from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

from core.sqlite_storage import connect_sqlite
from core.storage_paths import STATS_DB


def init_team_db() -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS team_cards_quarantine (message_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL)")
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
    result = []
    for message_id, payload in rows:
        try:
            decoded = json.loads(payload)
            if not isinstance(decoded, dict):
                raise ValueError("Team payload must be an object")
            result.append((message_id, decoded))
        except (ValueError, TypeError):
            quarantine_team(message_id, "Invalid JSON object")
    return result


def quarantine_team(message_id: int, reason: str) -> None:
    # Preserve the exact original payload before removing it from active records.
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("INSERT OR REPLACE INTO team_cards_quarantine SELECT message_id, payload, ? FROM team_cards WHERE message_id = ?", (reason, message_id))
        conn.execute("DELETE FROM team_cards WHERE message_id = ?", (message_id,))
    log.error("Quarantined invalid team record: message=%s reason=%s", message_id, reason)


def delete_team(message_id: int) -> None:
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("DELETE FROM team_cards WHERE message_id = ?", (message_id,))
