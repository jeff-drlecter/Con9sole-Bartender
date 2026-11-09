"""Narrow, journalled Anti-scam remediation; no general permission editor."""
import json
import time
import uuid
import discord
from core.storage_paths import DATA_DIR
from core.sqlite_storage import connect_sqlite

PATH=DATA_DIR/'anti_scam_fix.sqlite3'
# Ordinary game identities from the reviewed snapshot. EA FC-M is deliberately excluded.
ORDINARY={626386851048980480,626404018213879819,698205788250046544,
          1013030946389381120,1146307429039095869,1279061780097925173}
STAFF=('administrator','manage_guild','manage_roles','manage_channels','manage_messages','moderate_members','kick_members','ban_members')


def db():
    conn=connect_sqlite(PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,guild INTEGER,actor INTEGER,stamp REAL,payload TEXT)')
    return conn


def save(plan):
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO plans VALUES(?,?,?,?,?)',(plan['id'],plan['guild'],plan['actor'],plan['stamp'],json.dumps(plan)))


def load(identity,guild,actor):
    with db() as conn:row=conn.execute('SELECT payload FROM plans WHERE id=? AND guild=? AND actor=?',(identity,guild,actor)).fetchone()
    if not row:raise ValueError('找不到屬於你嘅預覽。')
    return json.loads(row[0])


def build(roles,channels,guild,actor,verified):
    plan=dict(id=uuid.uuid4().hex[:12],guild=guild,actor=actor,stamp=time.time(),ops=[],skipped=[])
    safe=set()
    for r in roles:
        if r.id not in ORDINARY|{verified}:continue
        if r.managed or any(getattr(r.permissions,p) for p in STAFF):
            plan['skipped'].append(f'{r.name}：有管理權限或屬整合角色，保留');continue
        safe.add(r.id)
        if r.permissions.mention_everyone:
            after=discord.Permissions(r.permissions.value);after.mention_everyone=False
            plan['ops'].append(dict(kind='role',target=r.id,name=r.name,before=r.permissions.value,after=after.value,state='prepared'))
    everyone=next(r for r in roles if r.id==guild)
    if not everyone.permissions.use_voice_activation:
        after=discord.Permissions(everyone.permissions.value);after.use_voice_activation=True
        plan['ops'].append(dict(kind='role',target=guild,name='@everyone：啟用語音感應',before=everyone.permissions.value,after=after.value,state='prepared'))
    for c in channels:
        for target,ow in c.overwrites.items():
            if target.id not in safe or not (isinstance(target,discord.Role) or getattr(target,'type',None) is discord.Role):continue
            if ow.mention_everyone is not True:continue
            before=ow.pair();ow.mention_everyone=None;after=ow.pair()
            plan['ops'].append(dict(kind='overwrite',channel=c.id,target=target.id,name=f'{c.name}／{target.id}：清除大量 mention 允許',before=[p.value for p in before],after=[p.value for p in after],state='prepared'))
    return plan


async def current(guild,op):
    roles=await guild.fetch_roles()
    role=next((r for r in roles if r.id==op['target']),None)
    if role is None:raise ValueError('角色已刪除，停止。')
    if op['kind']=='role':return role.permissions.value,role,None
    channel=await guild.fetch_channel(op['channel'])
    return [p.value for p in channel.overwrites_for(role).pair()],role,channel


async def execute(guild,plan,authorize,*,restore=False):
    if not restore and time.time()-plan['stamp']>1800:raise ValueError('預覽已超過30分鐘，請重新預覽。')
    if not restore and any(o['state'] in ('applying','uncertain','conflict') for o in plan['ops']):
        raise ValueError('計劃有未核對結果／衝突，禁止繼續套用；先復原或核對。')
    for op in reversed(plan['ops']) if restore else plan['ops']:
        if restore and (not op.get('attempted') or op['state'] not in ('applying','verified','uncertain','conflict')):continue
        if not restore and op['state'] not in ('prepared',):continue
        if not await authorize():raise ValueError('管理員權限已改變，停止。')
        value,role,channel=await current(guild,op)
        expected=op['after'] if restore else op['before']; desired=op['before'] if restore else op['after']
        if value==desired:
            op['state']='restored' if restore else 'verified';save(plan);continue
        if value!=expected:
            op['state']='conflict';save(plan);break
        if not await authorize():raise ValueError('管理員權限已改變，停止。')
        # Write-ahead receipt survives restart/HTTP ambiguity. Never blindly replay.
        op['state']='applying';op['attempted']=True;save(plan)
        try:
            reason=f"Anti-scam Update {plan['id']} actor={plan['actor']} restore={restore}"
            if channel is None:await role.edit(permissions=discord.Permissions(desired),reason=reason)
            else:
                ow=discord.PermissionOverwrite.from_pair(discord.Permissions(desired[0]),discord.Permissions(desired[1]))
                await channel.set_permissions(role,overwrite=None if ow.is_empty() else ow,reason=reason)
            observed,_,_=await current(guild,op)
            op['state']=('restored' if restore else 'verified') if observed==desired else 'uncertain'
        except Exception:
            op['state']='uncertain';save(plan);raise
        save(plan)
        if op['state']=='uncertain':break
    return plan


def summary(plan):
    from collections import Counter
    counts=Counter(op['state'] for op in plan['ops'])
    return f"計劃 {plan['id']}｜{len(plan['ops'])} 項｜"+'、'.join(f'{k} {v}' for k,v in counts.items())
