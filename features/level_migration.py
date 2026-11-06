"""Lossless offline XP transfer and recovery primitives.

Call only with the Bot's role+ledger locks held (or with the Bot stopped).
A matching source manifest is necessary, not sufficient proof of source completeness.
Never put real snapshots, Discord IDs or backup databases in git.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.sqlite_storage import connect_sqlite
from features.community_levels import DEFAULTS, Ledger, calendar, level_for, threshold

MAX_INT = 2**63-1
TABLES = ('xp','periods','cooldowns','receipts','bindings','notice_state','imports','xp_events','role_jobs','repair_attempts','weekly_notices')


def strict_json(raw: str):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def bad(value): raise ValueError('Non-finite JSON number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)


def integer(value, *, positive=False):
    if type(value) is str and value.isascii() and value.isdecimal() and str(int(value))==value:
        value=int(value)
    if type(value) is not int or not (1 if positive else 0)<=value<=MAX_INT:
        raise ValueError('Invalid integer/Discord ID')
    return value


def instant(value):
    if not isinstance(value,str): raise ValueError('Timestamp must be ISO8601 UTC')
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None or dt.utcoffset().total_seconds()!=0:
        raise ValueError('Timestamp must be UTC aware')
    return dt.timestamp()


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate_snapshot(snapshot, *, guild, roster_ids, expected_count):
    """Independent roster and source count must be supplied outside the snapshot."""
    if type(snapshot) is not dict or (type(snapshot.get('schema')) is not int or snapshot.get('schema')!=1) or snapshot.get('source')!='amari':
        raise ValueError('Unsupported snapshot schema/source')
    if integer(snapshot.get('guild_id'),positive=True)!=guild: raise ValueError('Wrong guild')
    capture=instant(snapshot.get('captured_at'))
    cutover=instant(snapshot.get('cutover_at'))
    frozen=instant(snapshot.get('source_frozen_at'))
    if frozen!=cutover or capture<cutover:
        raise ValueError('Source must be frozen at the common cutover time')
    scope=[integer(uid,positive=True) for uid in roster_ids]
    if len(scope)!=len(set(scope)) or integer(expected_count)!=len(scope):
        raise ValueError('Independent roster/count mismatch')
    rows=snapshot.get('users')
    if not isinstance(rows,list) or len(rows)!=expected_count or not 0<len(rows)<=100000:
        raise ValueError('Incomplete snapshot')
    clean=[]
    for row in rows:
        if type(row) is not dict or set(row)!={'user_id','total_xp','level','level_xp','weekly_xp'}:
            raise ValueError('Snapshot must contain raw XP, exact level, within-level XP and weekly XP')
        uid=integer(row['user_id'],positive=True)
        xp=integer(row['total_xp']); level=integer(row['level']); within=integer(row['level_xp']); weekly=integer(row['weekly_xp'])
        if level>10000 or level_for(xp)!=level or within!=xp-threshold(level):
            raise ValueError('Raw XP/level/within-level mismatch')
        clean.append(dict(user_id=uid,total_xp=xp,level=level,level_xp=within,weekly_xp=weekly))
    ids=[r['user_id'] for r in clean]
    if len(ids)!=len(set(ids)) or set(ids)!=set(scope): raise ValueError('Missing, duplicate or extra users')
    # Amari's weekly counter need not be a calendar week and may exceed total XP.
    period=snapshot.get('weekly_period')
    if not isinstance(period,str) or not period.strip() or len(period)>100:
        raise ValueError('Source weekly-period provenance is required')
    return dict(rows=clean,scope=set(scope),cutover=cutover,captured=capture,digest=digest(snapshot),period=period)


def create_backup(ledger: Ledger, destination: Path):
    destination=Path(destination)
    if destination.is_symlink() or destination.resolve()==ledger.path.resolve() or destination.exists():
        raise ValueError('Backup target must be new, distinct and not a symlink')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with connect_sqlite(ledger.path) as source, connect_sqlite(destination) as target:
            source.backup(target)
        with connect_sqlite(destination) as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0]!='delete':
                raise ValueError('Backup must be a standalone database')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Backup integrity failed')
        return hashlib.sha256(destination.read_bytes()).hexdigest()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def apply_snapshot(ledger, snapshot, *, guild, roster_ids, expected_count, backup_path, commit=False):
    plan=validate_snapshot(snapshot,guild=guild,roster_ids=roster_ids,expected_count=expected_count)
    cfg=ledger.settings(guild)
    if cfg['mode']!='off': raise ValueError('Pause all ledger writers before migration')
    with connect_sqlite(ledger.path) as db:
        if db.execute('SELECT 1 FROM migration_manifests WHERE guild=?',(guild,)).fetchone():
            raise ValueError('Snapshot already applied; use a reviewed restore instead')
        if db.execute('SELECT 1 FROM adjustments WHERE guild=? AND stamp>=? LIMIT 1',(guild,plan['cutover'])).fetchone():
            raise ValueError('Post-cutover adjustments require an explicit reviewed policy')
        if db.execute('SELECT 1 FROM departed_users WHERE guild=? AND stamp>=? LIMIT 1',(guild,plan['cutover'])).fetchone():
            raise ValueError('Post-cutover departures require an explicit reviewed policy')
        bridge=db.execute('SELECT user,source,amount,stamp FROM xp_events WHERE guild=? AND stamp>=?',(guild,plan['cutover'])).fetchall()
    if not commit:
        return dict(count=len(plan['rows']),source_total=sum(r['total_xp'] for r in plan['rows']),
                    source_weekly=sum(r['weekly_xp'] for r in plan['rows']),bridge_events=len(bridge),digest=plan['digest'])
    backup_sha=create_backup(ledger,Path(backup_path))
    with connect_sqlite(ledger.path) as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
        if current and json.loads(current[0]).get('mode','off')!='off': raise ValueError('Ledger is no longer paused')
        if db.execute('SELECT 1 FROM migration_manifests WHERE guild=?',(guild,)).fetchone(): raise ValueError('Migration raced another writer')
        if db.execute('SELECT 1 FROM adjustments WHERE guild=? AND stamp>=? LIMIT 1',(guild,plan['cutover'])).fetchone():
            raise ValueError('Post-cutover adjustments require an explicit reviewed policy')
        if db.execute('SELECT 1 FROM departed_users WHERE guild=? AND stamp>=? LIMIT 1',(guild,plan['cutover'])).fetchone():
            raise ValueError('Post-cutover departures require an explicit reviewed policy')
        # Keep durable post-cutover events, not additive pre-cutover shadow totals.
        post=db.execute('SELECT event,user,source,amount,stamp FROM xp_events WHERE guild=? AND stamp>=?',(guild,plan['cutover'])).fetchall()
        if any(uid not in plan['scope'] for _,uid,_,_,_ in post):
            raise ValueError('Post-cutover event owner outside verified scope')
        for table in TABLES:
            if table!='xp_events': db.execute(f'DELETE FROM {table} WHERE guild=?',(guild,))
        db.execute('DELETE FROM xp_events WHERE guild=? AND stamp<?',(guild,plan['cutover']))
        for row in plan['rows']:
            uid=row['user_id'];xp=row['total_xp']
            db.execute('INSERT INTO xp(guild,user,total,imported) VALUES(?,?,?,?)',(guild,uid,xp,xp))
            db.execute('INSERT INTO periods VALUES(?,?,?,?)',(guild,uid,'amari-legacy',row['weekly_xp']))
            db.execute('INSERT INTO notice_state VALUES(?,?,?)',(guild,uid,row['level']))
        for event,uid,source,amount,stamp in post:
            if source not in ('text','activity','voice'): raise ValueError('Invalid bridge source')
            integer(amount)
            total=db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,uid)).fetchone()[0]
            integer(total+amount)
            db.execute(f'UPDATE xp SET total=total+?,{source}={source}+? WHERE guild=? AND user=?',(amount,amount,guild,uid))
            week=calendar(stamp)[1]
            db.execute('INSERT INTO periods VALUES(?,?,?,?) ON CONFLICT(guild,user,week) DO UPDATE SET points=points+excluded.points',(guild,uid,week,amount))
            db.execute('INSERT INTO receipts VALUES(?,?,?)',(guild,event,stamp))
        # Rebuild accepted post-cutover cooldowns/caps; migration cannot reopen a farm window.
        clocks={};activities={}
        for event,uid,source,amount,stamp in post:
            bucket='voice' if source=='voice' else 'engagement'
            clocks[(uid,bucket)]=max(stamp,clocks.get((uid,bucket),stamp))
            if source=='activity':
                day=calendar(stamp)[0]
                activities[(uid,day)]=activities.get((uid,day),0)+1
        for (uid,bucket),stamp in clocks.items():
            db.execute('INSERT INTO cooldowns VALUES(?,?,?,?,?,?)',(guild,uid,bucket,stamp,calendar(stamp)[0],0))
        for uid in {u for u,_ in activities}:
            day=max(d for u,d in activities if u==uid)
            db.execute('INSERT INTO cooldowns VALUES(?,?,?,?,?,?)',(guild,uid,'activity_cap',clocks[(uid,'engagement')],day,activities[(uid,day)]))
        cfg.update(mode='off',cutover_at=plan['cutover'])
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(guild,json.dumps(cfg)))
        db.execute('INSERT INTO migration_manifests VALUES(?,?,?,?,?,?,?)',(guild,plan['digest'],plan['cutover'],len(plan['rows']),plan['period'],str(backup_path),backup_sha))
    return dict(count=len(plan['rows']),digest=plan['digest'],backup_sha=backup_sha)


def restore_backup(ledger, backup_path, *, expected_sha, guild, checkpoint_path):
    """Bot must be stopped/locked. Hash exactly the bytes that are validated and restored."""
    source=Path(backup_path)
    if source.is_symlink() or source.resolve()==ledger.path.resolve() or not source.is_file():
        raise ValueError('Invalid backup path')
    if any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Backup sidecars are forbidden; create a standalone backup')
    verified=source.read_bytes()
    if hashlib.sha256(verified).hexdigest()!=expected_sha:raise ValueError('Backup checksum mismatch')
    fd,raw=tempfile.mkstemp(prefix='level-restore-',suffix='.sqlite3',dir=ledger.path.parent)
    staging=Path(raw)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(verified);handle.flush();os.fsync(handle.fileno())
        with connect_sqlite(staging) as db:
            if db.execute('PRAGMA journal_mode').fetchone()[0]!='delete':
                raise ValueError('Only standalone DELETE-journal backups are accepted')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Corrupt backup')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(TABLES+('settings','migration_manifests')).issubset(tables):
                raise ValueError('Incompatible backup')
            with connect_sqlite(ledger.path) as current:
                expected={r[0]:r[1] for r in current.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}
            actual={r[0]:r[1] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}
            if expected!=actual:raise ValueError('Incompatible backup table schema')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
                raise ValueError('Unexpected executable schema in backup')
            guilds=set()
            for table in tables:
                columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                if 'guild' in columns:guilds.update(r[0] for r in db.execute(f'SELECT DISTINCT guild FROM {table}'))
            if guilds!={guild}:raise ValueError('Backup guild mismatch')
            for gid,value in db.execute('SELECT guild,value FROM settings').fetchall():
                cfg=json.loads(value);cfg['mode']='off'
                db.execute('UPDATE settings SET value=? WHERE guild=?',(json.dumps(cfg),gid))
        if ledger.settings(guild)['mode']!='off':raise ValueError('Pause before restoring')
        checkpoint_sha=create_backup(ledger,Path(checkpoint_path))
        with connect_sqlite(staging) as clean,connect_sqlite(ledger.path) as live:
            clean.backup(live)
        return dict(checkpoint_sha=checkpoint_sha,mode='off')
    except sqlite3.DatabaseError as exc:
        raise ValueError('Invalid backup database') from exc
    finally:
        staging.unlink(missing_ok=True)
        for suffix in ('-wal','-shm','-journal'):Path(str(staging)+suffix).unlink(missing_ok=True)


def role_restore_plan(before, current, managed_ids):
    """Plan only reviewed level-role changes; never grants arbitrary snapshot roles."""
    managed=[integer(x,positive=True) for x in managed_ids]
    if len(managed)!=len(set(managed)):raise ValueError('Duplicate managed role ID')
    allowed=set(managed)
    def normalize(values):
        result={}
        for raw_uid,raw_roles in values.items():
            uid=integer(raw_uid,positive=True)
            if uid in result:raise ValueError('Duplicate normalized user ID')
            roles=[integer(x,positive=True) for x in raw_roles]
            if len(roles)!=len(set(roles)):raise ValueError('Duplicate role ID')
            result[uid]=set(roles)
        return result
    before=normalize(before);current=normalize(current)
    result=[]
    for uid,roles in before.items():
        if not roles<=allowed:raise ValueError('Unsafe role snapshot')
        actual=current.get(uid,set()) & allowed
        result.append(dict(user_id=uid,add=sorted(roles-actual),remove=sorted(actual-roles)))
    return result
