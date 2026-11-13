"""Durable, game-scoped one-shot and recurring session notifications."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

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
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_interest_delivery (
            session_id TEXT, scope TEXT, batch INTEGER, users TEXT NOT NULL,
            state TEXT NOT NULL, retry_at REAL NOT NULL DEFAULT 0, message_id INTEGER,
            PRIMARY KEY(session_id,scope,batch))''')
        delivery_columns={r[1] for r in conn.execute('PRAGMA table_info(squad_interest_delivery)')}
        if 'revision' not in delivery_columns:
            conn.execute("ALTER TABLE squad_interest_delivery ADD COLUMN revision TEXT NOT NULL DEFAULT ''")
        if 'context' not in delivery_columns:
            conn.execute("ALTER TABLE squad_interest_delivery ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
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
        conn.execute('CREATE TABLE IF NOT EXISTS squad_interest_cancellations(scope TEXT,user_id INTEGER,stamp REAL,PRIMARY KEY(scope,user_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS squad_ended_sessions(session_id TEXT PRIMARY KEY,stamp REAL)')
        conn.execute('CREATE TABLE IF NOT EXISTS squad_closed_notices(session_id TEXT,scope TEXT,batch INTEGER,message_id INTEGER,PRIMARY KEY(session_id,scope,batch,message_id))')
        if 'compact' not in {r[1] for r in conn.execute('PRAGMA table_info(squad_closed_notices)')}:
            conn.execute('ALTER TABLE squad_closed_notices ADD COLUMN compact INTEGER NOT NULL DEFAULT 0')
        conn.execute('CREATE TABLE IF NOT EXISTS squad_close_retries(session_id TEXT,scope TEXT,batch INTEGER,retry_at REAL,PRIMARY KEY(session_id,scope,batch))')
        conn.execute('CREATE TABLE IF NOT EXISTS squad_card_posts(attempt TEXT PRIMARY KEY,session_id TEXT,destination INTEGER,voice INTEGER,stamp REAL,state TEXT,message_id INTEGER)')
        conn.execute('CREATE INDEX IF NOT EXISTS squad_card_post_session ON squad_card_posts(session_id,stamp)')
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
            _cancel_receipt(conn, scope, user_id)
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
        if conn.execute('SELECT 1 FROM squad_ended_sessions WHERE session_id=?', (session_id,)).fetchone():
            return []
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
        for index in range(0,len(selected),20):
            conn.execute('INSERT OR IGNORE INTO squad_interest_delivery(session_id,scope,batch,users,state) VALUES(?,?,?,?,?)',
                         (session_id,scope,index//20,json.dumps(selected[index:index+20]),'pending'))
    return selected


def pending_deliveries(session_id,scope,now=None):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        scope=_scope(conn,scope)
        return [(batch,json.loads(users)) for batch,users in conn.execute(
            "SELECT batch,users FROM squad_interest_delivery WHERE session_id=? AND scope=? AND state='pending' AND retry_at<=? AND NOT EXISTS(SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=squad_interest_delivery.session_id) ORDER BY batch",
            (session_id,scope,time.time() if now is None else now))]


def delivery_context(session_id,scope,context):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        scope=_scope(conn,scope)
        conn.execute("UPDATE squad_interest_delivery SET context=? WHERE session_id=? AND scope=? AND context='{}'",
                     (json.dumps(context),session_id,scope))


def claim_delivery(session_id,scope,batch):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        scope=_scope(conn,scope)
        revision=uuid.uuid4().hex
        changed=conn.execute("UPDATE squad_interest_delivery SET state='uncertain',revision=? WHERE session_id=? AND scope=? AND batch=? AND state='pending' AND NOT EXISTS(SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=squad_interest_delivery.session_id)",
                              (revision,session_id,scope,batch)).rowcount
        return revision if changed else None


def finish_delivery(session_id,scope,batch,*,message_id=None,retry=False,now=None,expected_revision=None):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        scope=_scope(conn,scope)
        conn.execute("UPDATE squad_interest_delivery SET state=?,message_id=?,retry_at=? WHERE session_id=? AND scope=? AND batch=? AND state='uncertain' AND (? IS NULL OR revision=?)",
                     (('cancelled' if retry and conn.execute('SELECT 1 FROM squad_ended_sessions WHERE session_id=?',(session_id,)).fetchone() else 'pending') if retry else 'sent',message_id,(time.time() if now is None else now)+60 if retry else 0,session_id,scope,batch,expected_revision,expected_revision))


def _cancel_receipt(conn, scope, user_id):
    conn.execute('INSERT INTO squad_interest_cancellations VALUES(?,?,?) ON CONFLICT(scope,user_id) DO UPDATE SET stamp=excluded.stamp',
                 (scope,user_id,time.time()))


def cancel(scope, guild_id, user_id):
    """Idempotent withdrawal includes already reserved, not-yet-sent one shots."""
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        scope = _scope(conn, scope)
        if not conn.execute('SELECT 1 FROM squad_interest_topics WHERE scope=? AND guild_id=?',(scope,guild_id)).fetchone():
            raise ValueError('Unknown interest topic')
        conn.execute('DELETE FROM squad_interest_members WHERE scope=? AND user_id=?',(scope,user_id))
        _cancel_receipt(conn,scope,user_id)


def delivery_users(session_id, scope, batch, revision):
    """Fence the claimed revision and recheck withdrawals immediately before send."""
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        scope = _scope(conn,scope)
        row = conn.execute("SELECT d.users,a.attempted_at FROM squad_interest_delivery d JOIN squad_interest_attempts a ON a.session_id=d.session_id AND a.scope=d.scope WHERE d.session_id=? AND d.scope=? AND d.batch=? AND d.revision=? AND d.state='uncertain' AND NOT EXISTS(SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=d.session_id)",
                           (session_id,scope,batch,revision)).fetchone()
        if not row:return []
        return [uid for uid in json.loads(row[0]) if not conn.execute(
            'SELECT 1 FROM squad_interest_cancellations WHERE scope=? AND user_id=? AND stamp>=?',(scope,uid,row[1])).fetchone()]


def own_preferences(guild_id, user_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        rows = {scope:dict(id=scope,label=label,kind=kind) for scope,label,kind in conn.execute(
            'SELECT t.scope,t.label,m.kind FROM squad_interest_topics t JOIN squad_interest_members m ON m.scope=t.scope WHERE t.guild_id=? AND m.user_id=?',(guild_id,user_id))}
        # reserve consumes a once preference before POST; keep queued receipts visible.
        for scope,label,users,attempted in conn.execute("SELECT d.scope,t.label,d.users,a.attempted_at FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope JOIN squad_interest_attempts a ON a.scope=d.scope AND a.session_id=d.session_id WHERE t.guild_id=? AND d.state='pending' AND NOT EXISTS(SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=d.session_id)",(guild_id,)):
            if user_id in json.loads(users) and not conn.execute('SELECT 1 FROM squad_interest_cancellations WHERE scope=? AND user_id=? AND stamp>=?',(scope,user_id,attempted)).fetchone():
                rows.setdefault(scope,dict(id=scope,label=label,kind='pending'))
        return sorted(rows.values(),key=lambda x:x['label'].casefold())


def end_session(session_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT OR IGNORE INTO squad_ended_sessions VALUES(?,?)',(session_id,time.time()))
        # Known unsent work is terminal; uncertain evidence remains for manual review.
        conn.execute("UPDATE squad_interest_delivery SET state='cancelled',revision=? WHERE session_id=? AND state='pending'",(uuid.uuid4().hex,session_id))


def link_footprint(session_id, message_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        for scope,batch,raw in conn.execute('SELECT scope,batch,context FROM squad_interest_delivery WHERE session_id=?',(session_id,)).fetchall():
            context=json.loads(raw)
            context.setdefault('original_card',context.get('card'))
            context['card']=message_id
            conn.execute('UPDATE squad_interest_delivery SET context=? WHERE session_id=? AND scope=? AND batch=?',
                         (json.dumps(context),session_id,scope,batch))
        # A notice might already have closed while a footprint edit was retried.
        conn.execute('UPDATE squad_closed_notices SET compact=0 WHERE session_id=?',(session_id,))


def closing_notices(limit=20):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        return [dict(session=s,scope=t,batch=b,message_id=m,context=json.loads(c),guild_id=g,label=l)
            # Revisit legacy notices once, even if startup refresh has already
            # removed their subscription-card tracking. Keep retries durable.
            for s,t,b,m,c,g,l in conn.execute("SELECT d.session_id,d.scope,d.batch,d.message_id,d.context,t.guild_id,t.label FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope JOIN squad_ended_sessions e ON e.session_id=d.session_id WHERE d.state='sent' AND d.message_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM squad_closed_notices n WHERE n.session_id=d.session_id AND n.scope=d.scope AND n.batch=d.batch AND n.message_id=d.message_id AND n.compact=1) AND NOT EXISTS(SELECT 1 FROM squad_close_retries r WHERE r.session_id=d.session_id AND r.scope=d.scope AND r.batch=d.batch AND r.retry_at>?) ORDER BY e.stamp LIMIT ?",(time.time(),limit))]


def notice_closed(row):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT OR REPLACE INTO squad_closed_notices(session_id,scope,batch,message_id,compact) VALUES(?,?,?,?,1)',(row['session'],row['scope'],row['batch'],row['message_id']))


def begin_card_post(session_id, destination, voice):
    initialize()
    attempt=uuid.uuid4().hex
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM squad_card_posts WHERE session_id=? AND state='uncertain'",(session_id,)).fetchone():
            raise RuntimeError('Squad card send uncertain; inspect existing message before recovery')
        conn.execute('INSERT INTO squad_card_posts VALUES(?,?,?,?,?,?,NULL)',(attempt,session_id,destination,voice,time.time(),'uncertain'))
    return attempt


def finish_card_post(attempt, *, message_id=None, rejected=False):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute("UPDATE squad_card_posts SET state=?,message_id=? WHERE attempt=? AND state='uncertain'",('rejected' if rejected else 'sent',message_id,attempt))


def uncertain_card(session_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        row=conn.execute("SELECT attempt,destination,voice,stamp FROM squad_card_posts WHERE session_id=? AND state='uncertain' ORDER BY stamp DESC LIMIT 1",(session_id,)).fetchone()
        return dict(zip(('attempt','destination','voice','stamp'),row)) if row else None


def latest_card_post(session_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        row=conn.execute('SELECT state,message_id FROM squad_card_posts WHERE session_id=? ORDER BY stamp DESC,rowid DESC LIMIT 1',(session_id,)).fetchone()
        return dict(state=row[0],message_id=row[1]) if row else None


def canonical_scope(scope):
    initialize()
    with connect_sqlite(STATS_DB) as conn:return _scope(conn,scope)


def notice_close_failed(row):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT INTO squad_close_retries VALUES(?,?,?,?) ON CONFLICT(session_id,scope,batch) DO UPDATE SET retry_at=excluded.retry_at',
            (row['session'],row['scope'],row['batch'],time.time()+60))
