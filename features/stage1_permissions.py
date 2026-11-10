"""Stage 1: narrow attachment/embed gate, preserving all participation bits.

No bot/staff privilege changes are inferred from role names. Such changes remain
explicit blockers until a service-specific permission inventory is approved.
"""
import asyncio
import copy
import hashlib
import json
import time
import uuid
import discord
from features.permission_audit import role_permissions
from features.verified_access_preview import STAFF_IDS, STAFF_POWERS

CAP_MASK = discord.Permissions(attach_files=True, embed_links=True).value
VIP_CHANNELS = {'1380168909671370824','1380173835474571406','1380176573189197922','1380176879562002462'}


def fingerprint(snapshot):
    payload = {'service_members':snapshot.get('service_members',{}), 'staff_members':snapshot.get('staff_members',{}), 'roles': [(r['id'],r['permissions']['value'],r.get('managed'),r.get('bot_managed')) for r in snapshot['roles']],
               'channels': [(c['id'],c['type'],c['category_id'],c['overwrites']) for c in snapshot['channels']]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def privileged(role):
    perms = discord.Permissions(int(role['permissions']['value']))
    return role['id'] in STAFF_IDS or any(getattr(perms, p) for p in STAFF_POWERS)


def build(snapshot, actor, verified):
    gid = snapshot['guild']['id']; vid = str(verified)
    roles = {r['id']:r for r in snapshot['roles']}
    channels = {c['id']:c for c in snapshot['channels']}
    if vid not in roles or roles[vid].get('managed') or privileged(roles[vid]):
        raise ValueError('Verified 角色缺少或已具有管理權限。')
    if any(c not in channels for c in VIP_CHANNELS):
        raise ValueError('VIP 例外頻道已變更，未建立可套用計劃。')
    vip_categories = {channels[c]['category_id'] for c in VIP_CHANNELS}
    if len(vip_categories) != 1 or None in vip_categories:
        raise ValueError('VIP 例外分類已變更。')
    for cid in VIP_CHANNELS:
        row = next((o for o in channels[cid]['overwrites'] if o['type']=='role' and o['id']==vid), None)
        if row is None or int(row['deny']['value']) & CAP_MASK != CAP_MASK:
            raise ValueError('VIP 原有明確限制已變更，停止。')
    ordinary = {r['id'] for r in roles.values() if r['id'] not in {gid,vid} and not r.get('bot_managed') and not privileged(r)}
    plan = dict(id=uuid.uuid4().hex[:12], scope='stage1_caps', guild=int(gid), actor=actor,
                stamp=time.time(), fingerprint=fingerprint(snapshot), ops=[], skipped=[],
                ordinary=sorted(ordinary), verified=int(vid), accepted_exceptions=[], blockers=[])
    for cid in sorted(VIP_CHANNELS):
        plan['accepted_exceptions'].append({'channel':cid,'name':channels[cid]['name'],'decision':'保留 VIP／Booster 專區原有規則；Verified 不取得 VIP 可見性或權限。'})
    # Parent changes propagate to exactly synced children. Do not write those twice.
    for c in sorted(channels.values(), key=lambda c:(c['type']!='category',int(c['id']))):
        if c['id'] in VIP_CHANNELS or c['id'] in vip_categories:
            continue
        if c['category_id'] in vip_categories:
            raise ValueError('VIP 分類出現未覆核的新頻道。')
        parent = channels.get(c['category_id'])
        if parent and c['overwrites']==parent['overwrites']:
            continue
        rows = {o['id']:o for o in c['overwrites'] if o['type']=='role'}
        member_grants = [o['id'] for o in c['overwrites'] if o['type']=='member' and int(o['allow']['value']) & CAP_MASK]
        if member_grants:
            raise ValueError('存在個人附件／預覽允許，需先覆核；未建立計劃。')
        # Only retain Verified capabilities that were available with some eligible
        # identity before. This never changes visibility/send/connect/speak bits.
        prior_caps = 0
        for rid in [None,*sorted(ordinary)]:
            ids = [vid] if rid is None else [vid,rid]
            prior_caps |= role_permissions(list(roles.values()),c,gid,ids).value & CAP_MASK
        service_roles = {r['id'] for r in roles.values()
                         if r['id'] not in {gid,vid} and (r.get('bot_managed') or privileged(r))
                         and not discord.Permissions(int(r['permissions']['value'])).administrator}
        for rid in [gid,vid,*sorted(ordinary & rows.keys()),*sorted(service_roles)]:
            row = rows.get(rid)
            before = [int(row['allow']['value']),int(row['deny']['value'])] if row else [0,0]
            allow,deny = before
            if rid == gid:
                after = [allow & ~CAP_MASK, deny | CAP_MASK]
            elif rid == vid:
                # Existing explicit denials are intentional, never override them.
                after = [allow | (prior_caps & ~deny),deny]
            elif rid in service_roles:
                ids = snapshot.get('service_members',{}).get(rid,[rid])
                prior = role_permissions(list(roles.values()),c,gid,ids).value & CAP_MASK
                if not roles[rid].get('bot_managed'):
                    for member_ids in snapshot.get('staff_members',{}).values():
                        if rid in member_ids:
                            prior |= role_permissions(list(roles.values()),c,gid,member_ids).value & CAP_MASK
                after = [allow | (prior & ~deny),deny]
            else:
                after = [allow & ~CAP_MASK,deny]
            if before != after:
                plan['ops'].append(dict(kind='overwrite',channel=int(c['id']),target=int(rid),
                    name=f"{c['name']}／{roles[rid]['name']}", before=before,after=after,state='prepared',
                    category=c['category_id'],channel_type=c['type'], preserve_service=rid in service_roles))
    for role in roles.values():
        if role.get('bot_managed') and discord.Permissions(int(role['permissions']['value'])).administrator:
            plan['blockers'].append(f"Bot {role['name']} ({role['id']}) 仍有 Administrator；需按實際功能及頻道覆寫訂明最小權限，未自動降權。")
    simulated = simulate(snapshot,plan)
    service_losses = service_capability_losses(snapshot,simulated)
    if service_losses:
        raise ValueError('模擬發現 Bot／管理角色能力下降，停止：'+str(service_losses[:5]))
    plan['service_capability_losses'] = service_losses
    plan['verification'] = verify(simulated,verified)
    if plan['verification']['unexpected_unverified_caps']:
        raise ValueError('模擬仍有非例外附件／預覽允許，停止。')
    return plan


def simulate(snapshot, plan):
    result = copy.deepcopy(snapshot)
    channels = {c['id']:c for c in result['channels']}
    original = {c['id']:c for c in snapshot['channels']}
    for op in plan['ops']:
        channel = channels[str(op['channel'])]
        targets = [channel]
        if channel['type']=='category':
            targets += [c for c in result['channels'] if c['category_id']==channel['id'] and original[c['id']]['overwrites']==original[channel['id']]['overwrites']]
        for c in targets:
            rows=c['overwrites'];rid=str(op['target'])
            row=next((r for r in rows if r['type']=='role' and r['id']==rid),None)
            if row is None:
                row=dict(id=rid,type='role');rows.append(row)
            from features.permission_audit import permissions
            row['allow']=permissions(op['after'][0]);row['deny']=permissions(op['after'][1])
    return result


def service_capability_losses(before,after):
    gid=before['guild']['id'];after_channels={c['id']:c for c in after['channels']}
    services={r['id']:[r['id']] for r in before['roles'] if r.get('bot_managed') or privileged(r)}
    services.update(before.get('service_members',{}))
    services.update({'member:'+mid:ids for mid,ids in before.get('staff_members',{}).items()})
    losses=[]
    for c in before['channels']:
        for rid,ids in services.items():
            old=role_permissions(before['roles'],c,gid,ids).value & CAP_MASK
            new=role_permissions(after['roles'],after_channels[c['id']],gid,ids).value & CAP_MASK
            if old & ~new:
                losses.append({'channel':c['id'],'role':rid,'lost':old & ~new})
    return losses


def verify(snapshot, verified):
    gid=snapshot['guild']['id']; vid=str(verified)
    roles=snapshot['roles'];channels=snapshot['channels']
    ordinary=[r['id'] for r in roles if r['id'] not in {gid,vid} and not r.get('bot_managed') and not privileged(r)]
    unexpected=[]
    for c in channels:
        if c['type']=='category' or c['id'] in VIP_CHANNELS:continue
        # Conservative subset proof: omit ordinary role denies entirely. A
        # deny from one role must not hide a grant available without that role.
        base = 0
        for r in roles:
            if r['id'] in {gid,*ordinary}:
                base |= int(r['permissions']['value'])
        everyone = next((o for o in c['overwrites'] if o['type']=='role' and o['id']==gid),None)
        if everyone:
            base = (base & ~int(everyone['deny']['value'])) | int(everyone['allow']['value'])
        for o in c['overwrites']:
            if o['type']=='role' and o['id'] in ordinary:
                base |= int(o['allow']['value'])
        if discord.Permissions(base).administrator or base & CAP_MASK:
            unexpected.append(c['id'])
        if any(o['type']=='member' and int(o['allow']['value']) & CAP_MASK for o in c['overwrites']):
            unexpected.append(c['id'])
    return dict(unexpected_unverified_caps=sorted(set(unexpected)),ordinary_roles=len(ordinary),
                channels_checked=sum(c['type']!='category' and c['id'] not in VIP_CHANNELS for c in channels),
                limits='Role capability proof only. Actual member screening/timeouts/thread membership and Bot functional smoke tests remain live acceptance checks.')


async def execute(guild,plan,authorize,*,restore=False):
    from features import anti_scam_fix as journal
    if plan.get('scope')!='stage1_caps':raise ValueError('非第 1 階段計劃。')
    def validate(op,role,channel):
        if op['kind']!='overwrite' or channel is None or str(channel.id) in VIP_CHANNELS:
            raise ValueError('計劃超出可修改範圍。')
        delta=(op['before'][0]^op['after'][0]) | (op['before'][1]^op['after'][1])
        if delta & ~CAP_MASK:raise ValueError('計劃包含附件／預覽以外的權限變更。')
        if not restore:
            if str(channel.type)!=op['channel_type'] or (str(channel.category_id) if channel.category_id else None)!=op['category']:
                raise ValueError('頻道分類或類型已改變，停止。')
            if str(role.id)==str(plan['verified']) and (role.managed or any(getattr(role.permissions,p) for p in STAFF_POWERS)):
                raise ValueError('Verified 角色權限已改變，停止。')
            if str(role.id) not in {str(guild.id),str(plan['verified'])} and not op.get('preserve_service'):
                if role.is_bot_managed() or any(getattr(role.permissions,p) for p in STAFF_POWERS):
                    raise ValueError('目標角色已成為 Bot／管理角色，停止。')
    # Bound each command; receipts remain durable for audit and restoration.
    try:
        async with asyncio.timeout(150):
            return await journal.execute(guild,plan,authorize,restore=restore,validate=validate,max_ops=20,max_seconds=90)
    except TimeoutError:
        journal.save(plan)
        return plan
