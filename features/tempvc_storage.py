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
        conn.execute("""CREATE TABLE IF NOT EXISTS temp_voice_community_names (
            channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL, original_name TEXT NOT NULL,
            community_name TEXT, source TEXT NOT NULL
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
        conn.execute("DELETE FROM temp_voice_community_names WHERE channel_id = ?", (channel_id,))


def community_names(guild_id: int) -> dict[int, dict]:
    with connect_sqlite(STATS_DB) as conn:
        rows = conn.execute("""SELECT n.channel_id, n.owner_id, n.original_name, n.community_name, n.source
            FROM temp_voice_community_names n JOIN temp_voice_channels v USING(channel_id)
            WHERE n.guild_id = ? AND v.guild_id = n.guild_id AND v.creator_id = n.owner_id""",
            (guild_id,)).fetchall()
    return {row[0]: dict(owner_id=row[1], original_name=row[2], community_name=row[3], source=row[4]) for row in rows}


def set_community_name(channel_id: int, guild_id: int, owner_id: int,
                       original_name: str, name: str | None, source: str) -> dict | None:
    """Persist an owned room's latest intent, preserving its pre-community name."""
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        owner = conn.execute('SELECT creator_id FROM temp_voice_channels WHERE channel_id = ? AND guild_id = ?',
                             (channel_id, guild_id)).fetchone()
        if not owner or owner[0] != owner_id:
            return None
        previous = conn.execute('SELECT owner_id, original_name, source FROM temp_voice_community_names WHERE channel_id = ?',
                                (channel_id,)).fetchone()
        if name is None and previous and previous[2] != source:
            return None
        if previous and previous[0] == owner_id:
            original_name = previous[1]
        elif name is None:
            return dict(owner_id=owner_id, original_name=original_name, community_name=None, source=source)
        conn.execute('INSERT OR REPLACE INTO temp_voice_community_names VALUES (?, ?, ?, ?, ?, ?)',
                     (channel_id, guild_id, owner_id, original_name, name, source))
    return dict(owner_id=owner_id, original_name=original_name, community_name=name, source=source)


def finish_community_clear(channel_id: int, owner_id: int, source: str) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('DELETE FROM temp_voice_community_names WHERE channel_id = ? AND owner_id = ? AND source = ? AND community_name IS NULL',
                     (channel_id, owner_id, source))


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
