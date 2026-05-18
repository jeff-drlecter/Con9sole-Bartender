from __future__ import annotations

import asyncio
from collections import defaultdict, deque
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

DRINK_USER_COOLDOWNS: dict[int, float] = {}
PENDING_GIFT_DRINK_REQUESTS: dict[int, float] = {}
GIFT_DRINK_TARGET_TIMEOUT_SECONDS = 60.0

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATS_DB = DATA_DIR / "community_stats.sqlite3"

EVENT_SELF_DRINK = "self_drink"
EVENT_GIFT_DRINK = "gift_drink"


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


def cleanup_pending_gift_requests() -> None:
    now = time.time()
    expired = [
        user_id
        for user_id, started_at in PENDING_GIFT_DRINK_REQUESTS.items()
        if now - started_at >= GIFT_DRINK_TARGET_TIMEOUT_SECONDS
    ]
    for user_id in expired:
        PENDING_GIFT_DRINK_REQUESTS.pop(user_id, None)


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
            "例：`@jacky`\n\n"
            "如果想取消，請輸入：`cancel`"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜只會讀取你下一個訊息。")
    return embed


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


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))
        init_drink_events_db()

    async def _record_usage(self, interaction: discord.Interaction, feature: str = "drink") -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(feature, interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _enforce_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        if is_admin_or_helper(interaction.user):
            return True

        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False

        touch_drink_cooldown(interaction.user.id)
        return True

    def _pick_rarity(self) -> str:
        labels = list(RARITY_STYLE.keys())
        weights = [RARITY_STYLE[label]["weight"] for label in labels]
        return random.choices(labels, weights=weights, k=1)[0]

    def _build_pool_for_rarity(self, rarity: str) -> List[DrinkEntry]:
        pool = [drink for drink in ALL_DRINKS if drink.rarity == rarity]
        seasonal = [drink for drink in current_seasonal_pool() if drink.rarity == rarity]
        return pool + seasonal

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        pool = self._build_pool_for_rarity(rarity)
        if not pool:
            pool = ALL_DRINKS + current_seasonal_pool()

        recent = set(self.user_recent_draws[user_id])
        candidates = [drink for drink in pool if drink.eng not in recent]
        chosen = random.choice(candidates or pool)
        self.user_recent_draws[user_id].append(chosen.eng)
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

    async def _wait_for_gift_target(self, interaction: discord.Interaction) -> discord.Member | None:
        if interaction.channel is None:
            await send_or_followup(interaction, content="❌ 搵唔到目前 channel，請重新試一次。", ephemeral=True)
            return None

        cleanup_pending_gift_requests()
        if interaction.user.id in PENDING_GIFT_DRINK_REQUESTS:
            await send_or_followup(
                interaction,
                content="⏳ 你已經有一個等待 tag 對象嘅賜酒操作。請先完成，或者輸入 `cancel` 取消。",
                ephemeral=True,
            )
            return None

        ok = await self._enforce_drink_cooldown(interaction)
        if not ok:
            return None

        PENDING_GIFT_DRINK_REQUESTS[interaction.user.id] = time.time()

        await send_or_followup(
            interaction,
            embed=build_gift_prompt_embed(interaction.user),
            ephemeral=True,
        )

        def check(message: discord.Message) -> bool:
            if message.author.bot:
                return False
            if message.author.id != interaction.user.id:
                return False
            if message.channel.id != interaction.channel_id:
                return False
            return True

        try:
            message = await self.bot.wait_for(
                "message",
                check=check,
                timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ 已逾時，賜酒已取消。", ephemeral=True)
            return None
        finally:
            PENDING_GIFT_DRINK_REQUESTS.pop(interaction.user.id, None)

        if message.content.strip().casefold() in {"cancel", "取消", "stop"}:
            await interaction.followup.send("已取消賜酒。", ephemeral=True)
            return None

        if len(message.mentions) != 1:
            await interaction.followup.send("❌ 請只 tag 一位成員。", ephemeral=True)
            return None

        target = message.mentions[0]
        if not isinstance(target, discord.Member):
            if interaction.guild is not None:
                target = interaction.guild.get_member(target.id)

        if target is None or not isinstance(target, discord.Member):
            await interaction.followup.send("❌ 搵唔到呢位成員，請重新試一次。", ephemeral=True)
            return None

        if target.id == interaction.user.id:
            await interaction.followup.send("🍹 想自己飲可以直接用調酒，賜酒請 tag 另一位成員。", ephemeral=True)
            return None

        if target.bot:
            await interaction.followup.send("🤖 酒保暫時唔向 bot 賜酒，請 tag 一位真人成員。", ephemeral=True)
            return None

        return target

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
        rotation_line = f"已避開最近 {RECENT_HISTORY_LIMIT} 杯"

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

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_drink(interaction, enforce_cooldown=True)

    async def gift_drink_entry(self, interaction: discord.Interaction) -> None:
        target = await self._wait_for_gift_target(interaction)
        if target is None:
            return

        await self.do_drink(
            interaction,
            to=target,
            enforce_cooldown=False,
            feature="drink_gift",
        )

    async def stats_entry(self, interaction: discord.Interaction) -> None:
        embed = build_drink_stats_embed(interaction.guild, interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="由酒保為你或指定成員調一杯特選飲品")
    @app_commands.describe(to="收酒嘅人；留空即係自己叫酒")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None):
        await self.do_drink(interaction, to, enforce_cooldown=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_stats", description="查看自己或指定成員的酒保紀錄")
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_stats(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        embed = build_drink_stats_embed(interaction.guild, target)
        await send_or_followup(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
