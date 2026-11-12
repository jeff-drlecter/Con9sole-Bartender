"""Bounded durable outbox for community audit events; no Discord/network calls."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from core.sqlite_storage import connect_sqlite, enable_wal

RETENTION_SECONDS = 30 * 86400
MAX_EVENTS = 20000


def event_id() -> str:
    return uuid.uuid4().hex


class AuditStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.path) as db:
            enable_wal(db)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS audit_events(
                    id TEXT PRIMARY KEY, stamp REAL NOT NULL, category TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
                    message_id INTEGER, error TEXT);
                CREATE INDEX IF NOT EXISTS audit_due ON audit_events(state,due,stamp);
            ''')
            # A process may have died after Discord accepted a send. Never blindly resend it.
            db.execute("UPDATE audit_events SET state='uncertain',error='process interrupted during delivery' WHERE state='sending'")

    def append(self, category, payload, *, key=None, now=None):
        now = time.time() if now is None else now
        key = key or event_id()
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM audit_events WHERE id=?', (key,)).fetchone():
                return key
            db.execute("DELETE FROM audit_events WHERE stamp<? AND state IN ('sent','acknowledged')", (now-RETENTION_SECONDS,))
            count = db.execute('SELECT count(*) FROM audit_events').fetchone()[0]
            if count >= MAX_EVENTS:
                db.execute("DELETE FROM audit_events WHERE id IN (SELECT id FROM audit_events WHERE state IN ('sent','acknowledged') ORDER BY stamp LIMIT 1000)")
                if db.execute('SELECT count(*) FROM audit_events').fetchone()[0] >= MAX_EVENTS:
                    raise RuntimeError('Audit outbox full: unresolved records preserved')
            db.execute('INSERT INTO audit_events(id,stamp,category,payload) VALUES(?,?,?,?)',
                       (key, now, category, json.dumps(payload, ensure_ascii=False)))
        return key

    def pending(self, category, now=None, limit=5):
        with connect_sqlite(self.path) as db:
            rows = db.execute("SELECT id,stamp,payload FROM audit_events WHERE category=? AND state='pending' AND due<=? ORDER BY stamp,id LIMIT ?",
                              (category,time.time() if now is None else now,limit)).fetchall()
        return [(key,stamp,json.loads(raw)) for key,stamp,raw in rows]

    def claim(self, keys):
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if any(db.execute('SELECT state FROM audit_events WHERE id=?',(key,)).fetchone() != ('pending',) for key in keys):
                return False
            db.executemany("UPDATE audit_events SET state='sending',attempts=attempts+1 WHERE id=?", ((key,) for key in keys))
        return True

    def finish(self, keys, state, *, message_id=None, error=None):
        if state not in {'sent','pending','uncertain'}:
            raise ValueError(state)
        with connect_sqlite(self.path) as db:
            db.executemany("UPDATE audit_events SET state=?,message_id=?,error=?,due=? WHERE id=? AND state='sending'",
                           ((state,message_id,error,time.time()+60,key) for key in keys))

    def prune(self):
        with connect_sqlite(self.path) as db:
            db.execute("DELETE FROM audit_events WHERE stamp<? AND state IN ('sent','acknowledged')", (time.time()-RETENTION_SECONDS,))

    def summary(self):
        with connect_sqlite(self.path) as db:
            states = dict(db.execute('SELECT state,count(*) FROM audit_events GROUP BY state'))
            recent = db.execute("SELECT id,category,state,error FROM audit_events WHERE state IN ('uncertain','pending') ORDER BY stamp LIMIT 8").fetchall()
        return states,recent

    def resolve(self, key, action):
        if action not in {'retry','ack'}:
            raise ValueError(action)
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE audit_events SET state=?,due=0,error=NULL WHERE id=? AND state='uncertain'",
                                   ('pending' if action=='retry' else 'acknowledged',key)).rowcount)
