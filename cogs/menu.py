from __future__ import annotations

import inspect
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper
from core.safe_send import safe_message_kwargs, send_or_followup
from data.menu_registry import MenuItem, get_menu_items

MENU_COLOR = 0x2B2D31
COOLDOWN_SECONDS = 3.0
MENTION_DEDUPE_TTL_SECONDS = 300.0
ROLE_TOOLS_TIMEOUT_SECONDS = 300
ROLE_BATCH_PAUSE_EVERY = 10
ROLE_BATCH_PAUSE_SECONDS = 0.8

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BARTENDER_IMAGE = ASSETS_DIR / "bartender.png"
BARTENDER_ATTACHMENT_NAME = "bartender.png"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATS_DB = DATA_DIR / "community_stats.sqlite3"

HK_TZ = timezone(timedelta(hours=8))
COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")
INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://threads.net/con9sole")
INVITE_CHANNEL_ID = getattr(config, "INVITE_CHANNEL_ID", None)
INVITE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
INVITE_MAX_USES = 10
INVITE_COOLDOWN_SECONDS = 10 * 60
RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

USER_MENU_COOLDOWNS: dict[int, float] = {}
USER_INVITE_COOLDOWNS: dict[int, float] = {}
MENTION_MESSAGE_DEDUPE: dict[int, float] = {}

FEATURE_LABELS: dict[str, str] = {
    "menu": "Menu",
    "home_menu": "Bartender Home",
    "team": "組隊",
    "tempvc": "小隊 call",
    "tempvc_control": "小隊 call 控制",
    "cheers": "打氣",
    "cheers_target": "幫人打氣",
    "drink": "調酒",
    "drink_gift": "賜酒",
    "drink_stats": "酒保紀錄",
    "drink_collection": "酒單收藏",
    "confession": "無名告白",
    "ig": "IG Page",
    "threads": "Threads Page",
    "invite": "生成邀請碼",
    "help": "幫助",
    "admin_tool": "Admin Tool",
    "admin_stats": "Admin Stats",
    "admin_reload": "Reload",
    "admin_role": "Role Tools",
    "admin_role_grant": "Role Grant",
    "admin_role_revoke": "Role Revoke",
    "admin_role_list": "Role List",
    "admin_ping": "Ping",
    "admin_vc_teardown": "VC Teardown",
    "mention_menu": "Mention Menu",
}

FEATURE_EMOJIS: dict[str, str] = {
    "menu": "⬅️",
    "home_menu": "🍸",
    "team": "👥",
    "tempvc": "🎧",
    "tempvc_control": "🎛️",
    "cheers": "🎉",
    "cheers_target": "🙌",
    "drink": "🍹",
    "drink_gift": "🥂",
    "drink_stats": "📊",
    "drink_collection": "🍾",
    "confession": "🕯️",
    "ig": "📸",
    "threads": "🧵",
    "invite": "🔗",
    "help": "ℹ️",
    "admin_tool": "🛠️",
    "admin_stats": "📊",
    "admin_reload": "🔄",
    "admin_role": "🎭",
    "admin_role_grant": "➕",
    "admin_role_revoke": "➖",
    "admin_role_list": "📋",
    "admin_ping": "🏓",
    "admin_vc_teardown": "🧹",
    "mention_menu": "💬",
}

STYLE_MAP: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "link": discord.ButtonStyle.link,
}

COG_METHOD_FALLBACKS: dict[str, list[str]] = {
    "team": ["menu_entry"],
    "tempvc": ["menu_entry"],
    "tempvc_control": ["open_control_panel_from_menu"],
    "cheers": ["menu_entry"],
    "cheers_target": ["cheer_for_member_entry"],
    "drink": ["menu_entry"],
    "drink_gift": ["gift_drink_entry"],
    "drink_stats": ["stats_entry"],
    "drink_collection": ["collection_entry"],
    "confession": ["menu_entry"],
}


@dataclass(frozen=True)
class RoleActionState:
    mode: str  # add / remove
    target_kind: str  # member / role
    target_member_id: int | None = None
    target_role_id: int | None = None
    apply_role_id: int | None = None
    include_bots: bool = False


# -----------------------------------------------------------------------------
# Stats
# -----------------------------------------------------------------------------

