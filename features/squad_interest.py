"""Persistent, opt-in next-session notifications scoped to one game and mode."""
from __future__ import annotations

import hashlib
import json
import time

from core.sqlite_storage import connect_sqlite, initialize_once
from core.storage_paths import STATS_DB

NOTIFY_COOLDOWN = 30 * 60


def topic(guild_id, game, mode=''):
    game, mode = str(game).strip(), str(mode).strip()
    if not game:
        return None
    identity = json.dumps([guild_id, ' '.join(game.casefold().split()),
                           ' '.join(mode.casefold().split())], ensure_ascii=False)
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:32],
                guild_id=guild_id, label=game + (f' · {mode}' if mode else ''))


@initialize_once
def initialize():
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_topics (
            scope TEXT PRIMARY KEY, guild_id INTEGER NOT NULL, label TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_members (
            scope TEXT NOT NULL REFERENCES squad_interest_topics(scope),
            user_id INTEGER NOT NULL, last_notified REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(scope, user_id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_attempts (
            session_id TEXT NOT NULL, scope TEXT NOT NULL,
            attempted_at REAL NOT NULL, PRIMARY KEY(session_id, scope))''')


def remember(value):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT OR IGNORE INTO squad_interest_topics VALUES (?,?,?)',
                     (value['id'], value['guild_id'], value['label']))


def topics():
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return [dict(id=r[0], guild_id=r[1], label=r[2]) for r in
                conn.execute('SELECT scope,guild_id,label FROM squad_interest_topics')]


def toggle(scope, guild_id, user_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM squad_interest_topics WHERE scope=? AND guild_id=?',
                            (scope, guild_id)).fetchone():
            raise ValueError('Unknown interest topic')
        deleted = conn.execute('DELETE FROM squad_interest_members WHERE scope=? AND user_id=?',
                               (scope, user_id)).rowcount
        if not deleted:
            conn.execute('INSERT INTO squad_interest_members(scope,user_id) VALUES (?,?)', (scope,user_id))
        return not bool(deleted)


def members(scope):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return [r[0] for r in conn.execute('SELECT user_id FROM squad_interest_members WHERE scope=? ORDER BY user_id', (scope,))]


def reserve(session_id, scope, eligible, *, now=None):
    """Reserve once before posting; uncertain sends must never auto-replay pings."""
    initialize()
    current = time.time() if now is None else now
    selected = []
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('INSERT OR IGNORE INTO squad_interest_attempts VALUES (?,?,?)',
                            (session_id,scope,current)).rowcount:
            return []
        for user_id in eligible:
            # Recheck subscription atomically: a just-cancelled user is excluded.
            if conn.execute('''UPDATE squad_interest_members SET last_notified=?
                WHERE scope=? AND user_id=? AND (last_notified=0 OR last_notified<=?)''',
                (current,scope,user_id,current-NOTIFY_COOLDOWN)).rowcount:
                selected.append(user_id)
    return selected
