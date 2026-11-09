"""Representative unverified access witnesses and non-executable change preview."""
from itertools import combinations
import discord
from features.permission_audit import role_permissions

STAFF_IDS={'626379227473903632','1279071042249162856'}
STAFF_POWERS=('administrator','manage_guild','manage_roles','manage_channels','manage_messages','manage_webhooks','moderate_members','kick_members','ban_members')
CAPS=('attach_files','embed_links')


def preview(snapshot,verified):
    vid=str(verified);gid=snapshot['guild']['id'];roles=snapshot['roles']
    names={r['id']:r['name'] for r in roles}
    ordinary=[]
    for r in roles:
        p=discord.Permissions(int(r['permissions']['value']))
        if r['id'] in {gid,vid}|STAFF_IDS or r.get('bot_managed',False) or any(getattr(p,k) for k in STAFF_POWERS):continue
        ordinary.append(r['id'])
    allowed=set(ordinary);scenarios={()}
    scenarios.update((r,) for r in ordinary)
    scenarios.update(tuple(sorted(pair)) for pair in combinations(ordinary,2))
    onboarding=snapshot['onboarding']
    if onboarding['status']=='ok':
        for prompt in onboarding['data']['prompts']:
            for option in prompt['options']:
                ids=set(map(str,option['role_ids']))
                if ids and ids<=allowed:
                    scenarios.add(tuple(sorted(ids)))
                    for optin in ('1425179515637727302','1425184403742527609'):
                        if optin in allowed:scenarios.add(tuple(sorted(ids|{optin})))
    scenarios=sorted(scenarios,key=lambda ids:(len(ids),ids))
    role_index={r['id']:r for r in roles}
    scenario_records=[(ids,[role_index[r] for r in (gid,*ids) if r in role_index]) for ids in scenarios]
    findings=[];proposals=[];exceptions=[]
    mask=discord.Permissions(attach_files=True,embed_links=True).value
    for channel in snapshot['channels']:
        if channel['type']=='category':continue
        witnesses={}
        for ids,selected_roles in scenario_records:
            effective=role_permissions(selected_roles,channel,gid,ids)
            if not effective.view_channel:continue
            surface='channel' if effective.send_messages else 'thread_reply_candidate' if effective.send_messages_in_threads else None
            if surface is None:continue
            for cap in CAPS:
                if cap not in witnesses and getattr(effective,cap):
                    witnesses[cap]=dict(role_ids=list(ids),role_names=[names[r] for r in ids],surface=surface,
                        base_grant_roles=[r['id'] for r in selected_roles if getattr(discord.Permissions(int(r['permissions']['value'])),cap)],
                        channel_permission_rows=[o for o in channel['overwrites'] if o['type']=='role' and o['id'] in {gid,*ids}])
            if len(witnesses)==len(CAPS):break
        member_grants=[o['id'] for o in channel['overwrites'] if o['type']=='member' and int(o['allow']['value']) & mask]
        if member_grants:exceptions.append(dict(channel_id=channel['id'],kind='member_overwrite_requires_membership_review',targets=member_grants))
        if not witnesses:continue
        findings.append(dict(channel_id=channel['id'],channel_name=channel['name'],type=channel['type'],witnesses=witnesses))
        if vid not in names:continue
        rows={o['id']:o for o in channel['overwrites'] if o['type']=='role'}
        verified_deny=int(rows.get(vid,{'deny':{'value':'0'}})['deny']['value']) & mask
        if verified_deny:
            exceptions.append(dict(channel_id=channel['id'],kind='verified_explicit_deny_preserved',permission_value=str(verified_deny)))
            continue
        operations=[]
        # Only attachment/embed bits are proposed. No write API consumes this report.
        for rid in [gid,vid]+[r for r in ordinary if r in rows]:
            before=rows.get(rid,dict(allow=dict(value='0'),deny=dict(value='0')))
            allow=int(before['allow']['value']);deny=int(before['deny']['value'])
            if rid==gid:new_allow=allow & ~mask;new_deny=deny | mask
            elif rid==vid:new_allow=allow | mask;new_deny=deny & ~mask
            else:new_allow=allow & ~mask;new_deny=deny
            if (allow,deny)!=(new_allow,new_deny):
                operations.append(dict(target_role_id=rid,target_name=names.get(rid,rid),
                    before=[str(allow),str(deny)],after=[str(new_allow),str(new_deny)]))
        proposals.append(dict(channel_id=channel['id'],channel_name=channel['name'],operations=operations,
            apply_supported=False,requires_review=True))
    return dict(schema_version=1,update='Anti-scam Update',mode='preview_only',source_captured_at=snapshot['captured_at'],
        guild_id=gid,ordinary_role_count=len(ordinary),scenario_count=len(scenarios),findings=findings,proposals=proposals,exceptions=exceptions,
        blockers=[] if vid in names else ['Verified 角色不存在，無法產生收窄方案。'],
        coverage=['Checked everyone, every eligible single role and pair, onboarding answer role groups and those groups plus off-topic/news-sub.',
            'Hypothetical witnesses, not a member census. Arbitrary triples/higher combinations, owner, timeout, screening, threads/membership and member-specific overwrites are not resolved.',
            'Managed human roles such as Booster are included; bot-managed and staff roles are excluded.',
            'Channel surface requires View and Send; thread_reply_candidate requires View and Send in Threads, but no actual thread existence/access is asserted.',
            'Embed Links only controls previews, not posting URLs. Existing native URL/spam rules remain alert-only.',
            'Proposals are not executable plans. Verified explicit attachment/embed denials are preserved for manual review; member grants are separate exceptions.',
            'Proposed Verified allows may broaden attachment/embed permissions for Verified in affected channels. Review purpose, category sync and other role/member overrides before any application.',
            'No message contents, member list or Discord settings were modified.'])


def summary(result):
    examples=[]
    for row in result['findings']:
        witness=next(iter(row['witnesses'].values()))
        labels='＋'.join(witness['role_names']) or '@everyone'
        examples.append(f"{row['channel_name']}：{labels}")
    examples=examples[:5]
    return ('**Verified 高風險權限預覽｜未修改**\n'
        f"代表情境 {result['scenario_count']} 組｜命中頻道 {len(result['findings'])} 個｜需覆核例外 {len(result['exceptions'])} 項\n"
        +'\n'.join(examples)+'\n完整角色組合、權限來源及候選前後差異見附件。\n'
        '唔係全會員／所有組合驗收；附件及連結預覽與貼 URL 分開。連結仍只提示，候選方案未套用。')
