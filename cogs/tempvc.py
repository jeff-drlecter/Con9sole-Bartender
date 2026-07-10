from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper
from utils import (
    emb,
    send_log,
    voice_arrow,
    is_temp_vc_id,
    set_delete_task,
    clear_delete_task,
    cancel_delete_task,
    cancel_all_delete_tasks,
    track_temp_vc,
    untrack_temp_vc,
    bootstrap_track_temp_vcs,
)

log = logging.getLogger("con9sole-bartender.tempvc")

VC_LIMIT_USER_COOLDOWNS: dict[int, float] = {}
VC_LIMIT_CHANNEL_COOLDOWNS: dict[int, float] = {}

TEMP_VC_LIMIT_CHOICES: tuple[int, ...] = (2, 5, 8, 11, 12, 16, 24, 32)
MAX_ADMIN_SELECT_OPTIONS = 25


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


def _interaction_response_done(interaction: discord.Interaction) -> bool:
    try:
        return interaction.response.is_done()
    except Exception:
        return False


async def _send_interaction_message(
    interaction: discord.Interaction,
    content: str,
    *,
    ephemeral: bool = True,
    view: discord.ui.View | None = None,
) -> None:
    if _interaction_response_done(interaction):
        await interaction.followup.send(content, ephemeral=ephemeral, view=view)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral, view=view)


def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False

    member: discord.Member = inter.user
    perms = member.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True

    verified_role_id = getattr(config, "VERIFIED_ROLE_ID", None)
    if verified_role_id is None:
        return False

    return any(role.id == verified_role_id for role in member.roles)


