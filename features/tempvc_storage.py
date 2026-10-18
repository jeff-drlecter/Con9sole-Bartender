from __future__ import annotations

import time

from core.sqlite_storage import connect_sqlite
from core.storage_paths import STATS_DB


def init_tempvc_db() -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS temp_voice_channels (
            channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
            creator_id INTEGER, created_at REAL NOT NULL
        )""")


def remember(channel_id: int, guild_id: int, creator_id: int | None) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute(
            """INSERT INTO temp_voice_channels VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET guild_id=excluded.guild_id,
            creator_id=COALESCE(excluded.creator_id, temp_voice_channels.creator_id)""",
            (channel_id, guild_id, creator_id, time.time()),
        )


def forget(channel_id: int) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute(
            "DELETE FROM temp_voice_channels WHERE channel_id = ?", (channel_id,)
        )


def tracked_ids(guild_id: int) -> list[int]:
    with connect_sqlite(STATS_DB) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT channel_id FROM temp_voice_channels WHERE guild_id = ?",
                (guild_id,),
            )
        ]


def owned_ids(guild_id: int, user_id: int) -> list[int]:
    with connect_sqlite(STATS_DB) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT channel_id FROM temp_voice_channels WHERE guild_id = ? AND creator_id = ? ORDER BY created_at DESC",
                (guild_id, user_id),
            )
        ]


def creator_id(channel_id: int) -> int | None:
    with connect_sqlite(STATS_DB) as conn:
        row = conn.execute(
            "SELECT creator_id FROM temp_voice_channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
    return row[0] if row else None
