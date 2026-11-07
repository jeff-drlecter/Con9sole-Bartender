"""Historical base-XP compensation. Caller holds role/ledger locks and scoring OFF.

The explicit base-only policy is required: retained history cannot recover deleted
messages or historical Booster membership. This never changes weekly XP or CDs.
"""
import json
from pathlib import Path
from core.sqlite_storage import connect_sqlite
from features.community_levels import level_for
from features.level_migration import create_backup,digest,integer


def prepare(ledger,guild,actor,job,start,replay,current_users):
    if replay.get('algorithm')!='net-shared-cooldown-v1' or start!=1786982400:
        raise ValueError('Unsupported historical scope/algorithm')
    policy=replay['policy']
    if policy.get('cooldown')!=60:raise ValueError('Historical compensation requires the verified original 60-second cooldown')
    if not start<policy['cutoff'] or not isinstance(replay.get('evidence_digest'),str) or len(replay['evidence_digest'])!=64:
        raise ValueError('Missing historical evidence digest or invalid time range')
    with connect_sqlite(ledger.path) as db:
        rows=db.execute("SELECT plan,manifest FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchall()
    if len(rows)!=1:raise ValueError('Exactly one applied baseline is required')
    plan,body=rows[0];baseline=json.loads(body)
    if policy['baseline']!=plan or policy['cutoff']!=baseline['cutover']:
        raise ValueError('Historical replay must reach the applied baseline cutoff')
    scope={r['user_id'] for r in baseline['rows']};users=[]
    for user,row in sorted(replay['users'].items(),key=lambda item:int(item[0])):
        uid=integer(user,positive=True);amount=integer(row['base_xp'])
        if uid not in scope or uid not in current_users or uid not in policy['users']:
            raise ValueError('Historical member outside current verified scope')
        if amount!=integer(row['combined'])-integer(row['text_only']) or amount>integer(row['game_accepted']):
            raise ValueError('Invalid net historical compensation')
        if amount:users.append(dict(user=uid,amount=amount))
    if not users:raise ValueError('No positive historical compensation')
    return dict(schema='historical-base-v1',guild=guild,actor=actor,job=job,baseline=plan,start=start,
        cutoff=policy['cutoff'],replay_digest=digest(replay),users=users,
        policy='retained-history net shared-CD base XP; deleted messages and historical Booster multipliers not inferred')


def apply(ledger,manifest,backup_path,now,*,actor,current_users,accept_base_only=False):
    if not accept_base_only:raise ValueError('Explicit base-only historical policy acceptance required')
    if manifest.get('schema')!='historical-base-v1' or manifest['actor']!=actor:raise ValueError('Historical plan actor/schema mismatch')
    guild=integer(manifest['guild'],positive=True);sha=digest(manifest)
    ids=[integer(row['user'],positive=True) for row in manifest['users']]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(current_users):raise ValueError('Duplicate or departed historical member')
    for row in manifest['users']:integer(row['amount'],positive=True)
    cfg=ledger.settings(guild);old=cfg.get('historical_bonus')
    if old:
        if old['digest']!=sha:raise ValueError('Historical compensation already applied; reviewed restore required')
        return dict(already_applied=True,count=len(ids))
    if cfg['mode']!='off':raise ValueError('Pause scoring before compensation')
    def validate(db):
        rows=db.execute("SELECT plan,manifest FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchall()
        if len(rows)!=1 or rows[0][0]!=manifest['baseline']:raise ValueError('Applied baseline changed')
        baseline=json.loads(rows[0][1])
        if baseline['cutover']!=manifest['cutoff'] or manifest['start']!=1786982400:raise ValueError('Historical time scope changed')
        if not set(ids)<={r['user_id'] for r in baseline['rows']}:raise ValueError('Historical member outside baseline')
    with connect_sqlite(ledger.path) as db:validate(db)
    backup_sha=create_backup(ledger,Path(backup_path))
    with connect_sqlite(ledger.path) as db:
        db.execute('BEGIN IMMEDIATE');validate(db)
        cfg=json.loads(db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()[0])
        if cfg['mode']!='off' or cfg.get('historical_bonus'):raise ValueError('Compensation state changed')
        for row in manifest['users']:
            uid=row['user'];amount=row['amount']
            prior=db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,uid)).fetchone()
            if prior is None:raise ValueError('Historical profile missing')
            total=integer(prior[0]+amount)
            db.execute('UPDATE xp SET total=? WHERE guild=? AND user=?',(total,guild,uid))
            db.execute('INSERT INTO adjustments(guild,user,actor,delta,reason,stamp) VALUES(?,?,?,?,?,?)',
                (guild,uid,actor,amount,'historical-base:'+sha[:16],now))
            db.execute('INSERT OR REPLACE INTO notice_state VALUES(?,?,?)',(guild,uid,level_for(total)))
            db.execute('DELETE FROM role_jobs WHERE guild=? AND user=?',(guild,uid))
            db.execute('DELETE FROM repair_attempts WHERE guild=? AND user=?',(guild,uid))
        cfg['historical_bonus']=dict(digest=sha,manifest=manifest,stamp=now,backup_path=str(backup_path),backup_sha=backup_sha)
        db.execute('UPDATE settings SET value=? WHERE guild=?',(json.dumps(cfg,sort_keys=True),guild))
    return dict(already_applied=False,count=len(ids),backup_sha=backup_sha)
