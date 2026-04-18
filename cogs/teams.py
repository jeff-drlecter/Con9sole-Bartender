from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands


STATE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
SWEEP_INTERVAL_SECONDS = 10 * 60  # 10 minutes


@dataclass
class TeamState:
    leader_id: int
    required: int
    mode: str
    channel_id: int
    message_id: int | None = None
    join_now: set[int] = field(default_factory=set)
    join_later: set[int] = field(default_factory=set)
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    last_touched: float = field(default_factory=time.time)


class Teams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, TeamState] = {}
        self._views_registered = False
        self._sweeper_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        if not self._views_registered:
            self.bot.add_view(CancelledTeamView(self))
            self._views_registered = True

        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = asyncio.create_task(self._sweeper_loop())

    def cog_unload(self) -> None:
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()

    def touch_state(self, state: TeamState) -> None:
        state.last_touched = time.time()

    def remove_state_by_message_id(self, message_id: int | None) -> None:
        if message_id is None:
            return
        self.states.pop(message_id, None)

    def get_state_by_message_id(self, message_id: int | None) -> TeamState | None:
        if message_id is None:
            return None
        return self.states.get(message_id)

    def is_state_expired(self, state: TeamState) -> bool:
        return (time.time() - state.last_touched) >= STATE_TTL_SECONDS

    async def _sweeper_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
                expired_ids = [
                    mid for mid, state in list(self.states.items()) if self.is_state_expired(state)
                ]
                for mid in expired_ids:
                    self.states.pop(mid, None)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def open_team_menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            content="請選擇需要多少位隊友：",
            view=TeamCountView(self, interaction.user.id),
            ephemeral=True,
        )

    async def open_cancelled_menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            content="❌ 呢個組隊行動已取消，你可以重新開一個新組隊。",
            view=CancelledTeamView(self),
            ephemeral=True,
        )

    async def create_team(self, interaction: discord.Interaction, count: int, mode: str) -> None:
        mode = mode.strip() or "未知"

        state = TeamState(
            leader_id=interaction.user.id,
            required=count,
            mode=mode,
            channel_id=interaction.channel_id,
        )

        message = await interaction.followup.send(
            content=self.build_message(state),
            view=TeamView(self, state),
        )

        state.message_id = message.id
        self.touch_state(state)
        self.states[message.id] = state

    def build_message(self, state: TeamState) -> str:
        filled = len(state.join_now) + len(state.join_later)
        remaining = max(state.required - filled, 0)

        def fmt(user_ids: set[int]) -> str:
            if not user_ids:
                return "暫時未有人"
            return " ".join(f"<@{uid}>" for uid in sorted(user_ids))

        if state.cancelled:
            return (
                "❌ 組隊行動已取消。\n"
                f"召集人：<@{state.leader_id}>"
            )

        if remaining == 0:
            status = "✅ 已齊人，可以開始！\n請按「建立小隊 call」開始對話。"
            remaining_text = "0（已滿）"
        else:
            status = "如果加入請按「立即加入」或「稍後加入」。"
            remaining_text = str(remaining)

        return (
            f"<@{state.leader_id}> 正在召集隊友，需要 {state.required} 位！\n"
            f"遊玩模式：{state.mode}\n\n"
            f"{status}\n"
            f"目前尚欠人數：{remaining_text}\n\n"
            f"可以立即加入：{fmt(state.join_now)}\n"
            f"可以稍後加入：{fmt(state.join_later)}"
        )

    def is_full(self, state: TeamState) -> bool:
        return len(state.join_now) + len(state.join_later) >= state.required

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        self.remove_state_by_message_id(payload.message_id)


