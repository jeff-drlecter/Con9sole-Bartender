"""Durable, game-scoped one-shot and recurring session notifications."""
from __future__ import annotations

import hashlib
import json
import time

from core.sqlite_storage import connect_sqlite, initialize_once
from core.storage_paths import STATS_DB


def topic(guild_id, game, mode=''):
    game = str(game).strip()
    if not game:
        return None
    identity = json.dumps([guild_id, ' '.join(game.casefold().split())], ensure_ascii=False)
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:32],
                guild_id=guild_id, label=game)


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
        columns = {r[1] for r in conn.execute('PRAGMA table_info(squad_interest_members)')}
        for name, definition in [('kind', "TEXT NOT NULL DEFAULT 'always'"),
                                 ('excluded_session', "TEXT NOT NULL DEFAULT ''")]:
            if name not in columns:
                conn.execute(f'ALTER TABLE squad_interest_members ADD COLUMN {name} {definition}')
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_aliases (
            scope TEXT PRIMARY KEY, game_scope TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_cards (
            message_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL,
            scope TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '')''')
        # Previous subscriptions were recurring and mode-scoped. Preserve that
        # consent while merging modes into games; retain aliases for old buttons.
        for old, guild_id, label in list(conn.execute('SELECT scope,guild_id,label FROM squad_interest_topics')):
            if conn.execute('SELECT 1 FROM squad_interest_aliases WHERE scope=?', (old,)).fetchone():
                continue
            value = topic(guild_id, label.split(' · ', 1)[0])
            canonical = value['id']
            conn.execute('INSERT OR IGNORE INTO squad_interest_topics VALUES (?,?,?)',
                         (canonical, guild_id, value['label']))
            conn.execute('INSERT OR IGNORE INTO squad_interest_aliases VALUES (?,?)', (old, canonical))
            conn.execute('INSERT OR IGNORE INTO squad_interest_aliases VALUES (?,?)', (canonical, canonical))
            if canonical != old:
                conn.execute('''INSERT OR IGNORE INTO squad_interest_members
                    (scope,user_id,last_notified,kind,excluded_session)
                    SELECT ?,user_id,last_notified,kind,excluded_session
                    FROM squad_interest_members WHERE scope=?''', (canonical, old))
                conn.execute('DELETE FROM squad_interest_members WHERE scope=?', (old,))
                conn.execute('''INSERT OR IGNORE INTO squad_interest_attempts
                    SELECT session_id,?,attempted_at FROM squad_interest_attempts WHERE scope=?''', (canonical, old))


def _scope(conn, scope):
    row = conn.execute('SELECT game_scope FROM squad_interest_aliases WHERE scope=?', (scope,)).fetchone()
    return row[0] if row else scope


def remember(value):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT OR IGNORE INTO squad_interest_topics VALUES (?,?,?)',
                     (value['id'], value['guild_id'], value['label']))
        conn.execute('INSERT OR IGNORE INTO squad_interest_aliases VALUES (?,?)', (value['id'], value['id']))


def topics():
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return [dict(id=r[0], guild_id=r[1], label=r[2]) for r in
                conn.execute('SELECT scope,guild_id,label FROM squad_interest_topics')]


def toggle(scope, guild_id, user_id, kind='once', excluded_session=''):
    if kind not in ('once', 'always'):
        raise ValueError('Unknown notification kind')
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        scope = _scope(conn, scope)
        if not conn.execute('SELECT 1 FROM squad_interest_topics WHERE scope=? AND guild_id=?',
                            (scope, guild_id)).fetchone():
            raise ValueError('Unknown interest topic')
        previous = conn.execute('SELECT kind FROM squad_interest_members WHERE scope=? AND user_id=?',
                                (scope, user_id)).fetchone()
        if previous and previous[0] == kind:
            conn.execute('DELETE FROM squad_interest_members WHERE scope=? AND user_id=?', (scope, user_id))
            return False
        conn.execute('''INSERT INTO squad_interest_members(scope,user_id,kind,excluded_session)
            VALUES (?,?,?,?) ON CONFLICT(scope,user_id) DO UPDATE
            SET kind=excluded.kind, excluded_session=excluded.excluded_session''',
                     (scope, user_id, kind, excluded_session))
        return True


def preferences(scope):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return {r[0]: r[1] for r in conn.execute(
            'SELECT user_id,kind FROM squad_interest_members WHERE scope=? ORDER BY user_id', (_scope(conn, scope),))}


def members(scope):
    return list(preferences(scope))


def track_card(scope, channel_id, message_id, session_id=''):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('''INSERT INTO squad_interest_cards VALUES (?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET scope=excluded.scope,
            channel_id=excluded.channel_id, session_id=excluded.session_id''',
                     (message_id, channel_id, _scope(conn, scope), session_id))


def cards(scope):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return [dict(message_id=r[0], channel_id=r[1], session_id=r[2]) for r in conn.execute(
            'SELECT message_id,channel_id,session_id FROM squad_interest_cards WHERE scope=?', (_scope(conn, scope),))]


def card_session(message_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        row = conn.execute('SELECT session_id FROM squad_interest_cards WHERE message_id=?', (message_id,)).fetchone()
        return row[0] if row else ''


def forget_card(message_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('DELETE FROM squad_interest_cards WHERE message_id=?', (message_id,))


def reserve(session_id, scope, eligible, *, now=None):
    """Claim before posting, consuming one-shots; uncertain sends never replay."""
    initialize()
    current = time.time() if now is None else now
    selected = []
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        scope = _scope(conn, scope)
        if not conn.execute('INSERT OR IGNORE INTO squad_interest_attempts VALUES (?,?,?)',
                            (session_id, scope, current)).rowcount:
            return []
        for user_id in eligible:
            row = conn.execute('''SELECT kind,excluded_session FROM squad_interest_members
                WHERE scope=? AND user_id=?''', (scope, user_id)).fetchone()
            if not row or row[1] == session_id:
                continue
            selected.append(user_id)
            if row[0] == 'once':
                conn.execute('DELETE FROM squad_interest_members WHERE scope=? AND user_id=?', (scope, user_id))
            else:
                conn.execute('UPDATE squad_interest_members SET last_notified=? WHERE scope=? AND user_id=?',
                             (current, scope, user_id))
    return selected
