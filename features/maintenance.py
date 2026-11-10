"""Read-only configuration snapshots and crash-safe maintenance alert receipts.

No Discord mutations live here. Baselines are explicitly accepted, versioned,
never advanced by a poll. A send intent is durable before a network send.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from core.sqlite_storage import connect_sqlite


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def canonical(value):
    """Discord config arrays are sets; list ordering is not a setting change."""
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=encode)
    return value


def snapshot(roles, channels, rules, bots, temporary=()):
    temporary = set(map(str, temporary))
    return {
        'roles': {str(r.id): str(r.permissions.value) for r in roles},
        'channels': {
            str(c['id']): canonical({
                'type': c['type'], 'parent_id': c.get('parent_id'),
                'overwrites': c.get('permission_overwrites', []),
            }) for c in channels if str(c['id']) not in temporary
        },
        'automod': {str(r['id']): canonical({k: v for k, v in r.items()
                    if k not in ('id', 'guild_id', 'creator_id', 'name')}) for r in rules},
        'bots': {str(uid): sorted(map(str, ids)) for uid, ids in bots.items()},
    }


def differences(before, after):
    """Only bounded category counts and IDs leave private snapshot storage."""
    result = {}
    for category in ('roles', 'channels', 'automod', 'bots'):
        left, right = before[category], after[category]
        ids = sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))
        if ids:
            result[category] = ids
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)
        with connect_sqlite(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS baselines (
                    id INTEGER PRIMARY KEY, guild INTEGER NOT NULL, actor INTEGER NOT NULL,
                    stamp REAL NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS state (
                    guild INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                    channel INTEGER NOT NULL DEFAULT 0, candidate TEXT,
                    last TEXT, fingerprint TEXT, repeats INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS receipts (
                    guild INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL, stamp REAL NOT NULL, message INTEGER,
                    PRIMARY KEY(guild, fingerprint));
            ''')

    def state(self, guild):
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT enabled,channel,last FROM state WHERE guild=?', (guild,)).fetchone()
            baseline = db.execute('SELECT id,actor,stamp,snapshot FROM baselines WHERE guild=? ORDER BY id DESC LIMIT 1', (guild,)).fetchone()
            receipts = db.execute("SELECT state,count(*) FROM receipts WHERE guild=? GROUP BY state", (guild,)).fetchall()
        return dict(enabled=bool(row and row[0]), channel=row[1] if row else 0,
                    last=json.loads(row[2]) if row and row[2] else None,
                    baseline=dict(id=baseline[0], actor=baseline[1], stamp=baseline[2], snapshot=json.loads(baseline[3])) if baseline else None,
                    receipts=dict(receipts))

    def preview(self, guild, actor, observed, channel, now=None):
        token = digest({'snapshot': observed, 'channel': channel})[:16]
        candidate = dict(actor=actor, stamp=time.time() if now is None else now,
                         token=token, snapshot=observed, channel=channel)
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO state(guild) VALUES(?)', (guild,))
            db.execute('UPDATE state SET candidate=? WHERE guild=?', (encode(candidate), guild))
        return token

    def candidate_channel(self, guild):
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT candidate FROM state WHERE guild=?', (guild,)).fetchone()
        return json.loads(row[0])['channel'] if row and row[0] else 0

    def accept(self, guild, actor, token, observed, now=None):
        now = time.time() if now is None else now
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT candidate FROM state WHERE guild=?', (guild,)).fetchone()
            candidate = json.loads(row[0]) if row and row[0] else None
            if (not candidate or candidate['actor'] != actor or candidate['token'] != token
                    or not 0 <= now - candidate['stamp'] <= 600
                    or candidate['snapshot'] != observed):
                raise ValueError('預覽已過期、設定有變或確認碼不符；請重新預覽。')
            db.execute('INSERT INTO baselines(guild,actor,stamp,snapshot) VALUES(?,?,?,?)',
                       (guild, actor, now, encode(observed)))
            db.execute('UPDATE state SET candidate=NULL,channel=?,fingerprint=NULL,repeats=0 WHERE guild=?',
                       (candidate['channel'], guild))
            # Keep old receipts: accepting a new baseline never retries an uncertain send.

    def enable(self, guild, enabled):
        if enabled and not self.state(guild)['baseline']:
            raise ValueError('請先預覽及確認基準。')
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO state(guild) VALUES(?)', (guild,))
            db.execute('UPDATE state SET enabled=?,fingerprint=NULL,repeats=0 WHERE guild=?', (int(enabled), guild))

    def observe(self, guild, findings, *, background, now=None):
        now = time.time() if now is None else now
        fingerprint = digest(findings) if findings else None
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO state(guild) VALUES(?)', (guild,))
            row = db.execute('SELECT enabled,fingerprint,repeats FROM state WHERE guild=?', (guild,)).fetchone()
            repeats = (row[2] + 1 if row[1] == fingerprint else 1) if fingerprint else 0
            db.execute('UPDATE state SET last=? WHERE guild=?', (encode(dict(stamp=now, findings=findings)), guild))
            if not background:
                return None
            db.execute('UPDATE state SET fingerprint=?,repeats=? WHERE guild=?', (fingerprint, repeats, guild))
            if not row[0] or not fingerprint or repeats < 2:
                return None
            count = db.execute('SELECT count(*) FROM receipts WHERE guild=?', (guild,)).fetchone()[0]
            if count >= 1000:
                return None  # fail closed; status exposes full journal, no eviction/re-send
            exists = db.execute('SELECT 1 FROM receipts WHERE guild=? AND fingerprint=?', (guild, fingerprint)).fetchone()
            return None if exists else fingerprint

    def reserve(self, guild, fingerprint):
        with connect_sqlite(self.path) as db:
            cursor = db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,'uncertain',?,NULL)",
                                (guild, fingerprint, time.time()))
            return cursor.rowcount == 1

    def sent(self, guild, fingerprint, message):
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE receipts SET state='sent',message=? WHERE guild=? AND fingerprint=?",
                       (message, guild, fingerprint))