class TeamCountView(discord.ui.View):
    def __init__(self, cog: Teams, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個選單只限召集人使用。", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="選擇需要幾多位隊友",
        options=[discord.SelectOption(label=str(i), value=str(i)) for i in range(1, 17)],
        custom_id="teams:count_select",
    )
    async def select_count(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        count = int(select.values[0])
        await interaction.response.send_modal(TeamModeModal(self.cog, count))

    async def on_timeout(self) -> None:
        self.stop()


class TeamModeModal(discord.ui.Modal, title="設定遊玩模式"):
    def __init__(self, cog: Teams, count: int) -> None:
        super().__init__()
        self.cog = cog
        self.count = count

        self.mode = discord.ui.TextInput(
            label="遊玩模式（可留空）",
            placeholder="例如：Rank / ARAM / 任務",
            required=False,
            max_length=100,
        )
        self.add_item(self.mode)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self.cog.create_team(interaction, self.count, str(self.mode.value))


class CancelledTeamView(discord.ui.View):
    def __init__(self, cog: Teams) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Menu",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="teams:cancelled:menu",
        row=0,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        menu_cog = interaction.client.get_cog("Menu")
        if not menu_cog:
            await interaction.response.send_message("❌ Menu 功能未載入。", ephemeral=True)
            return

        open_main_menu = getattr(menu_cog, "open_main_menu", None)
        if callable(open_main_menu):
            await open_main_menu(interaction)
            return

        try:
            from cogs.menu import MainMenuView, build_main_menu_embed

            await interaction.response.send_message(
                embed=build_main_menu_embed(interaction.user),
                view=MainMenuView(menu_cog),
                ephemeral=True,
            )
        except Exception:
            await interaction.response.send_message("❌ Menu 開啟失敗。", ephemeral=True)

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="teams:cancelled:team",
        row=0,
    )
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.open_team_menu(interaction)


class TeamView(discord.ui.View):
    def __init__(self, cog: Teams, state: TeamState) -> None:
        super().__init__(timeout=STATE_TTL_SECONDS)
        self.cog = cog
        self.state = state

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.cog.touch_state(self.state)
        await interaction.response.edit_message(
            content=self.cog.build_message(self.state),
            view=self,
        )

    async def on_timeout(self) -> None:
        self.cog.remove_state_by_message_id(self.state.message_id)
        self.stop()

    @discord.ui.button(
        label="立即加入",
        style=discord.ButtonStyle.success,
        custom_id="teams:join_now",
    )
    async def join_now(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.state.cancelled:
            await interaction.response.send_message("❌ 呢個組隊已取消。", ephemeral=True)
            return

        uid = interaction.user.id

        if uid == self.state.leader_id:
            await interaction.response.send_message("你係召集人，唔需要再加入名單。", ephemeral=True)
            return

        if uid in self.state.join_now:
            await interaction.response.send_message("你已經喺「立即加入」名單。", ephemeral=True)
            return

        if self.cog.is_full(self.state) and uid not in self.state.join_later:
            await interaction.response.send_message("❌ 呢個組隊已齊人。", ephemeral=True)
            return

        self.state.join_later.discard(uid)
        self.state.join_now.add(uid)
        await self.refresh(interaction)

    @discord.ui.button(
        label="稍後加入",
        style=discord.ButtonStyle.primary,
        custom_id="teams:join_later",
    )
    async def join_later(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.state.cancelled:
            await interaction.response.send_message("❌ 呢個組隊已取消。", ephemeral=True)
            return

        uid = interaction.user.id

        if uid == self.state.leader_id:
            await interaction.response.send_message("你係召集人，唔需要再加入名單。", ephemeral=True)
            return

        if uid in self.state.join_later:
            await interaction.response.send_message("你已經喺「稍後加入」名單。", ephemeral=True)
            return

        if self.cog.is_full(self.state) and uid not in self.state.join_now:
            await interaction.response.send_message("❌ 呢個組隊已齊人。", ephemeral=True)
            return

        self.state.join_now.discard(uid)
        self.state.join_later.add(uid)
        await self.refresh(interaction)

    @discord.ui.button(
        label="取消",
        style=discord.ButtonStyle.danger,
        custom_id="teams:cancel",
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        uid = interaction.user.id

        if uid == self.state.leader_id:
            self.state.cancelled = True
            self.cog.remove_state_by_message_id(self.state.message_id)
            await interaction.response.edit_message(
                content=self.cog.build_message(self.state),
                view=CancelledTeamView(self.cog),
            )
            self.stop()
            return

        if uid not in self.state.join_now and uid not in self.state.join_later:
            await interaction.response.send_message("你未加入呢個組隊。", ephemeral=True)
            return

        self.state.join_now.discard(uid)
        self.state.join_later.discard(uid)
        await self.refresh(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Teams(bot))
