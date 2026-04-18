from __future__ import annotations

from typing import Optional, Dict, Union
import asyncio
import re

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import (
    emb,
    send_log,
    voice_arrow,
    is_temp_vc_id,
    set_delete_task,
    cancel_delete_task,
    track_temp_vc,
    untrack_temp_vc,
    bootstrap_track_temp_vcs,
)


async def mention_or_id(
    guild: discord.Guild,
    user_or_id: Union[int, discord.abc.User, discord.Member, None],
) -> str:
    if user_or_id is None:
        return "（未知成員）"
    if isinstance(user_or_id, discord.Member):
        return user_or_id.mention
    if isinstance(user_or_id, discord.User):
        uid = user_or_id.id
    elif isinstance(user_or_id, int):
        uid = user_or_id
    else:
        return f"User ID: {getattr(user_or_id, 'id', '未知')}"

    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except (discord.NotFound, discord.HTTPException):
            member = None
    return member.mention if member else f"User ID: {uid}"


def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == config.VERIFIED_ROLE_ID for r in m.roles)


def _get_timeout_seconds() -> float:
    try:
        return float(getattr(config, "TEMP_VC_EMPTY_SECONDS", 120))
    except Exception:
        return 120.0


def _get_sweep_interval_seconds() -> float:
    try:
        return float(getattr(config, "TEMP_VC_SWEEP_SECONDS", 300))
    except Exception:
        return 300.0


def _get_name_prefixes() -> list[str]:
    return [getattr(config, "TEMP_VC_PREFIX", "小隊call •")]


def _get_hub_channel_name() -> str:
    return str(getattr(config, "TEMP_VC_HUB_NAME", "開call")).strip() or "開call"


def _get_temp_channel_base_name() -> str:
    return str(getattr(config, "TEMP_VC_PREFIX", "小隊call •")).strip() or "小隊call •"


def _get_auto_vc_user_limit() -> Optional[int]:
    value = getattr(config, "TEMP_VC_DEFAULT_USER_LIMIT", None)
    if value in (None, "", 0, "0"):
        return None
    try:
        return max(1, min(99, int(value)))
    except Exception:
        return None


def _normalize_limit(limit: Optional[int], *, default: int = 32) -> int:
    if limit in (None, "", 0, "0"):
        return default
    try:
        return max(1, min(99, int(limit)))
    except Exception:
        return default


def _category_from_ctx_channel(
    ch: Optional[discord.abc.GuildChannel],
) -> Optional[discord.CategoryChannel]:
    if ch is None:
        return None
    if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
        return ch.category
    if isinstance(ch, discord.Thread):
        parent = ch.parent
        if isinstance(parent, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel)):
            return parent.category
    return None


def _is_hub_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    if not isinstance(channel, discord.VoiceChannel):
        return False
    return channel.name.strip() == _get_hub_channel_name()


def _normalize_temp_base_for_match() -> str:
    return _get_temp_channel_base_name().strip()


def _next_temp_channel_name_in_category(category: Optional[discord.CategoryChannel], guild: discord.Guild) -> str:
    base = _normalize_temp_base_for_match()
    pattern = re.compile(rf"^{re.escape(base)}\s+(\d+)$")
    used_numbers: set[int] = set()

    channels = category.channels if category else guild.channels
    for ch in channels:
        if not isinstance(ch, discord.VoiceChannel):
            continue
        m = pattern.fullmatch(ch.name.strip())
        if m:
            try:
                used_numbers.add(int(m.group(1)))
            except ValueError:
                pass

    n = 1
    while n in used_numbers:
        n += 1
    return f"{base} {n}"


async def schedule_delete_if_empty(channel: discord.VoiceChannel, *, force: bool = False):
    timeout = _get_timeout_seconds()
    ch_id = channel.id

    if not is_temp_vc_id(ch_id):
        return

    if not force and len(channel.members) > 0:
        cancel_delete_task(ch_id)
        return

    async def _task():
        try:
            print(f"⏳ Temp VC 倒數開始（{timeout:.0f}s）：#{channel.name} id={ch_id}")
            await asyncio.sleep(timeout)

            guild = channel.guild
            fresh = guild.get_channel(ch_id)
            if fresh is None:
                try:
                    fresh = await guild.fetch_channel(ch_id)
                except discord.NotFound:
                    print(f"🧹 目標已不存在（可能已手動刪）：id={ch_id}")
                    return
                except Exception as e:
                    print(f"⚠️ 取 channel 失敗 id={ch_id}：{e!r}")
                    return

            if isinstance(fresh, discord.VoiceChannel) and len(fresh.members) == 0 and is_temp_vc_id(ch_id):
                print(f"🧹 自動刪除空房：#{fresh.name}（id={ch_id}）")
                untrack_temp_vc(ch_id)
                try:
                    await fresh.delete(reason="Temp VC idle timeout")
                except discord.Forbidden:
                    print("❌ 沒有權限刪除語音房（請檢查 Bot 角色是否有『管理頻道』）。")
                except Exception as e:
                    print(f"❌ 刪除語音房失敗：{e!r}")
            else:
                print(f"🚫 取消刪除：房間有人或已不是 temp（id={ch_id}）")

        except asyncio.CancelledError:
            print(f"🛑 倒數已取消（有人進入/房間不再空）id={ch_id}")
            raise
        except Exception as e:
            print(f"⚠️ 倒數 task 發生例外 id={ch_id}：{e!r}")
        finally:
            cancel_delete_task(ch_id)

    cancel_delete_task(ch_id)
    set_delete_task(ch_id, asyncio.create_task(_task()))


class TempVCLimitSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="2 人", value="2"),
            discord.SelectOption(label="4 人", value="4"),
            discord.SelectOption(label="8 人", value="8"),
            discord.SelectOption(label="12 人", value="12"),
            discord.SelectOption(label="16 人", value="16"),
            discord.SelectOption(label="24 人", value="24"),
            discord.SelectOption(label="32 人（預設）", value="32"),
        ]
        super().__init__(
            placeholder="選擇房間人數上限（可留空，預設 32）",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(self.view, TempVCLimitView):
            return

        self.view.selected_limit = _normalize_limit(self.values[0], default=32)
        await interaction.response.edit_message(
            content=(
                f"📝 房間名稱：{self.view.room_name or '（留空）'}\n"
                f"👥 已選人數上限：{self.view.selected_limit}"
            ),
            view=self.view,
        )


class TempVCLimitView(discord.ui.View):
    def __init__(
        self,
        cog: "TempVC",
        *,
        owner_id: int,
        room_name: Optional[str],
        category: Optional[discord.CategoryChannel],
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id
        self.room_name = room_name.strip() if room_name else None
        self.category = category
        self.selected_limit: int = 32
        self.add_item(TempVCLimitSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個面板只限發起者使用。", ephemeral=True)
            return False
        return True

    @discord.ui.button(
        label="建立房間",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        ch = await self.cog._create_manual_temp_vc(
            interaction.guild,
            self.category,
            name=self.room_name,
            limit=self.selected_limit,
        )

        msg = (
            f"🍸 **Temp VC 已建立**：{ch.mention}\n"
            f"📝 **名稱**：`{ch.name}`\n"
            f"👥 **人數上限**：`{ch.user_limit or self.selected_limit}`\n"
            f"🎛️ **房間設定**：`bitrate={ch.bitrate // 1000}kbps` · `limit={ch.user_limit or self.selected_limit}`\n"
            f"✨ 祝你哋傾得開心。"
        )

        await interaction.followup.send(msg)
        self.stop()

    @discord.ui.button(
        label="用預設 32 建立",
        emoji="⚡",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def default_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        self.selected_limit = 32
        await interaction.response.defer(ephemeral=False)

        ch = await self.cog._create_manual_temp_vc(
            interaction.guild,
            self.category,
            name=self.room_name,
            limit=32,
        )

        msg = (
            f"🍸 **Temp VC 已建立**：{ch.mention}\n"
            f"📝 **名稱**：`{ch.name}`\n"
            f"👥 **人數上限**：`{ch.user_limit or 32}`\n"
            f"🎛️ **房間設定**：`bitrate={ch.bitrate // 1000}kbps` · `limit={ch.user_limit or 32}`\n"
            f"✨ 祝你哋傾得開心。"
        )

        await interaction.followup.send(msg)
        self.stop()

    @discord.ui.button(
        label="取消",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消建立小隊房。", view=None)
        self.stop()


class TempVCNameModal(discord.ui.Modal, title="建立小隊房"):
    room_name = discord.ui.TextInput(
        label="房間名稱",
        placeholder="可留空，例如：Apex / Rank / 深夜房",
        required=False,
        max_length=50,
    )

    def __init__(self, cog: "TempVC"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not user_can_run_tempvc(interaction):
            await interaction.response.send_message("你未有使用 Temp VC 權限。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        category = _category_from_ctx_channel(interaction.channel)
        name_value = str(self.room_name.value).strip() or None

        await interaction.response.send_message(
            content=(
                f"📝 房間名稱：{name_value or '（留空）'}\n"
                f"👥 請選擇房間人數上限（可直接用預設 32）"
            ),
            view=TempVCLimitView(
                self.cog,
                owner_id=interaction.user.id,
                room_name=name_value,
                category=category,
            ),
            ephemeral=True,
        )


class TempVC(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bootstrapped = False
        self._sweeper_task: Optional[asyncio.Task] = None
        self._creating_for_members: set[int] = set()

    def cog_unload(self):
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()

    async def _create_manual_temp_vc(
        self,
        guild: discord.Guild,
        category: Optional[discord.CategoryChannel],
        *,
        name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> discord.VoiceChannel:
        base = _get_temp_channel_base_name()
        vc_name = f"{base} {name.strip()}" if name and name.strip() else _next_temp_channel_name_in_category(category, guild)

        kwargs: Dict[str, object] = {"bitrate": guild.bitrate_limit}
        kwargs["user_limit"] = _normalize_limit(limit, default=32)

        ch = await guild.create_voice_channel(
            vc_name,
            category=category,
            reason="Create temp VC (bartender)",
            **kwargs,
        )
        track_temp_vc(ch.id)
        print(f"✅ 建立 Temp VC：#{ch.name}（id={ch.id}）於 {category.name if category else '根目錄'}")
        await schedule_delete_if_empty(ch, force=False)
        return ch

    async def _teardown_temp_vc(self, target: discord.VoiceChannel) -> None:
        untrack_temp_vc(target.id)
        cancel_delete_task(target.id)
        print(f"🗑️ 手動刪除 Temp VC：#{target.name}（id={target.id}）")
        await target.delete(reason="Manual teardown temp VC")

    async def create_temp_vc_from_menu(self, interaction: discord.Interaction):
        if not user_can_run_tempvc(interaction):
            await interaction.response.send_message("你未有使用 Temp VC 權限。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        await interaction.response.send_modal(TempVCNameModal(self))

    async def teardown_temp_vc_from_menu(self, interaction: discord.Interaction):
        if not user_can_run_tempvc(interaction):
            await interaction.response.send_message("你未有使用 Temp VC 權限。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("你而家未身處任何語音房。", ephemeral=True)
            return

        target = interaction.user.voice.channel
        if not isinstance(target, discord.VoiceChannel) or not is_temp_vc_id(target.id):
            await interaction.response.send_message("你目前身處嘅唔係由 Bot 建立嘅臨時語音房。", ephemeral=True)
            return

        await self._teardown_temp_vc(target)
        await interaction.response.send_message("✅ 已刪除你目前嘅 Temp VC。", ephemeral=True)

    async def _create_temp_vc_for_member(
        self,
        member: discord.Member,
        source_channel: discord.VoiceChannel,
    ) -> Optional[discord.VoiceChannel]:
        guild = member.guild
        category = source_channel.category
        vc_name = _next_temp_channel_name_in_category(category, guild)

        kwargs: Dict[str, object] = {"bitrate": guild.bitrate_limit}
        default_limit = _get_auto_vc_user_limit()
        if default_limit is not None:
            kwargs["user_limit"] = default_limit

        try:
            ch = await guild.create_voice_channel(
                vc_name,
                category=category,
                reason=f"Auto create temp VC for {member} via hub channel",
                **kwargs,
            )
        except discord.Forbidden:
            print("❌ 建立自動 temp VC 失敗：缺少管理頻道權限")
            return None
        except Exception as e:
            print(f"❌ 建立自動 temp VC 失敗：{e!r}")
            return None

        track_temp_vc(ch.id)
        print(f"✅ 自動建立 Temp VC：#{ch.name}（id={ch.id}） for user={member.id} from hub=#{source_channel.name}")

        try:
            await member.move_to(ch, reason="Moved to newly auto-created temp VC")
        except discord.Forbidden:
            print("❌ Move member 失敗：缺少 Move Members 權限")
            await schedule_delete_if_empty(ch, force=False)
            return ch
        except Exception as e:
            print(f"❌ Move member 去 temp VC 失敗：{e!r}")
            await schedule_delete_if_empty(ch, force=False)
            return ch

        cancel_delete_task(ch.id)
        return ch

    @commands.Cog.listener()
    async def on_ready(self):
        if self._bootstrapped:
            return
        self._bootstrapped = True

        for g in self.bot.guilds:
            try:
                ids = await bootstrap_track_temp_vcs(g, name_prefixes=_get_name_prefixes())
                for cid in ids:
                    ch = g.get_channel(cid)
                    if ch is None:
                        try:
                            ch = await g.fetch_channel(cid)
                        except discord.NotFound:
                            continue
                        except Exception as e:
                            print(f"[TempVC bootstrap] fetch_channel 失敗 cid={cid}：{e!r}")
                            continue

                    if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id):
                        await schedule_delete_if_empty(ch, force=True)
            except Exception as e:
                print(f"[TempVC bootstrap] {g.name} 失敗：{e!r}")

        interval = _get_sweep_interval_seconds()
        if interval > 0:
            self._sweeper_task = asyncio.create_task(self._sweeper_loop(interval))
            print(f"[TempVC] safety sweeper started (interval={interval:.0f}s)")
        else:
            print("[TempVC] safety sweeper disabled (TEMP_VC_SWEEP_SECONDS <= 0)")

    async def _sweeper_loop(self, interval: float):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(interval)
                for g in self.bot.guilds:
                    try:
                        ids = await bootstrap_track_temp_vcs(g, name_prefixes=_get_name_prefixes())
                        for cid in ids:
                            ch = g.get_channel(cid)
                            if ch is None:
                                try:
                                    ch = await g.fetch_channel(cid)
                                except discord.NotFound:
                                    continue
                                except Exception:
                                    continue

                            if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id) and len(ch.members) == 0:
                                await schedule_delete_if_empty(ch, force=True)
                    except Exception as e:
                        print(f"[TempVC sweeper] {g.name} sweep 失敗：{e!r}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TempVC sweeper] loop exception: {e!r}")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        if before.channel != after.channel:
            mtxt = await mention_or_id(member.guild, member)
            if not before.channel and after.channel:
                await send_log(member.guild, emb("Voice Join", f"🎤 {mtxt} {voice_arrow(before.channel, after.channel)}", 0x57F287))
            elif before.channel and not after.channel:
                await send_log(member.guild, emb("Voice Leave", f"🔇 {mtxt} {voice_arrow(before.channel, after.channel)}", 0xED4245))
            else:
                await send_log(member.guild, emb("Voice Move", f"🔀 {mtxt} {voice_arrow(before.channel, after.channel)}", 0x5865F2))

        if before.channel and is_temp_vc_id(before.channel.id):
            await schedule_delete_if_empty(before.channel, force=True)

        if after.channel and is_temp_vc_id(after.channel.id):
            cancel_delete_task(after.channel.id)

        if (
            after.channel
            and _is_hub_channel(after.channel)
            and before.channel != after.channel
            and member.id not in self._creating_for_members
        ):
            self._creating_for_members.add(member.id)
            try:
                created = await self._create_temp_vc_for_member(member, after.channel)
                if created is None:
                    try:
                        await member.send("我剛剛想幫你開臨時語音房，但建立失敗。請通知管理員檢查 Bot 權限設定。")
                    except Exception:
                        pass
            finally:
                self._creating_for_members.discard(member.id)

    @app_commands.command(name="vc_new", description="建立一個臨時語音房（空房 120 秒自動刪除）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(name="語音房名稱（可選）", limit="人數上限（可選；不填＝32）")
    async def vc_new(self, inter: discord.Interaction, name: Optional[str] = None, limit: Optional[int] = None):
        if not user_can_run_tempvc(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)
        if not inter.guild:
            return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

        category = _category_from_ctx_channel(inter.channel)
        await inter.response.defer(ephemeral=False)
        final_limit = _normalize_limit(limit, default=32)
        ch = await self._create_manual_temp_vc(inter.guild, category, name=name, limit=final_limit)

        msg = (
            f"🍸 **Temp VC 已建立**：{ch.mention}\n"
            f"📝 **名稱**：`{ch.name}`\n"
            f"👥 **人數上限**：`{ch.user_limit or final_limit}`\n"
            f"🎛️ **房間設定**：`bitrate={ch.bitrate // 1000}kbps` · `limit={ch.user_limit or final_limit}`\n"
            f"✨ 祝你哋傾得開心。"
        )

        await inter.followup.send(msg)

    @app_commands.command(name="vc_teardown", description="刪除由 Bot 建立的臨時語音房")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(channel="要刪嘅語音房（可選；唔填就刪你而家身處的 VC）")
    async def vc_teardown(self, inter: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
        if not user_can_run_tempvc(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)
        if not inter.guild:
            return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        target = channel
        if target is None and isinstance(inter.user, discord.Member) and inter.user.voice and inter.user.voice.channel:
            target = inter.user.voice.channel

        if not isinstance(target, discord.VoiceChannel):
            return await inter.followup.send("請指定或身處一個語音房。", ephemeral=True)
        if not is_temp_vc_id(target.id):
            return await inter.followup.send("呢個唔係由 Bot 建立的臨時語音房。", ephemeral=True)

        await self._teardown_temp_vc(target)
        await inter.followup.send("✅ 已刪除。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVC(bot))
