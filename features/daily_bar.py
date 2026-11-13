from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from core.sqlite_storage import connect_sqlite, enable_wal, initialize_once
from core.storage_paths import DATA_DIR, STATS_DB

log = logging.getLogger("con9sole-bartender.daily-bar")

DAILY_BAR_COLOR = 0xD6A85C
HK_TZ = ZoneInfo("Asia/Hong_Kong")

def _local_now(now=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(HK_TZ)

@dataclass(frozen=True)
class DailyBarTask:
    key: str
    emoji: str
    title: str
    description: str
    method: str
    note: str
    target: int = 1


DAILY_BAR_TASKS: tuple[DailyBarTask, ...] = (
    DailyBarTask(
        key="drink",
        emoji="🍹",
        title="叫一杯酒",
        description="今日搵酒保幫你調一杯特選飲品。",
        method="用 `/drink`，或者喺吧枱撳「飲一杯」。",
        note="完成後再打開今日任務，就會見到完成狀態。",
    ),
    DailyBarTask(
        key="drink_gift",
        emoji="🥂",
        title="請一位成員飲一杯酒",
        description="揀一位成員，請佢飲一杯酒保特選。",
        method="用 `/drink to:@成員`，或者喺吧枱撳「請人飲」揀對方。",
        note="賜酒 cooldown 會照常運作。",
    ),
    DailyBarTask(
        key="cheers",
        emoji="🎉",
        title="打一次氣",
        description="喺吧枱送出一句打氣說話。",
        method="喺「更多玩法 → 社群互動」撳「打氣」，或者用打氣功能。",
        note="每日一句，輕輕鬆鬆暖下場。",
    ),
    DailyBarTask(
        key="cheers_target",
        emoji="🙌",
        title="幫一位成員打氣",
        description="揀一位成員，送一句打氣畀對方。",
        method="喺「更多玩法 → 社群互動」撳「幫人打氣」，再揀一位成員。",
        note="見到邊個需要加油，就順手撐一撐佢。",
    ),
    DailyBarTask(
        key="drink_collection",
        emoji="🍾",
        title="打開酒單收藏",
        description="睇下你最近解鎖咗咩酒款。",
        method="用 `/drink_collection`，或者喺「更多玩法 → 我的紀錄」撳「我的收藏」。",
        note="收藏榜同酒保紀錄會隨住叫酒慢慢豐富。",
    ),
)


# Freeze the deployed task schedule through today's HK midnight.
COMMUNITY_TASKS_START = "2026-11-09"
COMMUNITY_TASKS = DAILY_BAR_TASKS[:4] + (
    DailyBarTask("text", "💬", "參與三次有效文字交流", "累積三次通過原有計分規則嘅文字參與。",
                 "去你已加入嘅文字頻道傾偈；每次須通過原有文字／互動共用 CD。",
                 "只計成功入帳次數；連續刷訊息、查看面板及匯入紀錄唔計。", 3),
    DailyBarTask("voice", "🎧", "同隊友完成一段有效語音", "完成一次有效語音計分。",
                 "與至少一位有效真人留喺可計分語音房，完成原有語音計分週期。",
                 "沿用現有語音 CD；AFK、耳聾、舞台聽眾等排除規則不變。"),
    DailyBarTask("team", "👥", "開一個組隊招募", "成功建立並保存一張組隊招募卡。",
                 "喺吧枱撳「約一局」，填好資料並成功發出約局。",
                 "只開啟表格、取消或發送失敗都唔計；每人每日獎勵仍然只得一次。"),
)


@initialize_once
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
    current = _local_now(now)
    return current.date().isoformat()


def _today_key(guild_id: int | None, *, now: datetime | None = None) -> str:
    return f"{guild_id or 0}:{_current_date(now=now)}"


def get_daily_bar_task(guild_id: int | None, *, now: datetime | None = None) -> DailyBarTask:
    key = _today_key(guild_id, now=now)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    tasks = COMMUNITY_TASKS if _current_date(now=now) >= COMMUNITY_TASKS_START else DAILY_BAR_TASKS
    index = int(digest[:8], 16) % len(tasks)
    return tasks[index]


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
    joined_since: float = 0,
    now: datetime | None = None,
) -> bool:
    current = _local_now(now)
    task = get_daily_bar_task(guild_id, now=current)
    if feature_key != task.key:
        return False

    init_daily_bar_db()
    day = current.date().isoformat()
    try:
        with connect_sqlite(STATS_DB) as conn:
            if joined_since:
                conn.execute("DELETE FROM daily_bar_completions WHERE guild_id IS ? AND user_id=? AND day=? AND julianday(completed_at)<julianday(?)",
                    (guild_id, user_id, day, datetime.fromtimestamp(joined_since, HK_TZ).isoformat()))
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
    progress: int | None = None,
    reward_state: str | None = None,
) -> discord.Embed:
    current = _local_now(now)
    task = get_daily_bar_task(guild_id, now=current)
    status = _completion_text(guild_id, user.id, now=current)
    if progress is not None:
        status = f"{min(progress, task.target)}／{task.target}" + (" · 已完成 ✅" if progress >= task.target else " · 未完成")

    embed = discord.Embed(
        title="📅 今日小任務",
        description=(
            f"歡迎回來，{user.mention}。\n\n"
            "今日有個細任務畀你。\n"
            "每日香港時間 00:00 刷新；全 server 同一任務。\n完成額外 +5 XP，每人每日一次，亦計入週榜。"
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
    embed.add_field(name="額外獎勵", value=reward_state or "完成後自動核對 +5 XP；每人每日一次。", inline=False)
    embed.add_field(
        name="備註",
        value=task.note,
        inline=False,
    )
    embed.set_footer(text=f"Con9sole Bartender｜Daily Bar｜{current.date().isoformat()} 香港時間")
    return embed
