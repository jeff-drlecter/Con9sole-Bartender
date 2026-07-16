from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import discord

from core.sqlite_storage import connect_sqlite, enable_wal
from core.storage_paths import DATA_DIR, STATS_DB

log = logging.getLogger("con9sole-bartender.daily-bar")

DAILY_BAR_COLOR = 0xD6A85C

@dataclass(frozen=True)
class DailyBarTask:
    key: str
    emoji: str
    title: str
    description: str
    method: str
    note: str


DAILY_BAR_TASKS: tuple[DailyBarTask, ...] = (
    DailyBarTask(
        key="drink",
        emoji="🍹",
        title="叫一杯酒",
        description="今日搵酒保幫你調一杯特選飲品。",
        method="用 `/drink`，或者喺 Quick Bar 撳 🍹。",
        note="完成後再打開今日任務，就會見到完成狀態。",
    ),
    DailyBarTask(
        key="drink_gift",
        emoji="🥂",
        title="請一位成員飲一杯酒",
        description="揀一位成員，請佢飲一杯酒保特選。",
        method="用 `/drink to:@成員`，或者喺 Quick Bar 撳 🥂 後 tag 對方。",
        note="賜酒 cooldown 會照常運作。",
    ),
    DailyBarTask(
        key="cheers",
        emoji="🎉",
        title="打一次氣",
        description="喺吧枱送出一句打氣說話。",
        method="喺 Quick Bar 撳 🎉，或者用打氣功能。",
        note="每日一句，輕輕鬆鬆暖下場。",
    ),
    DailyBarTask(
        key="cheers_target",
        emoji="🙌",
        title="幫一位成員打氣",
        description="tag 一位成員，送一句打氣畀對方。",
        method="喺 Quick Bar 撳 🙌，再跟提示 tag 成員。",
        note="見到邊個需要加油，就順手撐一撐佢。",
    ),
    DailyBarTask(
        key="drink_collection",
        emoji="🍾",
        title="打開酒單收藏",
        description="睇下你最近解鎖咗咩酒款。",
        method="用 `/drink_collection`，或者喺主目錄撳「酒單收藏」。",
        note="收藏榜同酒保紀錄會隨住叫酒慢慢豐富。",
    ),
)


def init_daily_bar_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(STATS_DB) as conn:
        enable_wal(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_bar_completions (
                guild_id INTEGER,
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                task_key TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_bar_completions_day
            ON daily_bar_completions(guild_id, day)
            """
        )


def _current_date(*, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.date().isoformat()


def _today_key(guild_id: int | None, *, now: datetime | None = None) -> str:
    return f"{guild_id or 0}:{_current_date(now=now)}"


def get_daily_bar_task(guild_id: int | None, *, now: datetime | None = None) -> DailyBarTask:
    key = _today_key(guild_id, now=now)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(DAILY_BAR_TASKS)
    return DAILY_BAR_TASKS[index]


def get_daily_bar_completion(
    guild_id: int | None,
    user_id: int,
    *,
    now: datetime | None = None,
) -> sqlite3.Row | None:
    init_daily_bar_db()
    day = _current_date(now=now)
    with connect_sqlite(STATS_DB) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT task_key, completed_at
            FROM daily_bar_completions
            WHERE guild_id IS ?
            AND user_id = ?
            AND day = ?
            """,
            (guild_id, user_id, day),
        ).fetchone()


def complete_daily_bar_task(
    *,
    guild_id: int | None,
    user_id: int,
    feature_key: str,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    task = get_daily_bar_task(guild_id, now=current)
    if feature_key != task.key:
        return False

    init_daily_bar_db()
    day = current.date().isoformat()
    try:
        with connect_sqlite(STATS_DB) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO daily_bar_completions (
                    guild_id,
                    user_id,
                    day,
                    task_key,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, day, task.key, current.isoformat()),
            )
        return cursor.rowcount > 0
    except Exception:
        log.exception(
            "Failed to complete daily bar task: guild=%s user=%s feature=%s",
            guild_id,
            user_id,
            feature_key,
        )
        return False


def _completion_text(guild_id: int | None, user_id: int, *, now: datetime | None = None) -> str:
    row = get_daily_bar_completion(guild_id, user_id, now=now)
    if row is None:
        return "未完成"
    return "已完成 ✅"


def build_daily_bar_embed(
    guild_id: int | None,
    *,
    user: discord.abc.User,
    now: datetime | None = None,
) -> discord.Embed:
    current = now or datetime.now(timezone.utc)
    task = get_daily_bar_task(guild_id, now=current)
    status = _completion_text(guild_id, user.id, now=current)

    embed = discord.Embed(
        title="📅 今日吧枱任務",
        description=(
            f"歡迎回來，{user.mention}。\n\n"
            "今日有個細任務畀你。\n"
            "任務每日刷新，同一日全 server 會見到同一個任務。"
        ),
        color=DAILY_BAR_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name=f"{task.emoji} 今日任務｜{task.title}",
        value=task.description,
        inline=False,
    )
    embed.add_field(
        name="完成方法",
        value=task.method,
        inline=False,
    )
    embed.add_field(
        name="完成狀態",
        value=status,
        inline=False,
    )
    embed.add_field(
        name="備註",
        value=task.note,
        inline=False,
    )
    embed.set_footer(text=f"Con9sole Bartender｜Daily Bar｜{current.date().isoformat()} UTC")
    return embed
