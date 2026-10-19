from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass

from features.drink_catalog import drink_catalog


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    target: int
    catalog_names: frozenset[str] | None = None


def milestones() -> list[Milestone]:
    names = frozenset(drink_catalog())
    version = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:12]
    counts = [
        (1, "初嚐一杯"),
        (5, "吧枱熟客"),
        (10, "酒譜新星"),
        (25, "風味探索者"),
        (50, "酒譜收藏家"),
        (100, "百杯見聞"),
        (250, "資深收藏家"),
        (500, "吧枱鑑賞家"),
        (1000, "千款傳奇"),
    ]
    result = [Milestone(f"count:{n}", label, n) for n, label in counts]
    if names:
        result += [
            Milestone(
                f"catalog:{version}:{percent}",
                f"酒譜 {percent}%",
                math.ceil(len(names) * percent / 100),
                names,
            )
            for percent in (25, 50, 75, 100)
        ]
    return result


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_collection (
        guild_key TEXT NOT NULL, user_id INTEGER NOT NULL, drink_eng TEXT NOT NULL,
        drink_zh TEXT NOT NULL, rarity TEXT NOT NULL, first_at TEXT NOT NULL,
        PRIMARY KEY(guild_key, user_id, drink_eng))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_collection_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_milestones (
        guild_key TEXT NOT NULL, user_id INTEGER NOT NULL, milestone_id TEXT NOT NULL,
        label TEXT NOT NULL, target INTEGER NOT NULL, catalog_total INTEGER,
        unlocked_at TEXT NOT NULL,
        PRIMARY KEY(guild_key, user_id, milestone_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_collection_titles (
        guild_key TEXT NOT NULL, user_id INTEGER NOT NULL, milestone_id TEXT NOT NULL,
        PRIMARY KEY(guild_key, user_id))""")
    # The marker and backfill commit together. Existing outgoing gifts remain owned;
    # new gifts only unlock a drink for their recipient. No historical rows are deleted.
    inserted = conn.execute(
        "INSERT OR IGNORE INTO drink_collection_meta VALUES ('legacy_backfill', '1')"
    ).rowcount
    if inserted:
        conn.execute("""INSERT INTO drink_collection
            SELECT COALESCE(CAST(guild_id AS TEXT), 'dm'), user_id, drink_eng,
                   drink_zh, rarity, MIN(created_at)
            FROM (SELECT guild_id, actor_id AS user_id, drink_eng, drink_zh, rarity, created_at FROM drink_events
                  UNION ALL
                  SELECT guild_id, target_id AS user_id, drink_eng, drink_zh, rarity, created_at FROM drink_events)
            GROUP BY guild_id, user_id, drink_eng""")


def guild_key(guild_id: int | None) -> str:
    return str(guild_id) if guild_id is not None else "dm"


def reconcile(
    conn: sqlite3.Connection, guild_id: int | None, user_id: int
) -> list[str]:
    rows = conn.execute(
        "SELECT drink_eng, first_at FROM drink_collection WHERE guild_key=? AND user_id=? ORDER BY first_at, drink_eng",
        (guild_key(guild_id), user_id),
    ).fetchall()
    added = []
    for goal in milestones():
        eligible = [
            row
            for row in rows
            if goal.catalog_names is None or row[0] in goal.catalog_names
        ]
        if len(eligible) < goal.target:
            continue
        cursor = conn.execute(
            """INSERT OR IGNORE INTO drink_milestones
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                guild_key(guild_id),
                user_id,
                goal.key,
                goal.label,
                goal.target,
                len(goal.catalog_names) if goal.catalog_names is not None else None,
                eligible[goal.target - 1][1],
            ),
        )
        if cursor.rowcount:
            added.append(goal.label)
    return added


def collection_snapshot(guild_id: int | None, user_id: int) -> dict:
    from features import drink_storage as storage
    from features import theme_collections

    storage.init_drink_events_db()
    with storage.connect_sqlite(storage.STATS_DB) as conn:
        conn.execute("BEGIN IMMEDIATE")
        reconcile(
            conn, guild_id, user_id
        )  # Backfill quietly; never send historical announcements.
        theme_collections.reconcile(conn, guild_id, user_id)
        names = {
            row[0]
            for row in conn.execute(
                "SELECT drink_eng FROM drink_collection WHERE guild_key=? AND user_id=?",
                (guild_key(guild_id), user_id),
            )
        }
        conn.row_factory = sqlite3.Row
        awards = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM drink_milestones WHERE guild_key=? AND user_id=? ORDER BY unlocked_at, target, milestone_id",
                (guild_key(guild_id), user_id),
            )
        ]
        awards.extend(theme_collections.title_awards(conn, guild_id, user_id))
        selected = conn.execute(
            "SELECT milestone_id FROM drink_collection_titles WHERE guild_key=? AND user_id=?",
            (guild_key(guild_id), user_id),
        ).fetchone()
    return {
        "names": names,
        "awards": awards,
        "selected": selected[0] if selected else None,
    }


def select_title(guild_id: int | None, user_id: int, milestone_id: str) -> bool:
    from features import drink_storage as storage
    from features import theme_collections

    storage.init_drink_events_db()
    with storage.connect_sqlite(storage.STATS_DB) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if milestone_id == "none":
            conn.execute(
                "DELETE FROM drink_collection_titles WHERE guild_key=? AND user_id=?",
                (guild_key(guild_id), user_id),
            )
            return True
        owned = conn.execute(
            "SELECT 1 FROM drink_milestones WHERE guild_key=? AND user_id=? AND milestone_id=?",
            (guild_key(guild_id), user_id, milestone_id),
        ).fetchone()
        owned_theme = any(
            a["milestone_id"] == milestone_id
            for a in theme_collections.title_awards(conn, guild_id, user_id)
        )
        if not owned and not owned_theme:
            return False
        conn.execute(
            "INSERT INTO drink_collection_titles VALUES (?, ?, ?) ON CONFLICT(guild_key,user_id) DO UPDATE SET milestone_id=excluded.milestone_id",
            (guild_key(guild_id), user_id, milestone_id),
        )
        return True
