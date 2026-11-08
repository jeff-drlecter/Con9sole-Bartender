"""Evidence-gated, atomic transition from preview to active level roles."""
import json
import re
from core.sqlite_storage import connect_sqlite
from features.community_levels import REWARD_NAMES,level_for
from features.level_migration import digest


def readiness(ledger,guild,cfg,now):
    expected={str(k):int(v) for k,v in cfg['rewards'].items()}
    if set(expected)!={str(k) for k in REWARD_NAMES}:raise ValueError('All ten reward mappings are required')
    drill=cfg.get('role_drill',{})
    if not (drill.get('state')=='restored' and drill.get('remove_observed') and drill.get('remove_succeeded') and drill.get('mapping')==expected):
        raise ValueError('A verified actual role removal/restore drill is required')
    if (cfg['text_cooldown'],cfg['activity_cooldown'],cfg['activity_daily_cap'],cfg['voice_interval'],cfg['voice_xp'])!=(60,60,0,300,25):
        raise ValueError('Rates differ from the verified original policy')
    with connect_sqlite(ledger.path) as db:
        plans=db.execute("SELECT plan FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchall()
        events=db.execute("SELECT event,user,stamp FROM xp_events WHERE guild=? AND source='voice' AND amount=? AND stamp>=? ORDER BY stamp",(guild,cfg['voice_xp'],max(now-86400,cfg.get('cutover_at',0)))).fetchall()
    if len(plans)!=1 or cfg.get('historical_bonus',{}).get('manifest',{}).get('baseline')!=plans[0][0]:
        raise ValueError('Verified baseline and historical compensation must be complete')
    by_channel={};witness=None
    for event,user,stamp in events:
        match=re.fullmatch(r'v:(\d+):(\d+):(\d+)',event)
        if not match or int(match[2])!=user:continue
        cid=int(match[1]);recent=[(uid,t) for uid,t in by_channel.get(cid,[]) if stamp-t<=30]
        recent.append((user,stamp));by_channel[cid]=recent
        if len({uid for uid,_ in recent})>=2:witness=dict(channel=cid,stamp=stamp,users=sorted({uid for uid,_ in recent}))
    if not witness:raise ValueError('Recent real multi-member voice awards must be verified')
    return dict(baseline=plans[0][0],role_drill=drill['id'],voice=witness)


def role_plan(ledger,guild,rewards,members):
    mapping={int(level):int(rid) for level,rid in rewards.items()};inverse={rid:level for level,rid in mapping.items()}
    with connect_sqlite(ledger.path) as db:
        baseline=db.execute("SELECT manifest FROM hybrid_plans WHERE guild=? AND state='applied'",(guild,)).fetchall()
        if len(baseline)!=1:raise ValueError('One verified baseline is required for the role plan')
        held=set(json.loads(baseline[0][0]).get('conflicts',[]))
        profiles=dict(db.execute('SELECT user,total FROM xp WHERE guild=?',(guild,)))
    rows=[]
    for member in sorted(members,key=lambda row:row['user']):
        uid=member['user'];current=set(member['roles']);total=profiles.get(uid)
        reason=None
        if uid in held:reason='baseline_conflict'
        elif total is None and current:reason='role_without_profile'
        elif total is not None and any(inverse.get(rid,100000)>level_for(total) for rid in current):reason='protected_role_downgrade'
        if reason:rows.append(dict(user=uid,kind='hold',reason=reason,current=sorted(current),target=sorted(current),add=[],remove=[]));continue
        if total is None:rows.append(dict(user=uid,kind='untouched',current=[],target=[],add=[],remove=[]));continue
        due=[level for level in mapping if level<=level_for(total)]
        target={mapping[max(due)]} if due else set()
        add=sorted(target-current);remove=sorted(current-target)
        rows.append(dict(user=uid,kind='change' if add or remove else 'keep',current=sorted(current),target=sorted(target),add=add,remove=remove))
    body=dict(mapping={str(k):v for k,v in mapping.items()},rows=rows)
    return {**body,'digest':digest(body),'counts':{kind:sum(r['kind']==kind for r in rows) for kind in ('change','keep','untouched','hold')}}


def commit(ledger,guild,changes,members,evidence,now,preview_digest):
    """Caller holds role+ledger locks, verified Discord state and a durable backup."""
    ids=[row['user'] for row in members]
    if len(ids)!=len(set(ids)) or any(type(uid) is not int or uid<=0 for uid in ids):raise ValueError('Invalid activation member scope')
    with connect_sqlite(ledger.path) as db:
        db.execute('BEGIN IMMEDIATE')
        cfg=json.loads(db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()[0])
        if cfg['mode']=='active':raise ValueError('Already active; do not repeat cutover')
        fresh=readiness(ledger,guild,cfg,now)
        if fresh!=evidence:raise ValueError('Activation evidence changed; recheck before takeover')
        plan=role_plan(ledger,guild,cfg['rewards'],members)
        if plan['counts']['hold'] or plan['digest']!=preview_digest:raise ValueError('Role changes are held or differ from the reviewed preview')
        intent=cfg.get('activation_intent')
        if not intent or intent['members']!=members or not changes.get('backup_sha') or not changes.get('backup_path'):
            raise ValueError('Verified activation snapshot/backup required')
        cfg.update(mode='active',announcement_channel=changes['announcement_channel'],announcement_ping=changes['announcement_ping'])
        cfg['activation']={**intent,**changes,'evidence':evidence,'role_plan':plan,'state':'active'}
        cfg.pop('activation_intent',None)
        queued={r['user'] for r in plan['rows'] if r['kind'] in ('change','keep')}
        for uid in sorted(queued):
            row=db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,uid)).fetchone()
            if row is None:raise ValueError('Reviewed profile disappeared during activation')
            total=row[0]
            db.execute('INSERT INTO role_jobs VALUES(?,?,?,?) ON CONFLICT(guild,user) DO UPDATE SET total=excluded.total,old_total=excluded.old_total',(guild,uid,total,total))
            db.execute('INSERT INTO notice_state VALUES(?,?,?) ON CONFLICT(guild,user) DO UPDATE SET level=max(notice_state.level,excluded.level)',(guild,uid,level_for(total)))
        db.execute('UPDATE settings SET value=? WHERE guild=?',(json.dumps(cfg,sort_keys=True),guild))
    return cfg


def pending_count(ledger,guild):
    with connect_sqlite(ledger.path) as db:
        return db.execute('SELECT count(*) FROM role_jobs WHERE guild=?',(guild,)).fetchone()[0]
