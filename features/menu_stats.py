from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

import config

MENU_COLOR = 0x2B2D31
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATS_DB = DATA_DIR / "community_stats.sqlite3"
HK_TZ = timezone(timedelta(hours=8))
COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")

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


def build_admin_stats_embed(*, guild_id: int | None, days: int | None, title_scope: str) -> discord.Embed:
    stats = get_stats(guild_id, days)
    total = get_total_usage(guild_id, days)
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
    return embed
