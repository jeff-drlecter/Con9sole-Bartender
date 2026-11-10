"""Enable only the approved alert-only rules; journal unknown POST outcomes."""
import json
import time
import discord
from core.storage_paths import DATA_DIR
from core.sqlite_storage import connect_sqlite
from features.anti_scam_rules import ALERT_CHANNEL, LINK_PATTERN
from features.permission_audit import overwrite_rows,permissions,role_permissions

PATH=DATA_DIR/'anti_scam_monitor.sqlite3'
STAFF={626379227473903632,1279071042249162856}


def receipt(guild,name,value=None):
    with connect_sqlite(PATH) as db:
        db.execute('CREATE TABLE IF NOT EXISTS monitor(guild INTEGER,name TEXT,value TEXT,PRIMARY KEY(guild,name))')
        if value is not None:db.execute('INSERT OR REPLACE INTO monitor VALUES(?,?,?)',(guild,name,json.dumps(value)))
        row=db.execute('SELECT value FROM monitor WHERE guild=? AND name=?',(guild,name)).fetchone()
    return json.loads(row[0]) if row else None


def desired(verified):
    return [dict(name='Anti-scam | Unverified links',trigger_type=1,event_type=1,enabled=True,
        trigger_metadata=dict(regex_patterns=[LINK_PATTERN]),exempt_roles=[str(verified)],exempt_channels=[],
        actions=[dict(type=2,metadata=dict(channel_id=str(ALERT_CHANNEL)))]),
        dict(name='Anti-scam | Suspected spam',trigger_type=3,event_type=1,enabled=True,
        trigger_metadata={},exempt_roles=[],exempt_channels=[],actions=[dict(type=2,metadata=dict(channel_id=str(ALERT_CHANNEL)))])]


def matches(rule,payload,*,enabled=True):
    raw=rule.to_dict()
    if any(raw.get(k)!=payload[k] for k in ('name','event_type','trigger_type')):return False
    if raw['enabled']!=enabled:return False
    if sorted(map(str,raw['exempt_roles']))!=sorted(payload['exempt_roles']) or raw['exempt_channels']!=[]:return False
    if raw['actions']!=payload['actions']:return False
    metadata=raw.get('trigger_metadata') or {}
    return metadata.get('regex_patterns',[])==payload.get('trigger_metadata',{}).get('regex_patterns',[]) and not any(metadata.get(k) for k in ('keyword_filter','allow_list','presets'))


def private_alert(guild_id,roles,channel):
    if channel is None or not isinstance(channel,discord.TextChannel):raise ValueError('管理員提示頻道不存在或唔係文字頻道。')
    rows=[dict(id=str(r.id),permissions=permissions(r.permissions.value)) for r in roles]
    c=dict(overwrites=overwrite_rows(channel))
    for r in roles:
        if r.id in STAFF or (r.managed and r.is_bot_managed()) or r.permissions.administrator or r.permissions.manage_guild:continue
        if role_permissions(rows,c,guild_id,[r.id]).view_channel:raise ValueError('提示頻道對非 staff 角色開放，停止。')
    for target,ow in channel.overwrites.items():
        if not (isinstance(target,discord.Role) or getattr(target,'type',None) is discord.Role) and ow.view_channel is True:
            raise ValueError('提示頻道有個人成員 Allow，請先核對私隱。')


async def run(guild,verified,authorize,mode='status',*,actor=0):
    rows=[]
    roles=await guild.fetch_roles()
    rules=await guild.fetch_automod_rules()
    if mode=='enable':
        if not any(r.id==verified for r in roles):raise ValueError('Verified 角色不存在。')
        channel=await guild.fetch_channel(ALERT_CHANNEL)
        private_alert(guild.id,roles,channel)
    for payload in desired(verified):
        name=payload['name'];record=receipt(guild.id,name)
        found=[r for r in rules if r.name==name]
        if len(found)>1:raise ValueError('同名規則多於一條，停止並人工核對。')
        rule=found[0] if found else None
        if rule is not None:
            if not record or rule.creator_id!=guild.me.id or (record.get('id') and record['id']!=rule.id):
                raise ValueError('同名規則唔屬於本工具，停止。')
            if not matches(rule,payload,enabled=rule.enabled):raise ValueError('規則已被修改，停止，唔覆蓋。')
            if mode=='disable' and rule.enabled:
                if not await authorize():raise ValueError('管理員權限已改變。')
                rule=await rule.edit(enabled=False,reason=f'Anti-scam Update: disable owned alert-only monitor actor={actor}')
            elif mode=='enable' and not rule.enabled:
                if not await authorize():raise ValueError('管理員權限已改變。')
                rule=await rule.edit(enabled=True,reason=f'Anti-scam Update: enable owned alert-only monitor actor={actor}')
            if mode!='status':
                verified_rules=await guild.fetch_automod_rules()
                rule=next((r for r in verified_rules if r.id==rule.id),None)
                if rule is None or not matches(rule,payload,enabled=mode=='enable'):raise ValueError('規則重讀驗證失敗，停止。')
                receipt(guild.id,name,dict(state='enabled' if rule.enabled else 'disabled',id=rule.id,stamp=time.time(),actor=actor))
            rows.append(f"{name}：{'已啟用，只提示' if rule.enabled else '已停用'}")
            continue
        if record:raise ValueError('已有建立紀錄但搵唔到規則；結果需人工核對，唔自動重建。')
        if mode!='enable':rows.append(f'{name}：未建立');continue
        if payload['trigger_type']==3 and any(r.trigger.type.value==3 for r in rules):
            rows.append(f'{name}：已有其他 spam 規則，保留並略過');continue
        if payload['trigger_type']==1 and sum(r.trigger.type.value==1 for r in rules)>=6:raise ValueError('Keyword 規則名額已滿。')
        if not await authorize():raise ValueError('管理員權限已改變。')
        receipt(guild.id,name,dict(state='uncertain',stamp=time.time(),actor=actor))
        trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType(payload['trigger_type']),regex_patterns=[LINK_PATTERN]) if payload['trigger_type']==1 else discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam)
        rule=await guild.create_automod_rule(name=name,event_type=discord.AutoModRuleEventType.message_send,
            trigger=trigger,actions=[discord.AutoModRuleAction(channel_id=ALERT_CHANNEL)],enabled=True,
            exempt_roles=[discord.Object(int(r)) for r in payload['exempt_roles']],exempt_channels=[],reason=f'Anti-scam Update: approved alert-only monitoring actor={actor}')
        receipt(guild.id,name,dict(state='created',id=rule.id,stamp=time.time(),actor=actor))
        rules=await guild.fetch_automod_rules()
        observed=next((r for r in rules if r.id==rule.id),None)
        if observed is None or not matches(observed,payload):raise ValueError('建立結果未能重讀確認；停止，請查狀態。')
        receipt(guild.id,name,dict(state='enabled',id=rule.id,stamp=time.time(),actor=actor))
        rows.append(f'{name}：已建立、啟用及重讀驗證，只提示')
    return rows
