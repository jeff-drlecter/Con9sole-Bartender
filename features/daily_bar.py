from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import discord

DAILY_BAR_COLOR = 0xD6A85C


@dataclass(frozen=True)
class DailyBarTask:
    emoji: str
    title: str
    description: str
    method: str
    note: str


DAILY_BAR_TASKS: tuple[DailyBarTask, ...] = (
    DailyBarTask(
        emoji="🍹",
        title="叫一杯酒",
        description="今日搵酒保幫你調一杯特選飲品。",
        method="用 `/drink`，或者喺 Quick Bar 撳 🍹。",
        note="任務 V1 暫時只顯示任務，唔會自動追蹤完成。",
    ),
    DailyBarTask(
        emoji="🥂",
        title="請一位成員飲一杯酒",
        description="揀一位成員，請佢飲一杯酒保特選。",
        method="用 `/drink to:@成員`，或者喺 Quick Bar 撳 🥂 後 tag 對方。",
        note="賜酒 cooldown 會照常運作。",
    ),
    DailyBarTask(
        emoji="🎉",
        title="打一口氣",
        description="喺吧枱送出一句打氣說話。",
        method="喺 Quick Bar 撳 🎉，或者用打氣功能。",
        note="適合每日第一個暖場互動。",
    ),
    DailyBarTask(
        emoji="🙌",
        title="幫一位成員打氣",
        description="tag 一位成員，送一句打氣畀對方。",
        method="喺 Quick Bar 撳 🙌，再跟提示 tag 成員。",
        note="今日嘅吧枱氣氛，由你開局。",
    ),
    DailyBarTask(
        emoji="🍾",
        title="翻開酒單收藏",
        description="睇下你最近解鎖咗咩酒款。",
        method="用 `/drink_collection`，或者喺主目錄撳「酒單收藏」。",
        note="收藏榜同酒保紀錄會隨住叫酒慢慢豐富。",
    ),
)


def _today_key(guild_id: int | None, *, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    day = current.date().isoformat()
    return f"{guild_id or 0}:{day}"


def get_daily_bar_task(guild_id: int | None, *, now: datetime | None = None) -> DailyBarTask:
    key = _today_key(guild_id, now=now)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(DAILY_BAR_TASKS)
    return DAILY_BAR_TASKS[index]


def build_daily_bar_embed(
    guild_id: int | None,
    *,
    user: discord.abc.User,
    now: datetime | None = None,
) -> discord.Embed:
    current = now or datetime.now(timezone.utc)
    task = get_daily_bar_task(guild_id, now=current)

    embed = discord.Embed(
        title="📅 今日吧枱任務",
        description=(
            f"歡迎回來，{user.mention}。\n\n"
            "今日吧枱已經開局。\n"
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
        name="備註",
        value=task.note,
        inline=False,
    )
    embed.set_footer(text=f"Con9sole Bartender｜Daily Bar｜{current.date().isoformat()} UTC")
    return embed
