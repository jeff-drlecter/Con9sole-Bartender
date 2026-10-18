from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field

import discord
from discord.ext import commands

from core.action_guard import claim_action
from core.discord_interactions import require_public_send
from core.safe_send import send_or_followup
from core.ui import SafeModal, SafeView
from features import team_storage
from features.menu_stats import record_usage_sync

log = logging.getLogger("con9sole-bartender.teams")
STATE_TTL_SECONDS = 6 * 60 * 60
SWEEP_INTERVAL_SECONDS = 60


def infer_game_name(channel: object) -> str | None:
    """Use an explicit game forum; avoid guessing that a general category is a game."""
    parent = channel.parent if isinstance(channel, discord.Thread) else channel
    name = getattr(parent, "name", "")
    if name.endswith("-專區"):
        return name[:-3].strip()[:80] or None
    category = getattr(parent, "category", None)
    if category is not None:
        name = category.name.strip()
        role_names = {
            role.name.casefold().removesuffix(" player").strip()
            for role in category.guild.roles
        }
        if name.casefold() in role_names:
            return name[:80]
    return None


@dataclass
class TeamState:
    leader_id: int
    required: int
    mode: str
    channel_id: int
    guild_id: int
    message_id: int | None = None
    join_now: set[int] = field(default_factory=set)
    join_later: set[int] = field(default_factory=set)
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)

    def payload(self) -> dict:
        result = asdict(self)
        result["join_now"] = sorted(self.join_now)
        result["join_later"] = sorted(self.join_later)
        return result

    @classmethod
    def restore(cls, payload: dict) -> TeamState:
        result = cls(**payload)
        result.join_now = set(result.join_now)
        result.join_later = set(result.join_later)
        return result


