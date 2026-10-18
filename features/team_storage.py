from __future__ import annotations

import json

from core.sqlite_storage import connect_sqlite
from core.storage_paths import STATS_DB


def init_team_db() -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS team_cards (message_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )


def save_team(message_id: int, payload: dict) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO team_cards VALUES (?, ?)",
            (message_id, json.dumps(payload, ensure_ascii=False)),
        )


def load_teams() -> list[tuple[int, dict]]:
    with connect_sqlite(STATS_DB) as conn:
        rows = conn.execute("SELECT message_id, payload FROM team_cards").fetchall()
    return [(message_id, json.loads(payload)) for message_id, payload in rows]


def delete_team(message_id: int) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("DELETE FROM team_cards WHERE message_id = ?", (message_id,))
