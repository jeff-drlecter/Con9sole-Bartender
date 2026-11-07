"""Owner-authorized public-board / role-floor baseline, separate from lossless import."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from core.sqlite_storage import connect_sqlite
from features.community_levels import REWARD_NAMES,level_for,threshold
from features.level_migration import create_backup,digest,integer,strict_json


def role_mapping(roles):
    result={}
    for role in roles:
        match=re.fullmatch(r'Lv\s*(\d+)\s*(.+)',role['name'],re.I)
        if not match:continue
        level=int(match[1])
        if level not in REWARD_NAMES or match[2]!=REWARD_NAMES[level]:continue
        if level in result:raise ValueError('Duplicate level-role names; map actual role IDs before migration')
        result[level]=integer(role['id'],positive=True)
    if set(result)!=set(REWARD_NAMES):raise ValueError('The full ten level-role IDs must be verified before migration')
    return result


def roster_digest(members):
    return digest(sorted(members,key=lambda row:row['id']))


def stage_public(ledger,guild,raw,now,*,expected_count=120):
    data=strict_json(raw)
    if type(data) is not dict or set(data)!={'batch','part','parts','rows','expected_count','observed_at'}:raise ValueError('Invalid public-board package')
    if integer(data['expected_count'],positive=True)!=expected_count:raise ValueError('Independent public-board count mismatch')
    observed=data['observed_at']
    if type(observed) not in (int,float) or not 0<=now-observed<=600:raise ValueError('Public-board observation expired')
    batch=data['batch'];part=integer(data['part'],positive=True);parts=integer(data['parts'],positive=True)
    if not isinstance(batch,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',batch) or not 1<=part<=parts<=20:
        raise ValueError('Invalid public-board part')
    rows=data['rows']
    if type(rows) is not list or not 1<=len(rows)<=50:raise ValueError('Invalid public-board rows')
    clean=[]
    for row in rows:
        if type(row) is not list or len(row)!=4:raise ValueError('Expected rank/name/XP/level')
        rank,name,xp,level=row;rank=integer(rank,positive=True);xp=integer(xp);level=integer(level)
        if not isinstance(name,str) or not name.strip() or len(name)>200 or level_for(xp)!=level or level>10000:
            raise ValueError('Invalid public-board name/XP/level')
        clean.append([rank,name,xp,level])
    encoded=json.dumps(dict(rows=clean,observed_at=observed,expected_count=expected_count),ensure_ascii=False,separators=(',',':'))
    with connect_sqlite(ledger.path) as db:
        old=db.execute('SELECT parts,rows FROM hybrid_public WHERE guild=? AND batch=? AND part=?',(guild,batch,part)).fetchone()
        if old and old!=(parts,encoded):raise ValueError('Existing capture part differs; start a new batch')
        if db.execute('SELECT 1 FROM hybrid_public WHERE guild=? AND batch=? AND parts!=?',(guild,batch,parts)).fetchone():
            raise ValueError('Capture part count differs')
        db.execute('INSERT OR IGNORE INTO hybrid_public VALUES(?,?,?,?,?,?)',(guild,batch,part,parts,now,encoded))
        stored=db.execute('SELECT part,rows,stamp FROM hybrid_public WHERE guild=? AND batch=? ORDER BY part',(guild,batch)).fetchall()
    if len(stored)!=parts:return dict(batch=batch,received=len(stored),parts=parts,complete=False)
    bodies=[json.loads(body) for _,body,_ in stored]
    if any(b['expected_count']!=expected_count or b['observed_at']!=observed for b in bodies):raise ValueError('Mixed source captures')
    if any(not 0<=now-stamp<=600 for _,_,stamp in stored):raise ValueError('Stored capture expired; start a fresh batch')
    full=[row for body in bodies for row in body['rows']]
    ranks=sorted(r[0] for r in full)
    if len(full)!=expected_count or ranks!=list(range(1,expected_count+1)):raise ValueError('Public ranks missing or duplicated')
    if max(stamp for _,_,stamp in stored)-min(stamp for _,_,stamp in stored)>600:raise ValueError('Capture took too long; refresh public board')
    return dict(batch=batch,received=parts,parts=parts,complete=True,rows=full,observed_at=observed)


def build_manifest(guild,actor,members,roles,public_rows,cutover,batch):
    mapping=role_mapping(roles)
    aliases={}
    for member in members:
        integer(member['id'],positive=True)
        for alias in set(member['aliases']):
            if alias:aliases.setdefault(alias,set()).add(member['id'])
    by_id={m['id']:m for m in members}
    if len(by_id)!=len(members):raise ValueError('Duplicate member IDs')
    selected={};conflicted=set();unresolved=[];unknown=0
    for rank,name,xp,level in public_rows:
        if name=='Unknown':unknown+=1;continue
        candidates=aliases.get(name,set())
        if len(candidates)!=1:unresolved.append(rank);continue
        uid=next(iter(candidates))
        if uid in selected:conflicted.add(uid)
        selected[uid]=dict(xp=xp,level=level,rank=rank,identity='unique_current_alias')
    rows=[];skipped=[];conflicts=[]
    for uid,member in sorted(by_id.items()):
        levels=[level for level,rid in mapping.items() if rid in member['roles']]
        floor=max(levels,default=0)
        exact=selected.get(uid) if uid not in conflicted else None
        if exact and exact['xp']<threshold(floor):conflicts.append(uid);continue
        if exact:
            rows.append(dict(user_id=uid,baseline=exact['xp'],kind='public_board',level=exact['level'],
                rank=exact['rank'],identity=exact['identity'],role_level=floor))
        elif floor:
            rows.append(dict(user_id=uid,baseline=threshold(floor),kind='role_floor',level=floor,role_level=floor))
        else:skipped.append(uid)
    if not rows:raise ValueError('No baseline evidence')
    return dict(schema='hybrid-baseline-v1',guild=integer(guild,positive=True),actor=integer(actor,positive=True),
        cutover=cutover,batch=batch,roster_digest=roster_digest(members),role_mapping={str(k):v for k,v in mapping.items()},
        rows=rows,skipped=skipped,conflicts=conflicts,unresolved_ranks=unresolved,unknown_departed=unknown,
        policy='public board for unique current account aliases; otherwise highest verified role floor',
        weekly='old Amari weekly balances unknown; not fabricated',preview='pre-cutover shadow archived for separate reconciliation',
        historical_bonus='not applied')


def save_plan(ledger,manifest):
    plan=uuid.uuid4().hex[:16]
    with connect_sqlite(ledger.path) as db:
        db.execute('INSERT INTO hybrid_plans VALUES(?,?,?,?,?,?,?,?,?)',(manifest['guild'],plan,manifest['actor'],
            manifest['cutover'],json.dumps(manifest,ensure_ascii=False),digest(manifest),'preview',None,None))
    return plan


def load_plan(ledger,guild,plan):
    with connect_sqlite(ledger.path) as db:
        row=db.execute('SELECT manifest,digest,state FROM hybrid_plans WHERE guild=? AND plan=?',(guild,plan)).fetchone()
    if not row:raise ValueError('Unknown baseline plan')
    data=strict_json(row[0])
    if data.get('schema')!='hybrid-baseline-v1' or digest(data)!=row[1]:raise ValueError('Baseline manifest integrity failed')
    return data,row[2]


def apply_plan(ledger,*,guild,actor,plan,members,roles,backup_path,now):
    """Caller holds role+ledger locks. This changes XP only and leaves mode OFF."""
    data,state=load_plan(ledger,guild,plan)
    if data['actor']!=actor:raise ValueError('Plan belongs to another administrator')
    if state=='applied':return dict(already_applied=True,count=len(data['rows']))
    if state!='preview' or not 0<=now-data['cutover']<=600:raise ValueError('Baseline plan expired')
    if roster_digest(members)!=data['roster_digest'] or {str(k):v for k,v in role_mapping(roles).items()}!=data['role_mapping']:
        raise ValueError('Member identity/role snapshot changed; create a fresh preview')
    if ledger.settings(guild)['mode']!='off':raise ValueError('Pause scoring before baseline commit')
    with connect_sqlite(ledger.path) as db:
        if db.execute("SELECT 1 FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchone():
            raise ValueError('A baseline is already applied; reviewed restore required')
        if db.execute('SELECT 1 FROM migration_manifests WHERE guild=?',(guild,)).fetchone():raise ValueError('Exact migration already applied')
    sha=create_backup(ledger,Path(backup_path))
    with connect_sqlite(ledger.path) as db:
        db.execute('BEGIN IMMEDIATE')
        cfg=json.loads(db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()[0])
        if cfg['mode']!='off':raise ValueError('Scoring resumed during baseline commit')
        if db.execute("SELECT 1 FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchone():raise ValueError('Baseline commit raced')
        for row in data['rows']:
            uid=row['user_id'];base=integer(row['baseline'])
            if db.execute('SELECT 1 FROM adjustments WHERE guild=? AND user=? AND stamp>=?',(guild,uid,data['cutover'])).fetchone():
                raise ValueError('Post-preview manual adjustment needs reconciliation')
            old=db.execute('SELECT * FROM xp WHERE guild=? AND user=?',(guild,uid)).fetchone()
            events=db.execute('SELECT event,user,source,amount,stamp FROM xp_events WHERE guild=? AND user=? AND stamp<?',(guild,uid,data['cutover'])).fetchall()
            periods=db.execute('SELECT week,points FROM periods WHERE guild=? AND user=?',(guild,uid)).fetchall()
            db.execute('INSERT INTO hybrid_shadow VALUES(?,?,?,?,?,?)',(guild,plan,uid,json.dumps(old),json.dumps(events),json.dumps(periods)))
            post=db.execute('SELECT event,source,amount,stamp FROM xp_events WHERE guild=? AND user=? AND stamp>=?',(guild,uid,data['cutover'])).fetchall()
            for _,source,amount,stamp in post:
                if source not in ('text','activity','voice'):raise ValueError('Invalid post-preview event source')
                integer(amount)
            amounts={source:sum(amount for _,s,amount,_ in post if s==source) for source in ('text','activity','voice')}
            total=integer(base+sum(amounts.values()))
            db.execute('INSERT OR REPLACE INTO xp VALUES(?,?,?,?,?,?,?)',(guild,uid,total,amounts['text'],amounts['activity'],amounts['voice'],base))
            db.execute('DELETE FROM xp_events WHERE guild=? AND user=? AND stamp<?',(guild,uid,data['cutover']))
            db.execute('DELETE FROM periods WHERE guild=? AND user=?',(guild,uid))
            from features.community_levels import calendar
            for _,source,amount,stamp in post:
                db.execute('INSERT INTO periods VALUES(?,?,?,?) ON CONFLICT(guild,user,week) DO UPDATE SET points=points+excluded.points',
                    (guild,uid,calendar(stamp)[1],amount))
            db.execute('DELETE FROM role_jobs WHERE guild=? AND user=?',(guild,uid))
            db.execute('DELETE FROM repair_attempts WHERE guild=? AND user=?',(guild,uid))
            db.execute('INSERT OR REPLACE INTO notice_state VALUES(?,?,?)',(guild,uid,level_for(total)))
        cfg['cutover_at']=data['cutover'];cfg['baseline_policy']='hybrid-role-floor-v1';cfg['old_weekly_unknown']=True
        db.execute('UPDATE settings SET value=? WHERE guild=?',(json.dumps(cfg),guild))
        db.execute("UPDATE hybrid_plans SET state='applied',backup_path=?,backup_sha=? WHERE guild=? AND plan=?",(str(backup_path),sha,guild,plan))
    return dict(already_applied=False,count=len(data['rows']),backup_sha=sha)