class Teams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, TeamState] = {}
        self.views: dict[int, TeamView] = {}
        self._sweeper_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        team_storage.init_team_db()
        self.bot.add_view(CancelledTeamView(self))
        for message_id, payload in team_storage.load_teams():
            try:
                state = TeamState.restore(payload)
                if state.message_id != message_id:
                    raise ValueError("Team message ID mismatch")
                self.states[message_id] = state
                view = TeamView(self, state)
                self.views[message_id] = view
                self.bot.add_view(view, message_id=message_id)
            except (TypeError, ValueError):
                log.exception("Cannot restore team card: message=%s", message_id)
        self._sweeper_task = asyncio.create_task(self._sweeper_loop())

    async def cog_unload(self) -> None:
        if self._sweeper_task:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
        for view in self.views.values():
            view.stop()
        self.views.clear()

    def is_state_expired(self, state: TeamState) -> bool:
        return time.time() - state.created_at >= STATE_TTL_SECONDS

    async def _sweeper_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            for state in list(self.states.values()):
                if not state.cancelled and not self.is_state_expired(state):
                    continue
                view = self.views.get(state.message_id)
                if view is None:
                    continue
                async with view.lock:
                    try:
                        channel = self.bot.get_channel(
                            state.channel_id
                        ) or await self.bot.fetch_channel(state.channel_id)
                        message = await channel.fetch_message(state.message_id)
                        await message.edit(
                            content="⌛ 呢次招募已結束，可以重新開局。",
                            view=CancelledTeamView(self),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        self.remove_state_by_message_id(state.message_id)
                    except discord.NotFound:
                        try:
                            self.remove_state_by_message_id(state.message_id)
                        except Exception:
                            log.exception("Could not clean deleted team card")
                    except Exception:
                        log.exception(
                            "Could not expire team card: message=%s", state.message_id
                        )

    def remove_state_by_message_id(self, message_id: int | None) -> None:
        if message_id is not None and message_id in self.states:
            team_storage.delete_team(message_id)
            self.states.pop(message_id, None)
            view = self.views.pop(message_id, None)
            if view is not None:
                view.stop()

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.open_team_menu(interaction)

    async def open_team_menu(self, interaction: discord.Interaction) -> None:
        if not await require_public_send(interaction):
            return
        game = infer_game_name(interaction.channel)
        view = TeamCountView(self, interaction.user.id, game=game)
        await interaction.response.send_message(
            f"👥 {game or '搵人玩'} · 而家開局\n仲差幾位隊友？",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def create_team(
        self, interaction: discord.Interaction, count: int, mode: str
    ) -> bool:
        if not 1 <= count <= 16 or not mode.strip() or len(mode.strip()) > 100:
            await send_or_followup(
                interaction, content="請填遊戲名稱，同揀 1–16 位隊友。", ephemeral=True
            )
            return False
        with claim_action(
            "team-create", interaction.guild_id, interaction.user.id
        ) as claimed:
            if not claimed:
                await send_or_followup(
                    interaction, content="正在建立招募，請稍候。", ephemeral=True
                )
                return False
            if not await require_public_send(interaction):
                return False
            for existing in self.states.values():
                if (
                    existing.guild_id == interaction.guild_id
                    and existing.leader_id == interaction.user.id
                    and not existing.cancelled
                    and not self.is_state_expired(existing)
                ):
                    await send_or_followup(
                        interaction,
                        content=f"你已經有一個招募： https://discord.com/channels/{existing.guild_id}/{existing.channel_id}/{existing.message_id}",
                        ephemeral=True,
                    )
                    return False
            await interaction.response.defer(thinking=True, ephemeral=False)
            state = TeamState(
                interaction.user.id,
                count,
                mode.strip(),
                interaction.channel_id,
                interaction.guild_id,
            )
            view = TeamView(self, state)
            message = await interaction.edit_original_response(
                content=self.build_message(state),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            state.message_id = message.id
            try:
                team_storage.save_team(message.id, state.payload())
            except Exception:
                view.stop()
                await message.edit(content="招募暫時未能保存，請稍後再試。", view=None)
                log.exception("Could not persist team card")
                return False
            self.states[message.id] = state
            self.views[message.id] = view
            record_usage_sync("team", interaction.user.id, interaction.guild_id)
            return True

    def build_message(self, state: TeamState) -> str:
        if state.cancelled:
            return "招募已結束，可以重新開局。"
        remaining = max(state.required - len(state.join_now) - len(state.join_later), 0)
        names = lambda values: (
            " ".join(f"<@{uid}>" for uid in sorted(values)) or "暫時未有人"
        )
        status = (
            f"尚欠：**{remaining} 位**"
            if remaining
            else "✅ 已齊人，召集人可以開小隊 call。"
        )
        return (
            f"👥 **{discord.utils.escape_markdown(state.mode)} · 而家開局**\n"
            f"召集人：<@{state.leader_id}> · 搵緊 {state.required} 位隊友\n\n"
            f"{status}\n✅ 已加入：{names(state.join_now)}\n🕒 遲少少：{names(state.join_later)}\n\n"
            "招募 6 小時後自動結束。召集人可用「更多」修改或結束。"
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        self.remove_state_by_message_id(payload.message_id)


class TeamCountButton(discord.ui.Button):
    def __init__(self, count: int) -> None:
        super().__init__(label=f"{count} 位", style=discord.ButtonStyle.primary, row=0)
        self.count = count

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view.game:
            if await view.cog.create_team(interaction, self.count, view.game):
                await view.finish_prompt()
        else:
            await interaction.response.send_modal(
                TeamDetailsModal(view.cog, count=self.count, selection_view=view)
            )


class TeamCountView(SafeView):
    def __init__(self, cog: Teams, owner_id: int, *, game: str | None = None) -> None:
        super().__init__(timeout=180)
        self.cog, self.owner_id, self.game = cog, owner_id, game
        self.message: discord.InteractionMessage | None = None
        for count in (1, 2, 3):
            self.add_item(TeamCountButton(count))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "呢個選單只限召集人使用。", ephemeral=True
        )
        return False

    @discord.ui.button(label="自訂／換遊戲", style=discord.ButtonStyle.secondary, row=1)
    async def custom(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            TeamDetailsModal(self.cog, game=self.game, selection_view=self)
        )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(content="已取消招募。", view=None)

    async def finish_prompt(self) -> None:
        self.stop()
        if self.message is not None:
            try:
                await self.message.edit(content="✅ 招募已開好。", view=None)
            except discord.HTTPException:
                pass

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(
                    content="選單已過期，請用 `/menu` 重新開啟。", view=None
                )
            except discord.HTTPException:
                pass


class TeamDetailsModal(SafeModal, title="搵人玩"):
    game = discord.ui.TextInput(label="玩咩遊戲／模式？", max_length=100)
    count = discord.ui.TextInput(label="仲差幾位？（1–16）", max_length=2, default="2")

    def __init__(
        self,
        cog: Teams,
        *,
        count: int = 2,
        game: str | None = None,
        selection_view: TeamCountView | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.game.default = game
        self.count.default = str(count)
        self.selection_view = selection_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            count = int(self.count.value)
        except ValueError:
            count = 0
        if await self.cog.create_team(interaction, count, self.game.value):
            if self.selection_view is not None:
                await self.selection_view.finish_prompt()


class CancelledTeamView(SafeView):
    def __init__(self, cog: Teams) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="再開一局", emoji="👥", custom_id="teams:cancelled:team")
    async def team_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.cog.open_team_menu(interaction)

    @discord.ui.button(label="吧枱", emoji="🍸", custom_id="teams:cancelled:menu")
    async def menu_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        menu = interaction.client.get_cog("Menu")
        if menu:
            await menu.open_main_menu(interaction)
        else:
            await send_or_followup(
                interaction, content="請用 `/menu` 重新開啟。", ephemeral=True
            )


class TeamView(SafeView):
    def __init__(self, cog: Teams, state: TeamState) -> None:
        super().__init__(timeout=None)
        self.cog, self.state = cog, state
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.state.cancelled or self.cog.is_state_expired(self.state):
            await send_or_followup(
                interaction,
                content="招募已結束，請用 `/menu` 再開一局。",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction, previous: dict) -> bool:
        try:
            team_storage.save_team(self.state.message_id, self.state.payload())
        except Exception:
            self.state.__dict__.update(TeamState.restore(previous).__dict__)
            log.exception(
                "Could not save team change: message=%s", self.state.message_id
            )
            await interaction.followup.send(
                "暫時保存唔到，未有更改名單，請稍後再試。", ephemeral=True
            )
            return False
        try:
            await interaction.edit_original_response(
                content=self.cog.build_message(self.state),
                view=self,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            log.exception(
                "Team saved but card refresh failed: message=%s", self.state.message_id
            )
            await interaction.followup.send(
                "名單已保存，但畫面暫時更新唔到，請勿重複加入。", ephemeral=True
            )
        return True

    async def join(self, interaction: discord.Interaction, *, later: bool) -> None:
        await interaction.response.defer()
        async with self.lock:
            if self.state.cancelled or self.cog.is_state_expired(self.state):
                await interaction.followup.send("招募已結束。", ephemeral=True)
                return
            uid = interaction.user.id
            if uid == self.state.leader_id:
                await interaction.followup.send(
                    "你係召集人，唔使再加入。", ephemeral=True
                )
                return
            if uid in self.state.join_now or uid in self.state.join_later:
                await interaction.followup.send(
                    "你已經喺名單；可先按「退出」。", ephemeral=True
                )
                return
            if (
                len(self.state.join_now) + len(self.state.join_later)
                >= self.state.required
            ):
                await interaction.followup.send(
                    "已齊人，試下另一個招募啦。", ephemeral=True
                )
                return
            previous = self.state.payload()
            (self.state.join_later if later else self.state.join_now).add(uid)
            if not await self.refresh(interaction, previous):
                return
            await interaction.followup.send(
                "✅ 已加入；有變可以按「退出」。", ephemeral=True
            )

    @discord.ui.button(label="加入", emoji="✅", custom_id="teams:join_now", row=0)
    async def join_now(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.join(interaction, later=False)

    @discord.ui.button(label="遲少少", emoji="🕒", custom_id="teams:join_later", row=0)
    async def join_later(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.join(interaction, later=True)

    @discord.ui.button(label="退出", custom_id="teams:leave", row=0)
    async def leave(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        async with self.lock:
            if self.state.cancelled or self.cog.is_state_expired(self.state):
                await interaction.followup.send("招募已結束。", ephemeral=True)
                return
            previous = self.state.payload()
            self.state.join_now.discard(interaction.user.id)
            self.state.join_later.discard(interaction.user.id)
            await self.refresh(interaction, previous)

    @discord.ui.button(
        label="小隊 call", emoji="🎧", custom_id="teams:create_tempvc", row=1
    )
    async def create_tempvc(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.state.leader_id:
            await send_or_followup(
                interaction, content="由召集人開房就得啦。", ephemeral=True
            )
            return
        cog = interaction.client.get_cog("TempVC")
        if cog:
            await cog.menu_entry(interaction)
        else:
            await send_or_followup(
                interaction, content="小隊 call 暫時未準備好。", ephemeral=True
            )

    @discord.ui.button(label="更多", custom_id="teams:manage", row=1)
    async def manage(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.state.leader_id:
            await send_or_followup(
                interaction, content="呢個係召集人嘅管理選單。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "招募設定", view=TeamManageView(self), ephemeral=True
        )

    async def finish(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.state.leader_id:
            await send_or_followup(
                interaction, content="只有召集人可以結束招募。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            previous = self.state.payload()
            self.state.cancelled = True
            try:
                team_storage.save_team(self.state.message_id, self.state.payload())
            except Exception:
                self.state.__dict__.update(TeamState.restore(previous).__dict__)
                log.exception("Could not close team card")
                await interaction.edit_original_response(
                    content="保存失敗，招募未有結束，請稍後再試。"
                )
                return
            try:
                channel = interaction.client.get_channel(
                    self.state.channel_id
                ) or await interaction.client.fetch_channel(self.state.channel_id)
                message = await channel.fetch_message(self.state.message_id)
                await message.edit(
                    content=self.cog.build_message(self.state),
                    view=CancelledTeamView(self.cog),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.NotFound:
                pass
            except discord.HTTPException:
                await interaction.edit_original_response(
                    content="招募已結束，但畫面暫時更新唔到；酒保會再嘗試更新。"
                )
                return
            try:
                self.cog.remove_state_by_message_id(self.state.message_id)
            except Exception:
                log.exception("Closed team card awaiting cleanup")
        await interaction.edit_original_response(content="✅ 招募已結束。")


class TeamManageView(SafeView):
    def __init__(self, team: TeamView) -> None:
        super().__init__(timeout=180)
        self.team = team

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.team.state.leader_id:
            await send_or_followup(
                interaction, content="只限召集人使用。", ephemeral=True
            )
            return False
        return await self.team.interaction_check(interaction)

    @discord.ui.button(label="修改遊戲／人數", emoji="✏️")
    async def edit(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EditTeamModal(self.team))

    @discord.ui.button(label="結束招募", style=discord.ButtonStyle.danger)
    async def finish(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.team.finish(interaction)


class EditTeamModal(SafeModal, title="修改招募"):
    game = discord.ui.TextInput(label="遊戲／模式", max_length=100)
    count = discord.ui.TextInput(label="所需隊友總數（1–16）", max_length=2)

    def __init__(self, team: TeamView) -> None:
        super().__init__(timeout=180)
        self.team = team
        self.game.default = team.state.mode
        self.count.default = str(team.state.required)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (
            interaction.user.id != self.team.state.leader_id
            or not await self.team.interaction_check(interaction)
        ):
            return
        try:
            count = int(self.count.value)
        except ValueError:
            count = 0
        if not self.game.value.strip() or not 1 <= count <= 16:
            await send_or_followup(
                interaction, content="請填遊戲名稱同 1–16 位隊友。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.team.lock:
            state = self.team.state
            if state.cancelled or self.team.cog.is_state_expired(state):
                await interaction.edit_original_response(content="招募已結束。")
                return
            if count < len(state.join_now) + len(state.join_later):
                await interaction.edit_original_response(
                    content="人數唔可以少過已加入嘅隊友。"
                )
                return
            previous = state.payload()
            state.mode, state.required = self.game.value.strip(), count
            try:
                team_storage.save_team(state.message_id, state.payload())
            except Exception:
                state.__dict__.update(TeamState.restore(previous).__dict__)
                await interaction.edit_original_response(
                    content="保存失敗，招募未有更改。"
                )
                return
            channel = interaction.client.get_channel(
                state.channel_id
            ) or await interaction.client.fetch_channel(state.channel_id)
            try:
                message = await channel.fetch_message(state.message_id)
                await message.edit(
                    content=self.team.cog.build_message(state),
                    view=self.team,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                await interaction.edit_original_response(
                    content="設定已保存，但畫面暫時更新唔到。"
                )
                return
        await interaction.edit_original_response(content="✅ 招募已更新。")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Teams(bot))
