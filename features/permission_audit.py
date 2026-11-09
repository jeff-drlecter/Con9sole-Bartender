"""Read-only Discord configuration export and conservative policy findings."""
from datetime import datetime, timezone
import io
import json
import zipfile
import discord

POWER = ('administrator', 'manage_guild', 'manage_roles', 'manage_channels',
         'manage_webhooks', 'ban_members', 'kick_members', 'moderate_members', 'mention_everyone')


def permissions(value):
    return {'value': str(value), 'enabled': [name for name, enabled in discord.Permissions(value) if enabled]}


def overwrite_rows(channel):
    rows=[]
    for target, overwrite in channel.overwrites.items():
        allow, deny=overwrite.pair()
        role=isinstance(target,discord.Role) or getattr(target,'type',None) is discord.Role
        rows.append({'id':str(target.id),'type':'role' if role else 'member',
                     'allow':permissions(allow.value),'deny':permissions(deny.value)})
    return sorted(rows,key=lambda r:(r['type'],int(r['id'])))


def role_permissions(roles, channel, guild_id, role_ids):
    """Raw Discord overwrite calculation for a hypothetical role combination.

    No owner, member overwrite, timeout or thread membership is implied.
    """
    ids={str(guild_id), *map(str,role_ids)}
    value=0
    for role in roles:
        if role['id'] in ids:value |= int(role['permissions']['value'])
    if discord.Permissions(value).administrator:return discord.Permissions.all()
    overwrites=channel['overwrites']
    for row in overwrites:
        if row['type']=='role' and row['id']==str(guild_id):
            value=(value & ~int(row['deny']['value'])) | int(row['allow']['value'])
    allow=deny=0
    for row in overwrites:
        if row['type']=='role' and row['id'] in ids and row['id']!=str(guild_id):
            allow |= int(row['allow']['value']);deny |= int(row['deny']['value'])
    return discord.Permissions((value & ~deny) | allow)


def analyze(snapshot, verified_id):
    findings=[]
    def add(code, severity, target, detail):
        findings.append(dict(code=code,severity=severity,target=str(target),detail=detail))
    roles=snapshot['roles'];guild=snapshot['guild']['id']
    for role in roles:
        powers=[p for p in POWER if getattr(discord.Permissions(int(role['permissions']['value'])),p)]
        if powers:add('PRIVILEGED_ROLE','review',role['id'],f"{role['name']}：{', '.join(powers)}；核對用途，唔代表漏洞。")
    verified=next((r for r in roles if r['id']==str(verified_id)),None)
    if not verified:add('VERIFIED_MISSING','warning',verified_id,'設定嘅 Verified 角色不存在。')
    by_id={c['id']:c for c in snapshot['channels']}
    for channel in snapshot['channels']:
        category=by_id.get(channel['category_id'])
        if category and channel['overwrites']!=category['overwrites']:
            add('UNSYNCED_CHANNEL','review',channel['id'],f"{channel['name']}：權限未跟分類同步；可能係刻意例外。")
        for ow in channel['overwrites']:
            if ow['type']=='member':add('MEMBER_OVERRIDE','review',channel['id'],f"個人覆寫：{ow['id']}；需核對用途。")
        base=role_permissions(roles,channel,guild,[])
        if channel['type'] in ('voice','stage_voice') and base.view_channel and base.connect and base.speak and not base.use_voice_activation:
            add('UNVERIFIED_PTT','policy',channel['id'],f"{channel['name']}：只持 @everyone 嘅情境仍需按鍵發話，與 Anti-scam Update 方向不一致。")
        for field in ('manage_channels','manage_roles','manage_webhooks','mention_everyone'):
            if getattr(base,field):add('EVERYONE_POWER','warning',channel['id'],f'@everyone 情境取得 {field}。')
    onboarding=snapshot['onboarding']
    if onboarding['status']=='ok':
        privileged={r['id'] for r in roles if any(getattr(discord.Permissions(int(r['permissions']['value'])),p) for p in POWER)}
        for prompt in onboarding['data']['prompts']:
            for option in prompt['options']:
                for rid in map(str,option['role_ids']):
                    if rid in privileged or rid==str(verified_id):
                        add('ONBOARDING_SENSITIVE_ROLE','warning',rid,f"選項 {option['title']} 會派發高權限／Verified 角色；需核對。")
    return findings