def user_can_admin_teardown(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    perms = member.guild_permissions
    return bool(perms.administrator or perms.manage_channels or is_admin_or_helper(member))


def user_can_change_vc_limit(member: discord.Member) -> bool:
    perms = member.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True

    if is_admin_or_helper(member):
        return True

    allowed_role_ids = set(getattr(config, "VC_LIMIT_LEVEL_ROLE_IDS", set()))
    if not allowed_role_ids:
        return False

    return any(role.id in allowed_role_ids for role in member.roles)


def user_bypasses_vc_limit_cooldown(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return bool(perms.administrator or perms.manage_channels or is_admin_or_helper(member))


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


def _get_vc_limit_user_cooldown_seconds() -> float:
    try:
        return float(getattr(config, "VC_LIMIT_USER_COOLDOWN_SECONDS", 30))
    except Exception:
        return 30.0


def _get_vc_limit_channel_cooldown_seconds() -> float:
    try:
        return float(getattr(config, "VC_LIMIT_CHANNEL_COOLDOWN_SECONDS", 30))
    except Exception:
        return 30.0


def _get_vc_limit_min() -> int:
    try:
        return max(1, int(getattr(config, "VC_LIMIT_MIN", 1)))
    except Exception:
        return 1


def _get_vc_limit_max() -> int:
    try:
        return min(99, max(_get_vc_limit_min(), int(getattr(config, "VC_LIMIT_MAX", 99))))
    except Exception:
        return 99


def _normalize_limit(limit: Optional[int] | str, *, default: int = 32) -> int:
    if limit in (None, "", 0, "0"):
        return default

    try:
        return max(1, min(99, int(limit)))
    except Exception:
        return default


def _parse_manual_limit(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _format_seconds(seconds: float) -> str:
    seconds_int = max(0, int(seconds + 0.999))
    minutes, sec = divmod(seconds_int, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


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
        match = pattern.fullmatch(ch.name.strip())
        if match:
            try:
                used_numbers.add(int(match.group(1)))
            except ValueError:
                pass

    n = 1
    while n in used_numbers:
        n += 1
    return f"{base} {n}"


async def schedule_delete_if_empty(channel: discord.VoiceChannel, *, force: bool = False) -> None:
    timeout = _get_timeout_seconds()
    ch_id = channel.id

    if not is_temp_vc_id(ch_id):
        return

    if not force and len(channel.members) > 0:
        cancel_delete_task(ch_id)
        return

    async def _task() -> None:
        try:
            log.debug("Temp VC deletion countdown started: channel=%s timeout=%s", ch_id, timeout)
            await asyncio.sleep(timeout)

            guild = channel.guild
            fresh = guild.get_channel(ch_id)
            if fresh is None:
                try:
                    fresh = await guild.fetch_channel(ch_id)
                except discord.NotFound:
                    log.info("Temp VC already deleted before countdown completed: channel=%s", ch_id)
                    return
                except Exception:
                    log.exception("Failed to fetch temp VC during deletion: channel=%s", ch_id)
                    return

            if isinstance(fresh, discord.VoiceChannel) and len(fresh.members) == 0 and is_temp_vc_id(ch_id):
                log.info("Deleting empty temp VC: channel=%s name=%s", ch_id, fresh.name)
                untrack_temp_vc(ch_id)
                try:
                    await fresh.delete(reason="Temp VC idle timeout")
                except discord.Forbidden:
                    log.error("Missing permission to delete temp VC: channel=%s", ch_id)
                except Exception:
                    log.exception("Failed to delete temp VC: channel=%s", ch_id)
            else:
                log.debug("Skipped temp VC deletion because it is occupied or untracked: channel=%s", ch_id)

        except asyncio.CancelledError:
            log.debug("Temp VC deletion countdown cancelled: channel=%s", ch_id)
            raise
        except Exception:
            log.exception("Temp VC deletion countdown failed: channel=%s", ch_id)
        finally:
            clear_delete_task(ch_id, asyncio.current_task())

    cancel_delete_task(ch_id)
    set_delete_task(ch_id, asyncio.create_task(_task()))


def _build_created_message(ch: discord.VoiceChannel, limit: int) -> str:
    actual_limit = ch.user_limit or limit
    return (
        f"✅ **Temp VC 已建立**：{ch.mention}\n"
        f"📝 **名稱**：`{ch.name}`\n"
        f"👥 **人數上限**：`{actual_limit}`\n"
        f"⚙️ **房間設定**：`bitrate={ch.bitrate // 1000}kbps` · `limit={actual_limit}`\n"
        f"✨ 祝你哋傾得開心。"
    )


def _build_control_panel_message(ch: discord.VoiceChannel) -> str:
    current_limit = ch.user_limit or "無限制"
    return (
        "🎛️ **小隊 call 控制**\n\n"
        f"目前房間：{ch.mention}\n"
        f"📝 名稱：`{ch.name}`\n"
        f"👥 目前人數：`{len(ch.members)}`\n"
        f"🔢 目前上限：`{current_limit}`\n\n"
        "可用操作：\n"
        "👥 **改人數上限** — Lv 15+ / Helper / Admin\n"
        "🧹 **刪除小隊 call** — 只可喺房內得返自己一個時使用"
    )


def _build_admin_teardown_panel_message(channels: list[discord.VoiceChannel]) -> str:
    if not channels:
        return "🧹 **Admin VC Teardown**\n\n目前無可刪除嘅 Bot Temp VC。"

    shown = min(len(channels), MAX_ADMIN_SELECT_OPTIONS)
    extra = len(channels) - shown
    extra_text = f"\n\n⚠️ 目前共有 `{len(channels)}` 間 Temp VC，Discord dropdown 最多顯示 `{shown}` 間。" if extra > 0 else ""
    return (
        "🧹 **Admin VC Teardown**\n\n"
        "請先喺 dropdown 選擇要刪除嘅小隊 call。\n"
        "選完之後，系統會再要求你按 **確認刪除**。"
        f"{extra_text}"
    )


def _build_admin_confirm_message(ch: discord.VoiceChannel) -> str:
    limit = ch.user_limit or "無限制"
    return (
        "🧹 **確認刪除小隊 call？**\n\n"
        f"房間：{ch.mention}\n"
        f"📝 名稱：`{ch.name}`\n"
        f"👥 目前人數：`{len(ch.members)}`\n"
        f"🔢 人數上限：`{limit}`\n\n"
        "⚠️ 此操作會即時刪除語音房，不能復原。"
    )


def _channel_sort_key(ch: discord.VoiceChannel) -> tuple[str, str, int]:
    category_name = ch.category.name if ch.category else ""
    return (category_name.lower(), ch.name.lower(), ch.id)


class TempVCLimitSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=f"{limit} 人", value=str(limit), emoji="⚡" if limit == 32 else "👥")
            for limit in TEMP_VC_LIMIT_CHOICES
        ]
        options[0].emoji = "2️⃣"
        options[1].emoji = "5️⃣"
        options[2].emoji = "8️⃣"
        options[-1].label = "32 人（預設）"

        super().__init__(
            placeholder="選擇人數上限；選完會即時建立房間",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, TempVCLimitView):
            return
        limit = _normalize_limit(self.values[0], default=32)
        await self.view.create_with_limit(interaction, limit)


class TempVCLimitView(discord.ui.View):
    def __init__(
        self,
        cog: "TempVC",
        *,
        owner_id: int,
        room_name: Optional[str],
        category: Optional[discord.CategoryChannel],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id
        self.room_name = room_name.strip() if room_name else None
        self.category = category
        self.created = False
        self.add_item(TempVCLimitSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個面板只限發起者使用。", ephemeral=True)
            return False
        return True

    async def create_with_limit(self, interaction: discord.Interaction, limit: int) -> None:
        if self.created:
            await interaction.response.send_message("呢個小隊房已經建立咗。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        self.created = True
        room_label = self.room_name or "自動編號"
        await interaction.response.edit_message(
            content=(
                f"✅ 已選擇人數上限：`{limit}`\n"
                f"📝 房間名稱：`{room_label}`\n"
                "⏳ 正在建立小隊房……"
            ),
            view=None,
        )

        try:
            ch = await self.cog._create_manual_temp_vc(
                interaction.guild,
                self.category,
                name=self.room_name,
                limit=limit,
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ 建立失敗：Bot 缺少 `Manage Channels` 權限。", ephemeral=True)
            self.stop()
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"❌ 建立失敗：Discord API 錯誤 `{type(exc).__name__}`。", ephemeral=True)
            self.stop()
            return
        except Exception as exc:
            await interaction.followup.send(f"❌ 建立失敗：`{type(exc).__name__}`。", ephemeral=True)
            self.stop()
            return

        msg = _build_created_message(ch, limit)
        control_view = TempVCControlView(self.cog, channel_id=ch.id)
        try:
            if interaction.channel is not None:
                await interaction.channel.send(msg, view=control_view)
            else:
                await interaction.followup.send(msg, view=control_view, ephemeral=False)
        except Exception:
            await interaction.followup.send(msg, view=control_view, ephemeral=False)

        self.stop()

    @discord.ui.button(label="用預設 32 建立", emoji="⚡", style=discord.ButtonStyle.primary, row=1)
    async def default_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.create_with_limit(interaction, 32)

    @discord.ui.button(label="取消", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消建立小隊房。", view=None)
        self.stop()


class ChangeLimitModal(discord.ui.Modal, title="修改小隊 call 人數上限"):
    new_limit = discord.ui.TextInput(
        label="新的人數上限",
        placeholder="請輸入 1-99，例如：11",
        required=True,
        max_length=2,
    )

    def __init__(self, cog: "TempVC", channel_id: int):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        limit = _parse_manual_limit(str(self.new_limit.value))
        await self.cog.apply_vc_limit_from_modal(interaction, self.channel_id, limit)


class TempVCControlView(discord.ui.View):
    def __init__(self, cog: "TempVC", *, channel_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.channel_id = channel_id

    @discord.ui.button(label="改人數上限", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def change_limit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ChangeLimitModal(self.cog, self.channel_id))

    @discord.ui.button(label="刪除小隊 call", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.delete_temp_vc_from_control(interaction, self.channel_id)

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        menu_cog = interaction.client.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "open_home_menu_from_button"):
            await menu_cog.open_home_menu_from_button(interaction)  # type: ignore[attr-defined]
            return
        await interaction.response.send_message("❌ Menu 功能未載入。", ephemeral=True)


class AdminTempVCSelect(discord.ui.Select):
    def __init__(self, cog: "TempVC", channels: list[discord.VoiceChannel]):
        self.cog = cog
        self.channel_ids = [ch.id for ch in channels[:MAX_ADMIN_SELECT_OPTIONS]]

        options: list[discord.SelectOption] = []
        for ch in channels[:MAX_ADMIN_SELECT_OPTIONS]:
            limit = ch.user_limit or "∞"
            category = ch.category.name if ch.category else "無分類"
            label = ch.name[:100]
            description = f"{len(ch.members)}人｜limit {limit}｜{category}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(ch.id),
                    description=description[:100],
                    emoji="🎧",
                )
            )

        super().__init__(
            placeholder="選擇要刪除嘅 Temp VC",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, AdminTempVCSelectView):
            await interaction.response.send_message("❌ Admin teardown view 狀態異常，請重新開啟。", ephemeral=True)
            return

        await self.view.select_channel(interaction, int(self.values[0]))


class AdminTempVCSelectView(discord.ui.View):
    def __init__(self, cog: "TempVC", *, owner_id: int, channels: list[discord.VoiceChannel]):
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id
        self.add_item(AdminTempVCSelect(cog, channels))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Admin Teardown 面板只限發起者使用。", ephemeral=True)
            return False

        if not isinstance(interaction.user, discord.Member) or not user_can_admin_teardown(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper / Manage Channels 權限先可以使用。", ephemeral=True)
            return False

        return True

    async def select_channel(self, interaction: discord.Interaction, channel_id: int) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return

        channel = interaction.guild.get_channel(channel_id)
        if channel is None:
            try:
                fetched = await interaction.guild.fetch_channel(channel_id)
                channel = fetched if isinstance(fetched, discord.VoiceChannel) else None
            except discord.NotFound:
                channel = None
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, discord.VoiceChannel) or not is_temp_vc_id(channel.id):
            await interaction.response.edit_message(
                content="❌ 呢間 Temp VC 已不存在，或者已不再係 Bot 建立嘅 Temp VC。",
                view=None,
            )
            self.stop()
            return

        await interaction.response.edit_message(
            content=_build_admin_confirm_message(channel),
            view=AdminTempVCConfirmView(self.cog, owner_id=interaction.user.id, channel_id=channel.id),
        )
        self.stop()

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Admin VC Teardown。", view=None)
        self.stop()


class AdminTempVCConfirmView(discord.ui.View):
    def __init__(self, cog: "TempVC", *, owner_id: int, channel_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.channel_id = channel_id
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個確認面板只限發起者使用。", ephemeral=True)
            return False

        if not isinstance(interaction.user, discord.Member) or not user_can_admin_teardown(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper / Manage Channels 權限先可以使用。", ephemeral=True)
            return False

        return True

    @discord.ui.button(label="確認刪除", emoji="✅", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個操作已經完成。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if channel is None:
            try:
                fetched = await interaction.guild.fetch_channel(self.channel_id)
                channel = fetched if isinstance(fetched, discord.VoiceChannel) else None
            except discord.NotFound:
                channel = None
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, discord.VoiceChannel) or not is_temp_vc_id(channel.id):
            await interaction.response.edit_message(
                content="❌ 呢間 Temp VC 已不存在，或者已不再係 Bot 建立嘅 Temp VC。",
                view=None,
            )
            self.stop()
            return

        channel_name = channel.name
        member_count = len(channel.members)

        try:
            await self.cog._teardown_temp_vc(channel)
        except discord.Forbidden:
            await interaction.response.edit_message(
                content="❌ 刪除失敗：Bot 缺少 `Manage Channels` 權限。",
                view=None,
            )
            self.stop()
            return
        except discord.HTTPException as exc:
            await interaction.response.edit_message(
                content=f"❌ 刪除失敗：Discord API 錯誤 `{type(exc).__name__}`。",
                view=None,
            )
            self.stop()
            return

        self.done = True
        await interaction.response.edit_message(
            content=f"✅ Admin Teardown 已刪除：`{channel_name}`（刪除前 `{member_count}` 人）",
            view=None,
        )
        self.stop()

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Admin VC Teardown。", view=None)
        self.stop()


class TempVCNameModal(discord.ui.Modal, title="建立小隊房"):
    room_name = discord.ui.TextInput(
        label="房間名稱",
        placeholder="可留空，例如：Apex / Rank / 深夜房",
        required=False,
        max_length=50,
    )

    def __init__(self, cog: "TempVC") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not user_can_run_tempvc(interaction):
            await interaction.response.send_message("你未有使用 Temp VC 權限。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        category = _category_from_ctx_channel(interaction.channel)
        name_value = str(self.room_name.value).strip() or None
        room_label = name_value or "自動編號"

        await interaction.response.send_message(
            content=(
                f"📝 房間名稱：`{room_label}`\n"
                "👥 請選擇人數上限；**選完會即時建立房間**。\n"
                "⚡ 或直接使用預設 `32` 建立。"
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
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._bootstrapped = False
        self._sweeper_task: Optional[asyncio.Task] = None
        self._creating_for_members: set[int] = set()

    def cog_unload(self) -> None:
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
        cancel_all_delete_tasks()

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        """Unified entrypoint for data/menu_registry.py."""
        await self.create_temp_vc_from_menu(interaction)

    def _get_current_member_temp_vc(self, interaction: discord.Interaction) -> tuple[discord.Member | None, discord.VoiceChannel | None, str | None]:
        if not interaction.guild:
            return None, None, "只可在伺服器使用。"

        if not isinstance(interaction.user, discord.Member):
            return None, None, "只可由伺服器成員使用。"

        member = interaction.user
        if not member.voice or not member.voice.channel:
            return member, None, "你而家未身處任何語音房。"

        channel = member.voice.channel
        if not isinstance(channel, discord.VoiceChannel):
            return member, None, "你目前身處嘅唔係語音房。"

        if not is_temp_vc_id(channel.id):
            return member, None, "你目前身處嘅唔係由 Bartender 建立嘅小隊 call。"

        return member, channel, None

    def _get_control_channel(self, interaction: discord.Interaction, channel_id: int) -> tuple[discord.Member | None, discord.VoiceChannel | None, str | None]:
        member, current_channel, error = self._get_current_member_temp_vc(interaction)
        if error or current_channel is None:
            return member, None, error

        if current_channel.id != channel_id:
            return member, None, "你已經離開原本嗰間小隊 call。請喺目前房間重新打開控制面板。"

        return member, current_channel, None

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
        log.info("Created temp VC: channel=%s name=%s category=%s", ch.id, ch.name, category.id if category else None)
        await schedule_delete_if_empty(ch, force=False)
        return ch

    async def _teardown_temp_vc(self, target: discord.VoiceChannel) -> None:
        untrack_temp_vc(target.id)
        cancel_delete_task(target.id)
        log.info("Deleting temp VC manually: channel=%s name=%s", target.id, target.name)
        await target.delete(reason="Manual teardown temp VC")

    async def get_all_temp_vcs(self, guild: discord.Guild) -> list[discord.VoiceChannel]:
        try:
            await bootstrap_track_temp_vcs(guild, name_prefixes=_get_name_prefixes())
        except Exception:
            log.exception("Failed to bootstrap temp VC admin list")

        channels = [
            ch
            for ch in guild.voice_channels
            if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id)
        ]
        return sorted(channels, key=_channel_sort_key)

    async def create_temp_vc_from_menu(self, interaction: discord.Interaction) -> None:
        if not user_can_run_tempvc(interaction):
            await interaction.response.send_message("你未有使用 Temp VC 權限。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        await interaction.response.send_modal(TempVCNameModal(self))

    async def open_control_panel_from_menu(self, interaction: discord.Interaction) -> None:
        member, channel, error = self._get_current_member_temp_vc(interaction)

        if error or member is None or channel is None:
            await _send_interaction_message(
                interaction,
                f"❌ {error or '搵唔到你目前嘅小隊 call。'}",
                ephemeral=True,
            )
            return

        await _send_interaction_message(
            interaction,
            _build_control_panel_message(channel),
            view=TempVCControlView(self, channel_id=channel.id),
            ephemeral=True,
        )

    async def apply_vc_limit_from_modal(
        self,
        interaction: discord.Interaction,
        channel_id: int,
        new_limit: int | None,
    ) -> None:
        member, channel, error = self._get_control_channel(interaction, channel_id)
        if error or member is None or channel is None:
            await interaction.response.send_message(f"❌ {error or '搵唔到你目前嘅小隊 call。'}", ephemeral=True)
            return

        if not user_can_change_vc_limit(member):
            await interaction.response.send_message(
                "❌ 呢個功能只限 **Lv 15 或以上會員** 使用。\n\n"
                "你目前未擁有 Lv 15+ 會員身份。\n"
                "可以繼續參與聊天提升 Amaribot 等級，升到 Lv 15 後再使用呢個功能。",
                ephemeral=True,
            )
            return

        min_limit = _get_vc_limit_min()
        max_limit = _get_vc_limit_max()
        if new_limit is None or new_limit < min_limit or new_limit > max_limit:
            await interaction.response.send_message(
                f"❌ 請輸入 `{min_limit}` 至 `{max_limit}` 之間嘅人數上限。",
                ephemeral=True,
            )
            return

        current_members = len(channel.members)
        if new_limit < current_members:
            await interaction.response.send_message(
                f"❌ 目前房內已有 `{current_members}` 人，不能把上限改成 `{new_limit}`。",
                ephemeral=True,
            )
            return

        old_limit = channel.user_limit or 0
        if old_limit == new_limit:
            await interaction.response.send_message(
                f"ℹ️ 呢間小隊 call 目前已經係 `{new_limit}` 人上限。",
                ephemeral=True,
            )
            return

        if not user_bypasses_vc_limit_cooldown(member):
            now = time.time()
            user_last = VC_LIMIT_USER_COOLDOWNS.get(member.id, 0.0)
            channel_last = VC_LIMIT_CHANNEL_COOLDOWNS.get(channel.id, 0.0)

            user_retry = _get_vc_limit_user_cooldown_seconds() - (now - user_last)
            channel_retry = _get_vc_limit_channel_cooldown_seconds() - (now - channel_last)
            retry = max(user_retry, channel_retry)

            if retry > 0:
                await interaction.response.send_message(
                    f"⏳ 呢個功能剛剛使用過，請等 `{_format_seconds(retry)}` 後再試。",
                    ephemeral=True,
                )
                return

        try:
            await channel.edit(user_limit=new_limit, reason=f"Temp VC limit changed by {member} ({member.id})")
        except discord.Forbidden:
            await interaction.response.send_message("❌ 修改失敗：Bot 缺少 `Manage Channels` 權限。", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"❌ 修改失敗：Discord API 錯誤 `{type(exc).__name__}`。", ephemeral=True)
            return

        if not user_bypasses_vc_limit_cooldown(member):
            now = time.time()
            VC_LIMIT_USER_COOLDOWNS[member.id] = now
            VC_LIMIT_CHANNEL_COOLDOWNS[channel.id] = now

        await interaction.response.send_message(
            f"✅ 已更新小隊 call 人數上限：`{old_limit or '無限制'}` → `{new_limit}`",
            ephemeral=True,
        )

    async def delete_temp_vc_from_control(self, interaction: discord.Interaction, channel_id: int) -> None:
        member, channel, error = self._get_control_channel(interaction, channel_id)
        if error or member is None or channel is None:
            await interaction.response.send_message(f"❌ {error or '搵唔到你目前嘅小隊 call。'}", ephemeral=True)
            return

        if len(channel.members) != 1 or channel.members[0].id != member.id:
            await interaction.response.send_message(
                "❌ 呢間小隊 call 仲有其他成員。\n\n"
                "請等到房內只剩你一個人，或者先叫其他成員離開後再刪除。\n"
                f"目前房內人數：`{len(channel.members)}`",
                ephemeral=True,
            )
            return

        await self._teardown_temp_vc(channel)
        await interaction.response.send_message("✅ 已刪除你目前嘅小隊 call。", ephemeral=True)

    async def open_admin_teardown_panel(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await _send_interaction_message(interaction, "❌ 只可在伺服器使用。", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not user_can_admin_teardown(interaction.user):
            await _send_interaction_message(
                interaction,
                "❌ 你需要 Admin / Helper / Manage Channels 權限先可以使用 VC Teardown。",
                ephemeral=True,
            )
            return

        channels = await self.get_all_temp_vcs(interaction.guild)
        if not channels:
            await _send_interaction_message(interaction, _build_admin_teardown_panel_message(channels), ephemeral=True)
            return

        await _send_interaction_message(
            interaction,
            _build_admin_teardown_panel_message(channels),
            view=AdminTempVCSelectView(self, owner_id=interaction.user.id, channels=channels),
            ephemeral=True,
        )

    async def teardown_temp_vc_from_menu(self, interaction: discord.Interaction) -> None:
        """Admin Tool entrypoint. Opens dropdown + confirm flow instead of direct deletion."""
        await self.open_admin_teardown_panel(interaction)

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
            log.error("Missing permission to create automatic temp VC: member=%s", member.id)
            return None
        except Exception:
            log.exception("Failed to create automatic temp VC: member=%s", member.id)
            return None

        track_temp_vc(ch.id)
        log.info("Created automatic temp VC: channel=%s member=%s hub=%s", ch.id, member.id, source_channel.id)

        try:
            await member.move_to(ch, reason="Moved to newly auto-created temp VC")
        except discord.Forbidden:
            log.error("Missing permission to move member into temp VC: member=%s channel=%s", member.id, ch.id)
            await schedule_delete_if_empty(ch, force=False)
            return ch
        except Exception:
            log.exception("Failed to move member into temp VC: member=%s channel=%s", member.id, ch.id)
            await schedule_delete_if_empty(ch, force=False)
            return ch

        cancel_delete_task(ch.id)
        return ch

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._bootstrapped:
            return

        self._bootstrapped = True

        for guild in self.bot.guilds:
            try:
                ids = await bootstrap_track_temp_vcs(guild, name_prefixes=_get_name_prefixes())
                for cid in ids:
                    ch = guild.get_channel(cid)
                    if ch is None:
                        try:
                            ch = await guild.fetch_channel(cid)
                        except discord.NotFound:
                            continue
                        except Exception:
                            log.exception("Failed to fetch temp VC during bootstrap: channel=%s", cid)
                            continue

                    if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id):
                        await schedule_delete_if_empty(ch, force=True)
            except Exception:
                log.exception("Temp VC bootstrap failed: guild=%s", guild.id)

        interval = _get_sweep_interval_seconds()
        if interval > 0:
            self._sweeper_task = asyncio.create_task(self._sweeper_loop(interval))
            log.info("Temp VC safety sweeper started: interval=%s", interval)
        else:
            log.info("Temp VC safety sweeper disabled")

    async def _sweeper_loop(self, interval: float) -> None:
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await asyncio.sleep(interval)
                for guild in self.bot.guilds:
                    try:
                        ids = await bootstrap_track_temp_vcs(guild, name_prefixes=_get_name_prefixes())
                        for cid in ids:
                            ch = guild.get_channel(cid)
                            if ch is None:
                                try:
                                    ch = await guild.fetch_channel(cid)
                                except discord.NotFound:
                                    continue
                                except Exception:
                                    continue

                            if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id) and len(ch.members) == 0:
                                await schedule_delete_if_empty(ch, force=True)
                    except Exception:
                        log.exception("Temp VC sweep failed: guild=%s", guild.id)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Temp VC sweeper loop failed")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        if before.channel != after.channel:
            mtxt = await mention_or_id(member.guild, member)
            if not before.channel and after.channel:
                await send_log(member.guild, emb("Voice Join", f"{mtxt} {voice_arrow(before.channel, after.channel)}", 0x57F287))
            elif before.channel and not after.channel:
                await send_log(member.guild, emb("Voice Leave", f"{mtxt} {voice_arrow(before.channel, after.channel)}", 0xED4245))
            else:
                await send_log(member.guild, emb("Voice Move", f"{mtxt} {voice_arrow(before.channel, after.channel)}", 0x5865F2))

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
    async def vc_new(self, inter: discord.Interaction, name: Optional[str] = None, limit: Optional[int] = None) -> None:
        if not user_can_run_tempvc(inter):
            await inter.response.send_message("你未有使用權限。", ephemeral=True)
            return

        if not inter.guild:
            await inter.response.send_message("只可在伺服器使用。", ephemeral=True)
            return

        category = _category_from_ctx_channel(inter.channel)
        await inter.response.defer(ephemeral=False)

        final_limit = _normalize_limit(limit, default=32)
        ch = await self._create_manual_temp_vc(inter.guild, category, name=name, limit=final_limit)
        await inter.followup.send(_build_created_message(ch, final_limit), view=TempVCControlView(self, channel_id=ch.id))

    @app_commands.command(name="vc_teardown", description="Admin/Helper：選擇並刪除由 Bot 建立的臨時語音房")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def vc_teardown(self, inter: discord.Interaction) -> None:
        await self.open_admin_teardown_panel(inter)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVC(bot))
