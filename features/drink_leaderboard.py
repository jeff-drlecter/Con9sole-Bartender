from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

import discord

from features.drink_storage import (
    EVENT_GIFT_DRINK,
    EVENT_SELF_DRINK,
    STATS_DB,
    init_drink_events_db,
)
from core.sqlite_storage import connect_sqlite

LeaderboardKind = Literal["self", "given", "received", "collection"]

LEADERBOARD_LIMIT = 10
LEADERBOARD_COLOR = 0xD6A85C


@dataclass(frozen=True)
class LeaderboardEntry:
    member_id: int
    total: int


LEADERBOARD_META: dict[LeaderboardKind, dict[str, str]] = {
    "self": {
        "emoji": "🍹",
        "title": "叫酒榜",
        "unit": "杯",
        "empty": "暫時未有人叫酒。",
        "hint": "計算自己向酒保叫酒嘅次數。",
    },
    "given": {
        "emoji": "🥂",
        "title": "賜酒榜",
        "unit": "杯",
        "empty": "暫時未有人賜酒。",
        "hint": "計算賜酒畀其他成員嘅次數。",
    },
    "received": {
        "emoji": "🎁",
        "title": "收酒榜",
        "unit": "杯",
        "empty": "暫時未有人收到賜酒。",
        "hint": "計算收到其他成員賜酒嘅次數。",
    },
    "collection": {
        "emoji": "🍾",
        "title": "收藏榜",
        "unit": "款",
        "empty": "暫時未有人解鎖酒款。",
        "hint": "計算自己飲到或收到賜酒解鎖嘅不同酒款。",
    },
}


def _fetch_rows(sql: str, params: tuple[object, ...]) -> list[LeaderboardEntry]:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [LeaderboardEntry(member_id=int(row[0]), total=int(row[1])) for row in rows]


def fetch_top_self_drinkers(guild_id: int | None, *, limit: int = LEADERBOARD_LIMIT) -> list[LeaderboardEntry]:
    return _fetch_rows(
        """
        SELECT actor_id AS member_id, COUNT(*) AS total
        FROM drink_events
        WHERE guild_id IS ?
        AND event_type = ?
        AND actor_id = target_id
        GROUP BY actor_id
        ORDER BY total DESC, member_id ASC
        LIMIT ?
        """,
        (guild_id, EVENT_SELF_DRINK, limit),
    )


def fetch_top_gifters(guild_id: int | None, *, limit: int = LEADERBOARD_LIMIT) -> list[LeaderboardEntry]:
    return _fetch_rows(
        """
        SELECT actor_id AS member_id, COUNT(*) AS total
        FROM drink_events
        WHERE guild_id IS ?
        AND event_type = ?
        GROUP BY actor_id
        ORDER BY total DESC, member_id ASC
        LIMIT ?
        """,
        (guild_id, EVENT_GIFT_DRINK, limit),
    )


def fetch_top_receivers(guild_id: int | None, *, limit: int = LEADERBOARD_LIMIT) -> list[LeaderboardEntry]:
    return _fetch_rows(
        """
        SELECT target_id AS member_id, COUNT(*) AS total
        FROM drink_events
        WHERE guild_id IS ?
        AND event_type = ?
        GROUP BY target_id
        ORDER BY total DESC, member_id ASC
        LIMIT ?
        """,
        (guild_id, EVENT_GIFT_DRINK, limit),
    )


def fetch_top_collectors(guild_id: int | None, *, limit: int = LEADERBOARD_LIMIT) -> list[LeaderboardEntry]:
    return _fetch_rows(
        """
        SELECT member_id, COUNT(*) AS total
        FROM (
            SELECT actor_id AS member_id, drink_eng
            FROM drink_events
            WHERE guild_id IS ?
            AND event_type = ?
            AND actor_id = target_id

            UNION

            SELECT target_id AS member_id, drink_eng
            FROM drink_events
            WHERE guild_id IS ?
            AND event_type = ?
        ) unlocked
        GROUP BY member_id
        ORDER BY total DESC, member_id ASC
        LIMIT ?
        """,
        (guild_id, EVENT_SELF_DRINK, guild_id, EVENT_GIFT_DRINK, limit),
    )


def fetch_leaderboard(kind: LeaderboardKind, guild_id: int | None, *, limit: int = LEADERBOARD_LIMIT) -> list[LeaderboardEntry]:
    if kind == "self":
        return fetch_top_self_drinkers(guild_id, limit=limit)
    if kind == "given":
        return fetch_top_gifters(guild_id, limit=limit)
    if kind == "received":
        return fetch_top_receivers(guild_id, limit=limit)
    return fetch_top_collectors(guild_id, limit=limit)


def _format_member(guild: discord.Guild | None, member_id: int) -> str:
    member = guild.get_member(member_id) if guild else None
    return member.mention if member else f"<@{member_id}>"


def _format_rows(guild: discord.Guild | None, entries: list[LeaderboardEntry], *, unit: str) -> str:
    if not entries:
        return ""

    lines: list[str] = []
    medals = ["🥇", "🥈", "🥉"]
    for index, entry in enumerate(entries, start=1):
        rank = medals[index - 1] if index <= len(medals) else f"`#{index}`"
        member_text = _format_member(guild, entry.member_id)
        lines.append(f"{rank} {member_text} — **{entry.total}** {unit}")
    return "\n".join(lines)


def build_drink_leaderboard_embed(
    guild: discord.Guild | None,
    *,
    kind: LeaderboardKind = "self",
    requested_by: discord.abc.User | None = None,
) -> discord.Embed:
    meta = LEADERBOARD_META[kind]
    entries = fetch_leaderboard(kind, guild.id if guild else None)
    body = _format_rows(guild, entries, unit=meta["unit"]) or meta["empty"]

    embed = discord.Embed(
        title="🏆 酒保排行榜",
        description=(
            f"{meta['emoji']} **{meta['title']}**\n"
            f"{meta['hint']}\n\n"
            f"{body}"
        ),
        color=LEADERBOARD_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    if requested_by is not None:
        embed.set_footer(text=f"Con9sole Bartender｜由 {requested_by.display_name} 打開排行榜")
    else:
        embed.set_footer(text="Con9sole Bartender｜排行榜以全部時間計算")
    return embed


class DrinkLeaderboardView(discord.ui.View):
    def __init__(self, *, guild: discord.Guild | None, requested_by: discord.abc.User | None = None) -> None:
        super().__init__(timeout=180)
        self.guild = guild
        self.requested_by = requested_by

    async def _show(self, interaction: discord.Interaction, kind: LeaderboardKind) -> None:
        embed = build_drink_leaderboard_embed(
            self.guild,
            kind=kind,
            requested_by=self.requested_by or interaction.user,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="叫酒", emoji="🍹", style=discord.ButtonStyle.success)
    async def self_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "self")

    @discord.ui.button(label="賜酒", emoji="🥂", style=discord.ButtonStyle.primary)
    async def given_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "given")

    @discord.ui.button(label="收酒", emoji="🎁", style=discord.ButtonStyle.primary)
    async def received_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "received")

    @discord.ui.button(label="收藏", emoji="🍾", style=discord.ButtonStyle.secondary)
    async def collection_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, "collection")