async def collect(guild, verified_id):
    roles=await guild.fetch_roles()
    channels=await guild.fetch_channels()
    snapshot={'schema_version':1,'update':'Anti-scam Update',
        'captured_at':datetime.now(timezone.utc).isoformat(),
        'guild':{'id':str(guild.id),'name':guild.name,'owner_id':str(guild.owner_id),
                 'verification_level':str(guild.verification_level),'features':list(guild.features),
                 'mfa_level':str(guild.mfa_level),'explicit_content_filter':str(guild.explicit_content_filter),
                 'cached_member_count':len(guild.members),'reported_member_count':guild.member_count},
        'coverage':{'roles':'REST fetch','channels':'REST fetch; categories included',
                    'members':'No member list exported; no per-member effective permission claims',
                    'threads':'Not enumerated; archived/private threads and membership require separate audit',
                    'limits':'Non-atomic snapshot. No messages, DMs, invites, webhooks tokens or Bot runtime policies exported. Role scenarios exclude member overrides/timeouts/owner and implicit channel permission dependencies.'},
        'roles':[{'id':str(r.id),'name':r.name,'position':r.position,'managed':r.managed,
                  'hoist':r.hoist,'mentionable':r.mentionable,'colour':r.colour.value,
                  'permissions':permissions(r.permissions.value)} for r in sorted(roles,key=lambda r:r.id)],
        'channels':[]}
    for c in sorted(channels,key=lambda c:c.id):
        row={'id':str(c.id),'name':c.name,'type':str(c.type),'position':c.position,
             'category_id':str(c.category_id) if c.category_id else None,'overwrites':overwrite_rows(c)}
        for attr in ('topic','nsfw','slowmode_delay','bitrate','user_limit','rtc_region','video_quality_mode',
                     'default_auto_archive_duration','default_thread_slowmode_delay','default_sort_order','default_layout'):
            if hasattr(c,attr):
                v=getattr(c,attr);row[attr]=getattr(v,'value',v)
        if hasattr(c,'available_tags'):
            row['available_tags']=[{'id':str(t.id),'name':t.name,'moderated':t.moderated,'emoji':str(t.emoji) if t.emoji else None} for t in c.available_tags]
        if hasattr(c,'default_reaction_emoji'):row['default_reaction_emoji']=str(c.default_reaction_emoji) if c.default_reaction_emoji else None
        snapshot['channels'].append(row)
    for name, fetch in (('onboarding',getattr(guild,'onboarding',None)),('automod',getattr(guild,'fetch_automod_rules',None))):
        try:
            if fetch is None:
                snapshot[name]={'status':'unsupported'};continue
            value=await fetch()
            if name=='onboarding':
                data={'enabled':value.enabled,'mode':value.mode.value,'default_channel_ids':sorted(map(str,value.default_channel_ids)),
                      'prompts':[{**p.to_dict(id=p.id),'id':str(p.id),'options':[{**option.to_dict(),'id':str(option.id),'role_ids':sorted(map(str,option.role_ids)),'channel_ids':sorted(map(str,option.channel_ids))} for option in p.options]} for p in value.prompts]}
            else:data=[r.to_dict() for r in value]
            snapshot[name]={'status':'ok','data':data}
        except discord.HTTPException as exc:
            snapshot[name]={'status':'unavailable','http_status':exc.status}
    snapshot['findings']=analyze(snapshot,verified_id)
    snapshot['role_scenarios']={}
    for label, ids in (('everyone_only',[]),('everyone_plus_verified',[verified_id])):
        if label.endswith('verified') and not any(r['id']==str(verified_id) for r in snapshot['roles']):continue
        snapshot['role_scenarios'][label]={c['id']:permissions(role_permissions(snapshot['roles'],c,guild.id,ids).value) for c in snapshot['channels']}
    return snapshot


def report(snapshot):
    lines=['# Anti-scam Update — Permission Audit',snapshot['captured_at'],
           f"Roles: {len(snapshot['roles'])} | Channels/categories: {len(snapshot['channels'])}",
           '唯讀設定快照；review 係待核對項目，唔代表已確認漏洞。',
           f"Onboarding: {snapshot['onboarding']['status']} | AutoMod: {snapshot['automod']['status']}",
           '未列舉 threads／封存 threads；未逐人驗算；非原子快照。角色情境係原始權限位元，未套個人覆寫、timeout 或隱含權限限制。',
           '## Findings']
    lines.extend(f"- [{r['severity']}] {r['code']} | {r['target']} | {r['detail']}" for r in snapshot['findings'])
    if not snapshot['findings']:lines.append('自動規則未發現項目；唔等於完整安全驗收。')
    return '\n'.join(lines)


def archive(snapshot):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('permission-audit.json',json.dumps(snapshot,ensure_ascii=False,indent=2))
        z.writestr('permission-audit.md',report(snapshot))
    output.seek(0)
    return output
