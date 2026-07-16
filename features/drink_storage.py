from __future__ import annotations

import os
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import discord

from core.sqlite_storage import connect_sqlite, enable_wal
from data.drink_data import DrinkEntry

log = logging.getLogger("con9sole-bartender.drink.storage")

EVENT_SELF_DRINK = "self_drink"
EVENT_GIFT_DRINK = "gift_drink"

# Persistent storage:
# Fly.io volume should mount at /data. For local/dev, safely fall back to repo data/.
DATA_DIR = Path(os.getenv("DRINK_DATA_DIR", "/data"))
if not DATA_DIR.exists():
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATS_DB = DATA_DIR / "community_stats.sqlite3"


def init_drink_events_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(STATS_DB) as conn:
        enable_wal(conn)
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
        with connect_sqlite(STATS_DB) as conn:
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
        # Stats failure should never block drink flow.
        log.exception(
            "Failed to record drink event: guild=%s event=%s actor=%s target=%s",
            guild_id,
            event_type,
            actor_id,
            target_id,
        )


def count_events(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> int:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
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


def count_distinct_drinks(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> int:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
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


def recent_event(guild_id: int | None, where_sql: str, params: tuple[object, ...]) -> sqlite3.Row | None:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
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


def top_member_id(
    guild_id: int | None,
    select_field: str,
    where_sql: str,
    params: tuple[object, ...],
) -> tuple[int, int] | None:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
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


def count_self_drinks(guild_id: int | None, user_id: int) -> int:
    return count_events(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )


def count_given_drinks(guild_id: int | None, user_id: int) -> int:
    return count_events(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def count_received_drinks(guild_id: int | None, user_id: int) -> int:
    return count_events(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def count_self_unique_drinks(guild_id: int | None, user_id: int) -> int:
    return count_distinct_drinks(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )


def count_given_unique_drinks(guild_id: int | None, user_id: int) -> int:
    return count_distinct_drinks(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def count_received_unique_drinks(guild_id: int | None, user_id: int) -> int:
    return count_distinct_drinks(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def top_given_target(guild_id: int | None, user_id: int) -> tuple[int, int] | None:
    return top_member_id(
        guild_id,
        "target_id",
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def top_received_actor(guild_id: int | None, user_id: int) -> tuple[int, int] | None:
    return top_member_id(
        guild_id,
        "actor_id",
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def recent_self_drink(guild_id: int | None, user_id: int) -> sqlite3.Row | None:
    return recent_event(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )


def recent_given_drink(guild_id: int | None, user_id: int) -> sqlite3.Row | None:
    return recent_event(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def recent_received_drink(guild_id: int | None, user_id: int) -> sqlite3.Row | None:
    return recent_event(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )


def fetch_collection_rows(
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

    with connect_sqlite(STATS_DB) as conn:
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


def fetch_collection_rarity_counts(guild_id: int | None, user_id: int) -> dict[str, int]:
    init_drink_events_db()
    with connect_sqlite(STATS_DB) as conn:
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
