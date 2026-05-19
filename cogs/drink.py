from __future__ import annotations

import asyncio
import os
import atexit
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import random
import sqlite3
import time
from typing import Deque, Dict, List

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from cogs.menu import build_full_menu_view, build_menu_file
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from core.drink_state import DrinkStateStore
from data.drink_data import (
    ALL_DRINKS,
    BARTENDER_ATTACHMENT_NAME,
    DRINK_COOLDOWN_SECONDS,
    DrinkEntry,
    ICON_MAP,
    RARITY_STYLE,
    RECENT_HISTORY_LIMIT,
    SEASONAL_DRINKS,
    TASTING_LINES,
)

# ── Persistent state ──────────────────────────────────────────────────────────────
_drink_state = DrinkStateStore.from_env()

# JSON keys可能係 str，跑程式用 int；重新 assign 番去 state 方便 serialize
DRINK_USER_COOLDOWNS: dict[int, float] = {
    int(user_id): float(ts)
    for user_id, ts in _drink_state.state.cooldowns.items()
}
_drink_state.state.cooldowns = DRINK_USER_COOLDOWNS

# stats DB 必須落 volume
DATA_DIR = Path(os.getenv("DRINK_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_DB = DATA_DIR / "community_stats.sqlite3"

GIFT_DRINK_TARGET_TIMEOUT_SECONDS = 60.0
COLLECTION_PAGE_LIMIT = 12

EVENT_SELF_DRINK = "self_drink"
EVENT_GIFT_DRINK = "gift_drink"

atexit.register(_drink_state.save)


@dataclass
class GiftDrinkPending:
    started_at: float
    cancel_event: asyncio.Event


PENDING_GIFT_DRINK_REQUESTS: dict[int, GiftDrinkPending] = {}


def init_drink_events_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drink_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                event_type TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                drink_eng TEXT NOT NULL,
                drink_zh TEXT NOT NULL,
                rarity TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drink_events_actor
            ON drink_events(guild_id, actor_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drink_events_target
            ON drink_events(guild_id, target_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drink_events_type
            ON drink_events(guild_id, event_type)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drink_events_created_at
            ON drink_events(guild_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drink_events_user_collection
            ON drink_events(guild_id, actor_id, target_id, drink_eng)
            """
        )


def record_drink_event(
    *,
    guild_id: int | None,
    event_type: str,
    actor_id: int,
    target_id: int,
    drink: DrinkEntry,
) -> None:
    try:
        init_drink_events_db()
        with sqlite3.connect(STATS_DB) as conn:
            conn.execute(
                """
                INSERT INTO drink_events (
                    guild_id,
                    event_type,
                    actor_id,
                    target_id,
                    drink_eng,
                    drink_zh,
                    rarity,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    event_type,
                    actor_id,
                    target_id,
                    drink.eng,
                    drink.zh,
                    drink.rarity,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception:
        pass


def _count_events(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> int:
    init_drink_events_db()
    with sqlite3.connect(STATS_DB) as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM drink_events
            WHERE guild_id IS ?
            AND {where_sql}
            """,
            (guild_id, *params),
        ).fetchone()
    return int(row[0]) if row else 0


def _count_distinct_drinks(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> int:
    init_drink_events_db()
    with sqlite3.connect(STATS_DB) as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT drink_eng)
            FROM drink_events
            WHERE guild_id IS ?
            AND {where_sql}
            """,
            (guild_id, *params),
        ).fetchone()
    return int(row[0]) if row else 0


def _recent_event(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> sqlite3.Row | None:
    init_drink_events_db()
    with sqlite3.connect(STATS_DB) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            f"""
            SELECT event_type, actor_id, target_id, drink_eng, drink_zh, rarity, created_at
            FROM drink_events
            WHERE guild_id IS ?
            AND {where_sql}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (guild_id, *params),
        ).fetchone()


def _top_member_id(guild_id: int | None, select_field: str, where_sql: str, params: tuple[object, ...]) -> tuple[int, int] | None:
    init_drink_events_db()
    with sqlite3.connect(STATS_DB) as conn:
        row = conn.execute(
            f"""
            SELECT {select_field} AS member_id, COUNT(*) AS total
            FROM drink_events
            WHERE guild_id IS ?
            AND {where_sql}
            GROUP BY {select_field}
            ORDER BY total DESC, member_id ASC
            LIMIT 1
            """,
            (guild_id, *params),
        ).fetchone()

    if not row:
        return None
    return int(row[0]), int(row[1])


def _drink_catalog() -> dict[str, DrinkEntry]:
    catalog: dict[str, DrinkEntry] = {}
    for drink in ALL_DRINKS:
        catalog.setdefault(drink.eng, drink)

    for pool in SEASONAL_DRINKS.values():
        for drink in pool:
            catalog.setdefault(drink.eng, drink)

    return catalog


def _catalog_by_rarity() -> dict[str, list[DrinkEntry]]:
    grouped: dict[str, list[DrinkEntry]] = {rarity: [] for rarity in RARITY_STYLE.keys()}
    for drink in _drink_catalog().values():
        grouped.setdefault(drink.rarity, []).append(drink)

    for drinks in grouped.values():
        drinks.sort(key=lambda item: (item.eng.casefold(), item.zh.casefold()))
    return grouped


def _fetch_collection_rows(
    guild_id: int | None,
    user_id: int,
    *,
    rarity: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    init_drink_events_db()

    rarity_sql = ""
    params: list[object] = [guild_id, user_id, user_id]
    if rarity is not None:
        rarity_sql = "AND rarity = ?"
        params.append(rarity)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(limit)

    with sqlite3.connect(STATS_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                drink_eng,
                drink_zh,
                rarity,
                MAX(created_at) AS latest_at,
                SUM(CASE WHEN event_type = ? AND actor_id = ? AND target_id = ? THEN 1 ELSE 0 END) AS self_count,
                SUM(CASE WHEN event_type = ? AND actor_id = ? THEN 1 ELSE 0 END) AS given_count,
                SUM(CASE WHEN event_type = ? AND target_id = ? THEN 1 ELSE 0 END) AS received_count
            FROM drink_events
            WHERE guild_id IS ?
            AND (actor_id = ? OR target_id = ?)
            {rarity_sql}
            GROUP BY drink_eng
            ORDER BY latest_at DESC, drink_eng ASC
            {limit_sql}
            """,
            (
                EVENT_SELF_DRINK,
                user_id,
                user_id,
                EVENT_GIFT_DRINK,
                user_id,
                EVENT_GIFT_DRINK,
                user_id,
                *params,
            ),
        ).fetchall()
    return list(rows)


def _fetch_collection_rarity_counts(guild_id: int | None, user_id: int) -> dict[str, int]:
    init_drink_events_db()
    with sqlite3.connect(STATS_DB) as conn:
        rows = conn.execute(
            """
            SELECT rarity, COUNT(*) AS total
            FROM (
                SELECT drink_eng, rarity
                FROM drink_events
                WHERE guild_id IS ?
                AND (actor_id = ? OR target_id = ?)
                GROUP BY drink_eng
            )
            GROUP BY rarity
            """,
            (guild_id, user_id, user_id),
        ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _progress_bar(current: int, total: int, *, size: int = 10) -> str:
    if total <= 0:
        return "░" * size
    filled = max(0, min(size, round((current / total) * size)))
    return "█" * filled + "░" * (size - filled)


def _rarity_label(rarity: str) -> str:
    meta = RARITY_STYLE.get(rarity, {})
    emoji = str(meta.get("emoji", "🍸"))
    label = str(meta.get("label", rarity))
    return f"{emoji} {label}"


def _rarity_color(rarity: str) -> int:
    meta = RARITY_STYLE.get(rarity, {})
    try:
        return int(meta.get("color", 0x2B2D31))
    except Exception:
        return 0x2B2D31


def _format_collection_row(row: sqlite3.Row) -> str:
    flags: list[str] = []
    if int(row["self_count"] or 0) > 0:
        flags.append("🍹")
    if int(row["received_count"] or 0) > 0:
        flags.append("🍷")
    if int(row["given_count"] or 0) > 0:
        flags.append("🥂")

    flag_text = "".join(flags) or "✅"
    return f"{flag_text} **{row['drink_eng']}（{row['drink_zh']}）**"


def format_member_ref(guild: discord.Guild | None, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    return member.mention if member else f"<@{user_id}>"


def format_recent_event(guild: discord.Guild | None, row: sqlite3.Row | None, *, user_id: int, kind: str) -> str:
    if row is None:
        return "暫時未有紀錄"

    drink_text = f"**{row['drink_eng']}（{row['drink_zh']}）**"
    rarity = row["rarity"]

    if kind == "self":
        return f"{drink_text}｜`{rarity}`"

    if kind == "given":
        target = format_member_ref(guild, int(row["target_id"]))
        return f"{drink_text} → {target}｜`{rarity}`"

    actor = format_member_ref(guild, int(row["actor_id"]))
    return f"{drink_text} ← {actor}｜`{rarity}`"


def build_tasting_note(drink: DrinkEntry) -> str:
    base = drink.desc.rstrip("。")
    return f"{base}。{random.choice(TASTING_LINES)}"


def get_drink_retry_after(user_id: int) -> float:
    last_used = DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_drink_cooldown(user_id: int) -> None:
    DRINK_USER_COOLDOWNS[user_id] = time.time()
    _drink_state.state.cooldowns = DRINK_USER_COOLDOWNS
    try:
        _drink_state.save()
    except Exception:
        pass


def cleanup_pending_gift_requests() -> None:
    now = time.time()
    expired_user_ids = [
        user_id
        for user_id, pending in PENDING_GIFT_DRINK_REQUESTS.items()
        if now - pending.started_at >= GIFT_DRINK_TARGET_TIMEOUT_SECONDS
    ]
    for user_id in expired_user_ids:
        pending = PENDING_GIFT_DRINK_REQUESTS.pop(user_id, None)
        if pending is not None and not pending.cancel_event.is_set():
            pending.cancel_event.set()


def current_seasonal_pool() -> List[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return pool
    return []


def build_result_payload(interaction: discord.Interaction, result_embed: discord.Embed) -> dict[str, object]:
    """Compact result embed + bartender thumbnail + Quick Bar buttons."""
    payload: dict[str, object] = {"embed": result_embed}

    menu_view = build_full_menu_view(interaction)
    if menu_view is not None:
        payload["view"] = menu_view

    menu_file = build_menu_file()
    if menu_file is not None:
        result_embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
        payload["file"] = menu_file

    return payload


def build_gift_prompt_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🥂 賜酒",
        description=(
            f"{user.mention}，請喺 **60 秒內** 喺呢個 channel tag 一位你想賜酒嘅成員。\n\n"
            "例：`@jeff`\n\n"
            "你亦可以撳下面嘅 **取消** 按鈕。"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜只會讀取你下一個訊息。")
    return embed


# ── Collection embeds / buttons（全保持原樣）────────────────────────────────────────
def build_drink_stats_embed(guild: discord.Guild | None, user: discord.Member | discord.User) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id

    self_count = _count_events(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )
    given_count = _count_events(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    received_count = _count_events(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    total_count = self_count + given_count + received_count

    top_given = _top_member_id(
        guild_id,
        "target_id",
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    top_received = _top_member_id(
        guild_id,
        "actor_id",
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )

    recent_self = _recent_event(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )
    recent_given = _recent_event(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    recent_received = _recent_event(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )

    top_given_text = "暫時未有紀錄"
    if top_given is not None:
        top_given_text = f"{format_member_ref(guild, top_given[0])}｜`{top_given[1]}` 次"

    top_received_text = "暫時未有紀錄"
    if top_received is not None:
        top_received_text = f"{format_member_ref(guild, top_received[0])}｜`{top_received[1]}` 次"

    embed = discord.Embed(
        title=f"🥂 {user.display_name} 的酒保紀錄",
        description=(
            f"🍹 **自己叫酒：** `{self_count}` 杯\n"
            f"🥂 **賜酒畀人：** `{given_count}` 杯\n"
            f"🍷 **收到賜酒：** `{received_count}` 杯\n"
            f"📊 **總酒保互動：** `{total_count}` 次"
        ),
        color=0x2B2D31,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="最常賜酒對象", value=top_given_text, inline=False)
    embed.add_field(name="最常收到來自", value=top_received_text, inline=False)
    embed.add_field(name="最近自己叫酒", value=format_recent_event(guild, recent_self, user_id=user_id, kind="self"), inline=False)
    embed.add_field(name="最近賜酒", value=format_recent_event(guild, recent_given, user_id=user_id, kind="given"), inline=False)
    embed.add_field(name="最近收到賜酒", value=format_recent_event(guild, recent_received, user_id=user_id, kind="received"), inline=False)
    embed.set_footer(text="Con9sole Bartender｜酒保紀錄 v1")
    return embed


# ...（中間 Collection / View / Button 部分保持你原來嘅內容）...

class Drink(commands.Cog):
    """ /drink：以 bartender 風格隨機為指定對象點一款酒。 """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

        # reload / restart 後，將 state 入番 deque
        try:
            for user_id, recent in _drink_state.state.recent_drinks.items():
                if not isinstance(user_id, int):
                    try:
                        user_id = int(user_id)
                    except Exception:
                        continue
                self.user_recent_draws[user_id] = deque(list(recent), maxlen=RECENT_HISTORY_LIMIT)
        except Exception:
            pass

        init_drink_events_db()

    # ...（其餘保持原樣）...

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        pool = self._build_pool_for_rarity(rarity)
        if not pool:
            pool = ALL_DRINKS + current_seasonal_pool()

        recent = set(self.user_recent_draws[user_id])

        # Soft repeat weighting:
        # - 最近 4/8 杯仍然有機會再中（視乎 drink_data 設定）
        # - 但非最近酒款有 4 倍機率
        weights = [
            1 if drink.eng in recent else 4
            for drink in pool
        ]

        chosen = random.choices(pool, weights=weights, k=1)[0]
        self.user_recent_draws[user_id].append(chosen.eng)

        # 保存最近歷史
        _drink_state.state.recent_drinks[user_id] = list(self.user_recent_draws[user_id])
        try:
            _drink_state.save()
        except Exception:
            pass

        return chosen

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None,
        drink: DrinkEntry,
    ) -> str:
        icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])
        giver = interaction.user.mention
        receiver = (to or interaction.user).mention
        drink_name = f"**{drink.eng}（{drink.zh}）**"

        if to and to.id != interaction.user.id:
            return f"{icon} {giver} 賜一杯 {drink_name} 給 {receiver}。"

        return f"{icon} Bartender Special：酒保為 {giver} 調製了一杯 {drink_name}。"

    # ...（其餘保持原樣）...

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
        feature: str | None = None,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_drink_cooldown(interaction)
            if not ok:
                return

        is_gift = bool(to and to.id != interaction.user.id)
        event_type = EVENT_GIFT_DRINK if is_gift else EVENT_SELF_DRINK
        usage_feature = feature or ("drink_gift" if is_gift else "drink")

        await self._record_usage(interaction, feature=usage_feature)

        rarity = self._pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        record_drink_event(
            guild_id=interaction.guild_id,
            event_type=event_type,
            actor_id=interaction.user.id,
            target_id=to.id if is_gift and to is not None else interaction.user.id,
            drink=drink,
        )

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 **限定供應：** {drink.limited_tag}" if drink.limited_tag else ""
        tasting_note = build_tasting_note(drink)
        style_icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])

        rarity_line = f"{rarity_meta['emoji']} {rarity_meta['label']}"
        style_line = f"{style_icon} {drink.typ}"
        rotation_line = f"最近 {RECENT_HISTORY_LIMIT} 杯低機率重複"

        result_embed = discord.Embed(
            title="🍹 Bartender’s Pick",
            description=(
                f"{header}\n\n"
                f"**品飲筆記**\n"
                f"➡️ {tasting_note}{limited_text}\n\n"
                f"**吧枱卡**\n"
                f"`{rarity_line}` ｜ `{style_line}` ｜ `{rotation_line}`"
            ),
            color=rarity_meta["color"],
            timestamp=discord.utils.utcnow(),
        )
        result_embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")

        send_kwargs = build_result_payload(interaction, result_embed)

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    # ...（其餘 command / setup 保持原樣）...


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