def init_stats_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS command_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature TEXT NOT NULL,
                user_id INTEGER,
                guild_id INTEGER,
                used_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_command_usage_feature_used_at
            ON command_usage(feature, used_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_command_usage_guild_used_at
            ON command_usage(guild_id, used_at)
            """
        )


def record_usage_sync(feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
    try:
        init_stats_db()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(STATS_DB) as conn:
            conn.execute(
                """
                INSERT INTO command_usage (feature, user_id, guild_id, used_at)
                VALUES (?, ?, ?, ?)
                """,
                (feature.lower().strip(), user_id, guild_id, now),
            )
    except Exception:
        pass


def get_stats(guild_id: int | None, days: int | None = None) -> list[tuple[str, int]]:
    init_stats_db()
    params: list[object] = []
    where: list[str] = []

    if guild_id is not None:
        where.append("guild_id = ?")
        params.append(guild_id)

    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where.append("used_at >= ?")
        params.append(since.isoformat())

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with sqlite3.connect(STATS_DB) as conn:
        rows = conn.execute(
            f"""
            SELECT feature, COUNT(*) AS total
            FROM command_usage
            {where_sql}
            GROUP BY feature
            ORDER BY total DESC
            """,
            params,
        ).fetchall()
    return [(str(row[0]), int(row[1])) for row in rows]


def get_total_usage(guild_id: int | None, days: int | None = None) -> int:
    init_stats_db()
    params: list[object] = []
    where: list[str] = []

    if guild_id is not None:
        where.append("guild_id = ?")
        params.append(guild_id)

    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where.append("used_at >= ?")
        params.append(since.isoformat())

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with sqlite3.connect(STATS_DB) as conn:
        row = conn.execute(f"SELECT COUNT(*) AS total FROM command_usage {where_sql}", params).fetchone()
    return int(row[0]) if row else 0


def format_stats_block(stats: list[tuple[str, int]]) -> str:
    if not stats:
        return "暫時未有紀錄。"

    lines: list[str] = []
    for feature, total in stats:
        emoji = FEATURE_EMOJIS.get(feature, "🔹")
        label = FEATURE_LABELS.get(feature, feature)
        lines.append(f"{emoji} **{label}**：`{total}` 次")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------

def can_use_admin(member: discord.Member | discord.User) -> bool:
    """Backward-compatible admin/helper checker."""
    return is_admin_or_helper(member)


can_use_admin_stats = can_use_admin


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


def _apply_bartender_thumbnail(embed: discord.Embed) -> None:
    if BARTENDER_IMAGE.exists():
        embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


def get_retry_after(user_id: int) -> float:
    last_used = USER_MENU_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cooldown(user_id: int) -> None:
    USER_MENU_COOLDOWNS[user_id] = time.time()


def get_invite_retry_after(user_id: int) -> float:
    last_used = USER_INVITE_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = INVITE_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_invite_cooldown(user_id: int) -> None:
    USER_INVITE_COOLDOWNS[user_id] = time.time()


def format_retry_seconds(seconds: float) -> str:
    seconds_int = max(0, int(seconds + 0.999))
    minutes, sec = divmod(seconds_int, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


def _cleanup_mention_dedupe(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    expired_ids = [
        message_id
        for message_id, seen_at in MENTION_MESSAGE_DEDUPE.items()
        if now - seen_at >= MENTION_DEDUPE_TTL_SECONDS
    ]
    for message_id in expired_ids:
        MENTION_MESSAGE_DEDUPE.pop(message_id, None)

    if len(MENTION_MESSAGE_DEDUPE) > 1000:
        newest = sorted(MENTION_MESSAGE_DEDUPE.items(), key=lambda item: item[1], reverse=True)[:300]
        MENTION_MESSAGE_DEDUPE.clear()
        MENTION_MESSAGE_DEDUPE.update(dict(newest))


def claim_mention_message(message_id: int) -> bool:
    now = time.time()
    _cleanup_mention_dedupe(now)
    if message_id in MENTION_MESSAGE_DEDUPE:
        return False
    MENTION_MESSAGE_DEDUPE[message_id] = now
    return True


def extract_discord_id(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"<@!?([0-9]{15,25})>|<@&([0-9]{15,25})>|([0-9]{15,25})", text)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return int(group)
            except ValueError:
                return None
    return None


async def fetch_member_by_id(guild: discord.Guild, raw: str) -> discord.Member | None:
    member_id = extract_discord_id(raw)
    if member_id is None:
        return None

    member = guild.get_member(member_id)
    if member is not None:
        return member

    try:
        return await guild.fetch_member(member_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


def get_member_from_state(guild: discord.Guild, member_id: int | None) -> discord.Member | None:
    if member_id is None:
        return None
    return guild.get_member(member_id)


def get_role_from_state(guild: discord.Guild, role_id: int | None) -> discord.Role | None:
    if role_id is None:
        return None
    return guild.get_role(role_id)


def get_batch_target_members(target_role: discord.Role, *, include_bots: bool) -> list[discord.Member]:
    members = list(target_role.members)
    if not include_bots:
        members = [member for member in members if not member.bot]
    members.sort(key=lambda member: member.display_name.casefold())
    return members


def mode_label(mode: str) -> str:
    return "加角色" if mode == "add" else "移除角色"


def mode_emoji(mode: str) -> str:
    return "➕" if mode == "add" else "➖"


# -----------------------------------------------------------------------------
# Role Tools embeds
# -----------------------------------------------------------------------------

def build_role_action_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎭 Role Tools｜{mode_label(mode)}",
        description=(
            "請選擇操作模式：\n\n"
            "👤 **單一成員** — 對指定一位成員加 / 移除角色\n"
            "🎭 **角色群組** — 對所有擁有某個角色的成員批量處理\n\n"
            "每個操作最後都會有確認頁，避免誤操作。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def build_member_select_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇成員",
        description=(
            "請用下面的 **User Select** 選擇目標成員。\n\n"
            "如果 Discord 搜尋不到該成員，請撳 **🆔 用 User ID**。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="User Select 搜尋不到時，可用 Developer Mode 複製 User ID。")
    return embed


def build_group_select_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇目標群組",
        description=(
            "請用下面的 **Role Select** 選擇目標角色群組。\n\n"
            "Bot 會對所有擁有此角色的成員執行操作。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="批量操作會在最後顯示預計影響人數。")
    return embed


def build_apply_role_select_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    if state.target_kind == "member":
        member = get_member_from_state(guild, state.target_member_id)
        target_text = member.mention if member else "`目標成員已不存在或未在 cache，請重新選擇`"
    else:
        role = get_role_from_state(guild, state.target_role_id)
        target_text = f"所有擁有 {role.mention} 的成員" if role else "`目標角色已不存在`"

    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇角色",
        description=(
            f"目標：{target_text}\n\n"
            f"請用下面的 **Role Select** 選擇要{mode_label(mode)}的角色。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="下一步會顯示確認頁。")
    return embed


def build_include_bots_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    target_role = get_role_from_state(guild, state.target_role_id)
    target_text = target_role.mention if target_role else "`目標角色已不存在`"
    apply_role = get_role_from_state(guild, state.apply_role_id)
    apply_text = apply_role.mention if apply_role else "`處理角色已不存在`"
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜批量設定",
        description=(
            f"目標群組：所有擁有 {target_text} 的成員\n"
            f"要{mode_label(mode)}：{apply_text}\n\n"
            "批量操作是否包含 Bot？\n\n"
            "建議保持 **不包含 Bot**，除非你清楚知道要處理 bot account。"
        ),
        color=MENU_COLOR,
    )
    return embed


def build_confirm_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    apply_role = get_role_from_state(guild, state.apply_role_id)
    apply_text = apply_role.mention if apply_role else "`處理角色已不存在`"

    if state.target_kind == "member":
        member = get_member_from_state(guild, state.target_member_id)
        target_text = member.mention if member else f"User ID `{state.target_member_id}`"
        impact_text = "`1` 位成員"
    else:
        target_role = get_role_from_state(guild, state.target_role_id)
        members = get_batch_target_members(target_role, include_bots=state.include_bots) if target_role else []
        target_text = f"所有擁有 {target_role.mention} 的成員" if target_role else "`目標角色已不存在`"
        impact_text = f"`{len(members)}` 位成員"

    embed = discord.Embed(
        title=f"{mode_emoji(mode)} 確認{mode_label(mode)}？",
        description=(
            f"目標：{target_text}\n"
            f"角色：{apply_text}\n"
            f"包含 Bot：`{'是' if state.include_bots else '否'}`\n"
            f"預計影響：{impact_text}\n\n"
            "⚠️ 此操作會立即修改成員角色。"
        ),
        color=0xED4245 if mode == "remove" else MENU_COLOR,
    )
    embed.set_footer(text="請確認無誤後先按確認。")
    return embed


def build_role_list_select_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📋 Role Tools｜查看角色",
        description=(
            "請用下面的 **User Select** 選擇要查看角色的成員。\n\n"
            "如果 Discord 搜尋不到該成員，請撳 **🆔 用 User ID 查詢**。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="User Select 搜尋不到時，可用 Developer Mode 複製 User ID。")
    return embed


# -----------------------------------------------------------------------------
# Main menu embeds
# -----------------------------------------------------------------------------

def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "👥 **組隊**｜召集隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **控制**｜管理目前小隊 call\n\n"
            "🎉 **打氣**｜為大家補充能量\n"
            "🙌 **幫人打氣**｜送一句打氣給其他成員\n"
            "🍹 **調酒**｜酒保特選\n"
            "🥂 **賜酒**｜賜一杯酒給其他成員\n\n"
            "⬅️ **Menu**｜進入吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text=f"Con9sole Bartender｜{user.display_name}，今晚由我為你服務。")
    return embed


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_home_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Bartender Home",
        description=(
            f"**{COMMUNITY_NAME} 吧枱主頁**\n\n"
            "👥 **組隊** — 召集隊友\n"
            "🎧 **小隊 call** — 建立臨時語音房\n"
            "🎛️ **小隊 call 控制** — 管理目前身處的小隊 call\n\n"
            "🎉 **打氣** — 為大家補充能量\n"
            "🙌 **幫人打氣** — 送一句打氣給其他成員\n"
            "🕯️ **無名告白** — 匿名投稿\n\n"
            "🍹 **調酒** — 酒保特選\n"
            "🥂 **賜酒** — 賜一杯酒給其他成員\n"
            "📊 **酒保紀錄** — 查看自己的酒保互動\n"
            "🍾 **酒單收藏** — 查看酒款收藏進度\n\n"
            "🔗 **生成邀請碼** — 7 日 / 10 次公開邀請連結\n"
            "📸 **IG Page** — 官方 Instagram\n"
            "🧵 **Threads Page** — 官方 Threads\n\n"
            "ℹ️ **幫助** — 使用說明\n"
            "🛠️ **Admin Tool** — 管理工具"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜選好服務後，直接撳下面按鈕。")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description=(
            "**Bartender 使用說明**\n\n"
            "👥 **組隊**｜發起組隊 / 招募隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **小隊 call 控制**｜改人數上限 / 刪除自己的小隊 call\n\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🙌 **幫人打氣**｜tag 一位成員，送一句打氣給對方\n\n"
            "🍹 **調酒**｜抽一杯酒保特選飲品\n"
            "🥂 **賜酒**｜tag 一位成員，賜一杯酒給對方\n"
            "📊 **酒保紀錄**｜查看自己叫酒 / 賜酒 / 收到賜酒紀錄\n"
            "🍾 **酒單收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n\n"
            "🕯️ **無名告白**｜匿名投稿\n"
            "📸 **IG Page / Threads Page**｜查看官方社交平台\n"
            "🔗 **生成邀請碼**｜7 日有效、最多 10 次使用，每人 10 分鐘一次\n"
            "🛠️ **Admin Tool**｜Admin / helpers 專用管理工具"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Admin Tool",
        description=(
            "**管理工具**\n\n"
            "📊 **Stats** — Community Bot 使用數據\n"
            "🔄 **Reload** — 直接重載所有 cogs\n"
            "🎭 **Role Tools** — Select Menu 角色管理工具\n"
            "🏓 **Ping** — Bot latency\n"
            "🧹 **VC Teardown** — 列出並刪除 Bot Temp VC\n\n"
            "⬅️ **Menu** — 返回吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Admin 工具只限授權成員使用。")
    return embed


def build_role_tools_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🎭 Role Tools",
        description=(
            "**Select Menu 角色管理工具**\n\n"
            "➕ **加角色** — 用選單選成員 / 角色，再確認執行\n"
            "➖ **移除角色** — 用選單選成員 / 角色，再確認執行\n"
            "📋 **查看角色** — 用 User Select 或 User ID 查看角色\n"
            "🧬 **新版本頻道** — 先保留為 slash 指令提示，不直接 button 執行\n\n"
            "✅ 平時用選單，搜尋不到成員時用 User ID fallback。\n"
            "⚠️ 批量處理前會顯示預計影響人數。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def build_role_channel_new_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🧬 新版本頻道",
        description=(
            "呢個功能涉及 clone channel、建立新版本 role 同權限設定，暫時保留用 slash command 執行。\n\n"
            "請使用：\n"
            "`/role_channel_new`\n\n"
            "建議只喺需要建立新版 channel / role 時使用。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜此功能暫不直接由 button 執行。")
    return embed


# -----------------------------------------------------------------------------
# Registry router
# -----------------------------------------------------------------------------

def _get_method(target: object, item: MenuItem) -> Callable[..., Awaitable[None]] | None:
    names = [item.method]
    names.extend(name for name in COG_METHOD_FALLBACKS.get(item.id, []) if name not in names)

    for name in names:
        candidate = getattr(target, name, None)
        if candidate and inspect.iscoroutinefunction(candidate):
            return candidate
    return None


async def _call_method_safely(method: Callable[..., Awaitable[None]], interaction: discord.Interaction) -> None:
    try:
        await method(interaction)
    except TypeError:
        try:
            await method(interaction, None)
        except TypeError:
            await method(interaction, to=None)


class RegistryButton(discord.ui.Button):
    def __init__(self, item: MenuItem):
        style = STYLE_MAP.get(item.style, discord.ButtonStyle.secondary)
        kwargs: dict[str, object] = {
            "label": item.label,
            "emoji": item.emoji,
            "style": style,
            "row": item.row,
        }
        if item.url:
            kwargs["url"] = item.url
        else:
            kwargs["custom_id"] = f"bartender:{item.layer}:{item.id}"

        super().__init__(**kwargs)
        self.item = item

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RegistryMenuView):
            await send_or_followup(interaction, content="❌ Menu view 狀態異常，請重新輸入 `/menu`。", ephemeral=True)
            return
        await self.view.handle_item(interaction, self.item)


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: "Menu", *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再撳。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def _record(self, interaction: discord.Interaction, feature: str) -> None:
        record_usage_sync(feature, interaction.user.id, interaction.guild_id)

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True
        await send_or_followup(
            interaction,
            content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以使用 Admin Tool。",
            ephemeral=True,
        )
        return False


class OwnerOnlyRoleToolView(BaseMenuView):
    def __init__(self, cog: "Menu", *, owner_id: int, timeout: float | None = ROLE_TOOLS_TIMEOUT_SECONDS) -> None:
        super().__init__(cog, timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return False
        if not await self._require_admin(interaction):
            return False
        return True


class RegistryMenuView(BaseMenuView):
    def __init__(self, cog: "Menu", layer: str) -> None:
        super().__init__(cog, timeout=None)
        self.layer = layer
        for item in get_menu_items(layer):
            self.add_item(RegistryButton(item))

    async def handle_item(self, interaction: discord.Interaction, item: MenuItem) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        if item.admin_only and not await self._require_admin(interaction):
            return

        if item.cog is None:
            await send_or_followup(interaction, content="❌ 呢個功能未設定 cog。", ephemeral=True)
            return

        target = self.cog if item.cog == "Menu" else interaction.client.get_cog(item.cog)
        if target is None:
            await send_or_followup(
                interaction,
                content=f"❌ `{item.cog}` 功能未載入。",
                ephemeral=True,
            )
            return

        method = _get_method(target, item)
        if method is None:
            await send_or_followup(
                interaction,
                content=f"❌ `{item.cog}` 未提供 `{item.method}` 入口。",
                ephemeral=True,
            )
            return

        try:
            await _call_method_safely(method, interaction)
        except discord.InteractionResponded:
            pass
        except Exception as exc:
            # 如果目標功能已經回覆過 user，就唔再補第二個錯誤訊息。
            # 例如 tempvc_control 已經提示「你而家未身處任何語音房」，
            # 就避免再出「AttributeError」造成重覆錯誤。
            if interaction.response.is_done():
                print(f"[Menu router suppressed] {item.id}: {type(exc).__name__}: {exc}")
                return

            await send_or_followup(
                interaction,
                content=f"❌ 執行 `{item.id}` 時出錯：`{type(exc).__name__}`。",
                ephemeral=True,
            )


class QuickBarView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "quick")


class HomeMenuView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "home")
        self.add_item(discord.ui.Button(label="IG Page", emoji="📸", style=discord.ButtonStyle.link, url=INSTAGRAM_URL, row=3))
        self.add_item(discord.ui.Button(label="Threads Page", emoji="🧵", style=discord.ButtonStyle.link, url=THREADS_URL, row=3))
        if RULES_URL:
            self.add_item(discord.ui.Button(label="Rules", emoji="🛡️", style=discord.ButtonStyle.link, url=RULES_URL, row=4))
        if HELP_URL:
            self.add_item(discord.ui.Button(label="Help Channel", emoji="❓", style=discord.ButtonStyle.link, url=HELP_URL, row=4))


class AdminToolView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "admin")


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, timeout=None)

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:help:home", row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self.cog.open_home_menu_from_button(interaction)


# -----------------------------------------------------------------------------
# Role Tools select flow
# -----------------------------------------------------------------------------

class RoleMemberIdModal(discord.ui.Modal, title="Role Tools｜用 User ID 選成員"):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="例如：123456789012345678",
        required=True,
        min_length=15,
        max_length=25,
    )

    def __init__(self, cog: "Menu", *, mode: str, owner_id: int):
        super().__init__(timeout=ROLE_TOOLS_TIMEOUT_SECONDS)
        self.cog = cog
        self.mode = mode
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        member = await fetch_member_by_id(interaction.guild, str(self.user_id.value))
        if member is None:
            await interaction.response.send_message(
                "❌ 找不到呢個 User ID 對應嘅伺服器成員。\n"
                "請確認：\n"
                "1. ID 正確\n"
                "2. 該用戶仍在伺服器內\n"
                "3. Bot 有 Server Members Intent / 權限讀取成員",
                ephemeral=True,
            )
            return

        state = RoleActionState(mode=self.mode, target_kind="member", target_member_id=member.id)
        await interaction.response.send_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
            ephemeral=True,
        )


class RoleListUserIdModal(discord.ui.Modal, title="Role Tools｜用 User ID 查看角色"):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="例如：123456789012345678",
        required=True,
        min_length=15,
        max_length=25,
    )

    def __init__(self, cog: "Menu", *, owner_id: int):
        super().__init__(timeout=ROLE_TOOLS_TIMEOUT_SECONDS)
        self.cog = cog
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        member = await fetch_member_by_id(interaction.guild, str(self.user_id.value))
        if member is None:
            await interaction.response.send_message(
                "❌ 找不到呢個 User ID 對應嘅伺服器成員。\n"
                "請確認 ID 正確，而且該用戶仍在伺服器內。",
                ephemeral=True,
            )
            return

        await self.cog.execute_role_list_for_member(interaction, member=member, edit_existing=False)


class RoleToolsView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, timeout=None)

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:admin", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await self.cog.open_admin_tool_from_button(interaction)

    @discord.ui.button(label="加角色", emoji="➕", style=discord.ButtonStyle.primary, custom_id="bartender:role_tools:grant", row=0)
    async def grant_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_action_embed("add"),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode="add"),
            ephemeral=True,
        )

    @discord.ui.button(label="移除角色", emoji="➖", style=discord.ButtonStyle.danger, custom_id="bartender:role_tools:revoke", row=0)
    async def revoke_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_action_embed("remove"),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode="remove"),
            ephemeral=True,
        )

    @discord.ui.button(label="查看角色", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:list", row=1)
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_list_select_embed(),
            view=RoleListSelectView(self.cog, owner_id=interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="新版本頻道", emoji="🧬", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:channel_new", row=1)
    async def channel_new_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await send_or_followup(
            interaction,
            embed=build_role_channel_new_help_embed(interaction.user),
            view=RoleToolsView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Menu", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:home", row=2)
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self.cog.open_home_menu_from_button(interaction)


class RoleActionTypeView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode

    @discord.ui.button(label="單一成員", emoji="👤", style=discord.ButtonStyle.primary, row=0)
    async def member_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_member_select_embed(self.mode),
            view=RoleMemberSelectView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="角色群組", emoji="🎭", style=discord.ButtonStyle.secondary, row=0)
    async def role_group_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_group_select_embed(self.mode),
            view=RoleGroupTargetSelectView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class MemberTargetSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇目標成員；搜尋不到請用 User ID", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleMemberSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_member_selected(interaction, self.values[0])


class RoleMemberSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode
        self.add_item(MemberTargetSelect())

    async def handle_member_selected(self, interaction: discord.Interaction, selected: discord.Member | discord.User) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return

        member = selected if isinstance(selected, discord.Member) else interaction.guild.get_member(selected.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(selected.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is None:
            await interaction.response.edit_message(content="❌ 找不到目標成員，請改用 User ID fallback。", embed=None, view=None)
            return

        state = RoleActionState(mode=self.mode, target_kind="member", target_member_id=member.id)
        await interaction.response.edit_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
        )

    @discord.ui.button(label="用 User ID", emoji="🆔", style=discord.ButtonStyle.primary, row=1)
    async def user_id_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoleMemberIdModal(self.cog, mode=self.mode, owner_id=interaction.user.id))

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_role_action_embed(self.mode),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class GroupTargetRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇目標角色群組", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleGroupTargetSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_target_role_selected(interaction, self.values[0])


class RoleGroupTargetSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode
        self.add_item(GroupTargetRoleSelect())

    async def handle_target_role_selected(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if role.is_default():
            await interaction.response.send_message("❌ 不能選擇 @everyone 作為目標群組。", ephemeral=True)
            return

        state = RoleActionState(mode=self.mode, target_kind="role", target_role_id=role.id)
        await interaction.response.edit_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
        )

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_role_action_embed(self.mode),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class ApplyRoleSelect(discord.ui.RoleSelect):
    def __init__(self, mode: str) -> None:
        super().__init__(placeholder=f"選擇要{mode_label(mode)}的角色", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleApplyRoleSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_apply_role_selected(interaction, self.values[0])


class RoleApplyRoleSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state
        self.add_item(ApplyRoleSelect(state.mode))

    async def handle_apply_role_selected(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if role.is_default():
            await interaction.response.send_message("❌ 不能加上或移除 @everyone。", ephemeral=True)
            return

        new_state = RoleActionState(
            mode=self.state.mode,
            target_kind=self.state.target_kind,
            target_member_id=self.state.target_member_id,
            target_role_id=self.state.target_role_id,
            apply_role_id=role.id,
            include_bots=False,
        )

        if new_state.target_kind == "role":
            await interaction.response.edit_message(
                embed=build_include_bots_embed(new_state.mode, new_state, interaction.guild),
                view=RoleIncludeBotsView(self.cog, owner_id=interaction.user.id, state=new_state),
            )
            return

        await interaction.response.edit_message(
            embed=build_confirm_embed(new_state.mode, new_state, interaction.guild),
            view=RoleConfirmView(self.cog, owner_id=interaction.user.id, state=new_state),
        )

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if self.state.target_kind == "member":
            await interaction.response.edit_message(
                embed=build_member_select_embed(self.state.mode),
                view=RoleMemberSelectView(self.cog, owner_id=interaction.user.id, mode=self.state.mode),
            )
        else:
            await interaction.response.edit_message(
                embed=build_group_select_embed(self.state.mode),
                view=RoleGroupTargetSelectView(self.cog, owner_id=interaction.user.id, mode=self.state.mode),
            )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleIncludeBotsView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state

    async def _go_confirm(self, interaction: discord.Interaction, include_bots: bool) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        new_state = RoleActionState(
            mode=self.state.mode,
            target_kind=self.state.target_kind,
            target_member_id=self.state.target_member_id,
            target_role_id=self.state.target_role_id,
            apply_role_id=self.state.apply_role_id,
            include_bots=include_bots,
        )
        await interaction.response.edit_message(
            embed=build_confirm_embed(new_state.mode, new_state, interaction.guild),
            view=RoleConfirmView(self.cog, owner_id=interaction.user.id, state=new_state),
        )

    @discord.ui.button(label="不包含 Bot", emoji="🚫", style=discord.ButtonStyle.primary, row=0)
    async def exclude_bots_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_confirm(interaction, include_bots=False)

    @discord.ui.button(label="包含 Bot", emoji="🤖", style=discord.ButtonStyle.secondary, row=0)
    async def include_bots_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_confirm(interaction, include_bots=True)

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleConfirmView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state
        self.done = False

    @discord.ui.button(label="確認", emoji="✅", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個操作已經完成。", ephemeral=True)
            return
        self.done = True
        await self.cog.execute_role_change_from_select(interaction, state=self.state)
        self.stop()

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleListUserSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇要查看角色的成員；搜尋不到請用 User ID", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleListSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_user_selected(interaction, self.values[0])


class RoleListSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: "Menu", *, owner_id: int) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.add_item(RoleListUserSelect())

    async def handle_user_selected(self, interaction: discord.Interaction, selected: discord.Member | discord.User) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return

        member = selected if isinstance(selected, discord.Member) else interaction.guild.get_member(selected.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(selected.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is None:
            await interaction.response.edit_message(content="❌ 找不到指定成員，請改用 User ID fallback。", embed=None, view=None)
            return

        await self.cog.execute_role_list_for_member(interaction, member=member, edit_existing=True)

    @discord.ui.button(label="用 User ID 查詢", emoji="🆔", style=discord.ButtonStyle.primary, row=1)
    async def user_id_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoleListUserIdModal(self.cog, owner_id=interaction.user.id))

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消查看角色。", embed=None, view=None)
        self.stop()


# Backward-compatible aliases used by other cogs.
MainMenuView = QuickBarView
CommunityHubView = HomeMenuView
MenuEntryView = QuickBarView


def build_menu_entry_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)


def build_full_menu_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)


# -----------------------------------------------------------------------------
# Cog
# -----------------------------------------------------------------------------

class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False
        init_stats_db()

    async def _enforce_command_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再用 /menu。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def record_usage(self, feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
        record_usage_sync(feature, user_id, guild_id)

    async def execute_role_change_from_select(self, interaction: discord.Interaction, *, state: RoleActionState) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            return

        role_cog = interaction.client.get_cog("RoleManager")
        if role_cog is None or not hasattr(role_cog, "_apply_role_change"):
            await interaction.response.edit_message(content="❌ RoleManager cog 未載入，請先 `/reload role`。", embed=None, view=None)
            return

        apply_role = get_role_from_state(interaction.guild, state.apply_role_id)
        if apply_role is None:
            await interaction.response.edit_message(content="❌ 要處理嘅角色已不存在。", embed=None, view=None)
            return

        target_member: discord.Member | None = None
        target_role: discord.Role | None = None

        if state.target_kind == "member":
            target_member = get_member_from_state(interaction.guild, state.target_member_id)
            if target_member is None and state.target_member_id is not None:
                try:
                    target_member = await interaction.guild.fetch_member(state.target_member_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    target_member = None
            if target_member is None:
                await interaction.response.edit_message(content="❌ 目標成員已不存在，或 Bot 無法讀取該成員。", embed=None, view=None)
                return
        else:
            target_role = get_role_from_state(interaction.guild, state.target_role_id)
            if target_role is None:
                await interaction.response.edit_message(content="❌ 目標角色群組已不存在。", embed=None, view=None)
                return

        feature = "admin_role_grant" if state.mode == "add" else "admin_role_revoke"
        record_usage_sync(feature, interaction.user.id, interaction.guild_id)

        try:
            await role_cog._apply_role_change(  # type: ignore[attr-defined]
                interaction,
                role_id=str(apply_role.id),
                target_member=target_member,
                target_role=target_role,
                include_bots=state.include_bots,
                mode=state.mode,
            )
        except discord.InteractionResponded:
            return
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"⚠️ Role Tools 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )

    async def execute_role_list_for_member(
        self,
        interaction: discord.Interaction,
        *,
        member: discord.Member,
        edit_existing: bool = True,
    ) -> None:
        if not interaction.guild:
            if edit_existing:
                await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            else:
                await interaction.response.send_message("⚠️ 呢個工具只可以喺伺服器內使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            if edit_existing:
                await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            else:
                await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        roles = [role for role in member.roles if not role.is_default()]
        roles.sort(key=lambda role: role.position, reverse=True)
        record_usage_sync("admin_role_list", interaction.user.id, interaction.guild_id)

        if not roles:
            content = f"ℹ️ {member.mention} 沒有任何自訂角色。"
            if edit_existing:
                await interaction.response.edit_message(content=content, embed=None, view=None)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        lines = [f"{role.mention} (ID: `{role.id}`)" for role in roles]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current_len + len(line) + 1 > 3800:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))

        embed = discord.Embed(
            title=f"📋 {member.display_name} 的角色（高→低）",
            description=chunks[0],
            color=MENU_COLOR,
        )
        embed.set_footer(text=f"共有 {len(roles)} 個角色")

        if edit_existing:
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    async def open_main_menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_home_menu_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_help_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("help", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_admin_tool_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_tool", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self),
            ephemeral=True,
        )

    async def create_invite_link_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)

        if not can_use_admin(interaction.user):
            retry_after = get_invite_retry_after(interaction.user.id)
            if retry_after > 0:
                await send_or_followup(
                    interaction,
                    content=f"⏳ 你啱啱已經產生過邀請碼，請等 {format_retry_seconds(retry_after)} 後再試。",
                    ephemeral=True,
                )
                return

        record_usage_sync("invite", interaction.user.id, interaction.guild_id)

        if INVITE_CHANNEL_ID is None:
            await send_or_followup(
                interaction,
                content=(
                    "⚠️ 未設定邀請入口頻道。\n"
                    "請先喺 `config.py` 加：\n"
                    "`INVITE_CHANNEL_ID: int = 你的channel_id`"
                ),
                ephemeral=True,
            )
            return

        channel = interaction.client.get_channel(int(INVITE_CHANNEL_ID))
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(int(INVITE_CHANNEL_ID))
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            await send_or_followup(
                interaction,
                content="⚠️ 搵唔到指定邀請入口頻道，請檢查 `INVITE_CHANNEL_ID`。",
                ephemeral=True,
            )
            return

        try:
            invite = await channel.create_invite(
                max_age=INVITE_MAX_AGE_SECONDS,
                max_uses=INVITE_MAX_USES,
                unique=True,
                temporary=False,
                reason=f"Invite generated by {interaction.user} ({interaction.user.id}) via Bartender menu",
            )
        except discord.Forbidden:
            await send_or_followup(
                interaction,
                content=f"❌ Bartender 無權喺 {channel.mention} 建立 invite，請開啟 `Create Instant Invite` 權限。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 建立邀請碼失敗：{type(exc).__name__}",
                ephemeral=True,
            )
            return

        if not can_use_admin(interaction.user):
            touch_invite_cooldown(interaction.user.id)

        public_message = (
            "🔗 **邀請碼已生成：**\n"
            f"{invite.url}\n\n"
            "有效期：`7 日`\n"
            "使用次數：`最多 10 次`\n"
            "成員類型：`非 temporary member`\n\n"
            "大家可以 copy 呢條 link share 畀朋友加入社群。"
        )

        try:
            if interaction.channel is None:
                raise RuntimeError("No interaction channel")
            await interaction.channel.send(public_message)
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 邀請碼已建立，但公開發送失敗：{type(exc).__name__}\n{invite.url}",
                ephemeral=True,
            )
            return

        await send_or_followup(interaction, content="✅ 邀請碼已公開發送到此頻道。", ephemeral=True)

    async def admin_stats_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)
        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)

        stats = get_stats(interaction.guild_id, days=7)
        total = get_total_usage(interaction.guild_id, days=7)
        top_feature = "暫時未有"
        if stats:
            top_key = stats[0][0]
            top_feature = f"{FEATURE_EMOJIS.get(top_key, '🔹')} {FEATURE_LABELS.get(top_key, top_key)}"

        now_hk = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")
        embed = discord.Embed(
            title="📊 Community Bot Insights｜本週",
            description=(
                f"**總使用次數：** `{total}`\n"
                f"**最活躍功能：** {top_feature}\n"
                f"**更新時間：** `{now_hk}`"
            ),
            color=MENU_COLOR,
        )
        embed.add_field(name="功能使用分佈", value=format_stats_block(stats), inline=False)
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")
        await send_or_followup(interaction, embed=embed, view=AdminToolView(self), ephemeral=True)

    async def admin_reload_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)
        record_usage_sync("admin_reload", interaction.user.id, interaction.guild_id)

        reload_cog = interaction.client.get_cog("Reload")
        if reload_cog is None or not hasattr(reload_cog, "_reload_one"):
            await send_or_followup(
                interaction,
                content="❌ Reload cog 未載入，請先用 `/reload reload` 或重啟 Bot。",
                ephemeral=True,
            )
            return

        try:
            from cogs.reload import _list_cogs_package  # type: ignore

            ok_list: list[str] = []
            fail_list: list[str] = []
            for name in _list_cogs_package():
                ext = f"cogs.{name}"
                try:
                    result = reload_cog._reload_one(ext)  # type: ignore[attr-defined]
                    if inspect.isawaitable(result):
                        ok, fail = await result
                    else:
                        ok, fail = result
                except Exception as exc:
                    ok = False
                    fail = f"`{type(exc).__name__}`: {exc}"
                if ok:
                    ok_list.append(name)
                else:
                    fail_list.append(f"{name} -> {fail}")

            msg: list[str] = []
            if ok_list:
                msg.append("✅ 已重載： " + ", ".join(ok_list))
            if fail_list:
                msg.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

            await send_or_followup(
                interaction,
                content="\n".join(msg) if msg else "⚠️ 無可重載的 cogs。",
                ephemeral=True,
            )
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ Reload button 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )

    async def admin_role_tools_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_role", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_role_tools_embed(interaction.user),
            view=RoleToolsView(self),
            ephemeral=True,
        )

    async def admin_ping_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)
        record_usage_sync("admin_ping", interaction.user.id, interaction.guild_id)
        latency_ms = round(interaction.client.latency * 1000)
        await send_or_followup(interaction, content=f"🏓 Pong! `{latency_ms} ms`", ephemeral=True)

    async def admin_vc_teardown_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_vc_teardown", interaction.user.id, interaction.guild_id)
        tempvc_cog = interaction.client.get_cog("TempVC")
        if tempvc_cog and hasattr(tempvc_cog, "teardown_temp_vc_from_menu"):
            try:
                result = tempvc_cog.teardown_temp_vc_from_menu(interaction)  # type: ignore[attr-defined]
                if inspect.isawaitable(result):
                    await result
                return
            except discord.InteractionResponded:
                return
            except Exception as exc:
                await send_or_followup(
                    interaction,
                    content=f"❌ VC Teardown 執行失敗：`{type(exc).__name__}`：{exc}",
                    ephemeral=True,
                )
                return

        await send_or_followup(
            interaction,
            content="🧹 **VC Teardown 指令入口**\n\n請使用 slash command：`/vc_teardown`。",
            ephemeral=True,
        )

    async def send_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not claim_mention_message(message.id):
            return

        if not can_use_admin(message.author):
            retry_after = get_retry_after(message.author.id)
            if retry_after > 0:
                return
            touch_cooldown(message.author.id)

        record_usage_sync("mention_menu", message.author.id, message.guild.id if message.guild else None)

        try:
            kwargs = safe_message_kwargs(
                embed=build_quick_bar_embed(message.author),
                view=QuickBarView(self),
                file=build_menu_file(),
            )
            kwargs["mention_author"] = False
            await message.reply(**kwargs)
        except discord.HTTPException:
            pass

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(QuickBarView(self))
        self.bot.add_view(HomeMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self.bot.add_view(AdminToolView(self))
        self.bot.add_view(RoleToolsView(self))
        self._views_registered = True

    @commands.Cog.listener("on_message")
    async def on_message_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return
        if self.bot.user is None:
            return

        direct_mention = f"<@{self.bot.user.id}>" in message.content or f"<@!{self.bot.user.id}>" in message.content
        if not direct_mention:
            return

        cleaned = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        if cleaned:
            return

        await self.send_mention_menu(message)

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 快捷吧枱")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=False,
            file=build_menu_file(),
        )

    @app_commands.command(name="community_hub", description="顯示 Con9sole Bartender 主頁")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    @app_commands.command(name="admin_stats", description="查看 Community Bot 使用數據")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(scope="查看範圍：today / week / all")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="今日", value="today"),
            app_commands.Choice(name="本週", value="week"),
            app_commands.Choice(name="全部", value="all"),
        ]
    )
    async def admin_stats(self, interaction: discord.Interaction, scope: app_commands.Choice[str]) -> None:
        if not can_use_admin(interaction.user):
            await send_or_followup(
                interaction,
                content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
                ephemeral=True,
            )
            return

        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)

        if scope.value == "today":
            days: int | None = 1
            title_scope = "今日"
        elif scope.value == "week":
            days = 7
            title_scope = "本週"
        else:
            days = None
            title_scope = "全部"

        stats = get_stats(interaction.guild_id, days)
        total = get_total_usage(interaction.guild_id, days)
        top_feature = "暫時未有"
        if stats:
            top_key = stats[0][0]
            top_feature = f"{FEATURE_EMOJIS.get(top_key, '🔹')} {FEATURE_LABELS.get(top_key, top_key)}"

        now_hk = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")
        embed = discord.Embed(
            title=f"📊 Community Bot Insights｜{title_scope}",
            description=(
                f"**總使用次數：** `{total}`\n"
                f"**最活躍功能：** {top_feature}\n"
                f"**更新時間：** `{now_hk}`"
            ),
            color=MENU_COLOR,
        )
        embed.add_field(name="功能使用分佈", value=format_stats_block(stats), inline=False)
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")
        await send_or_followup(interaction, embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
