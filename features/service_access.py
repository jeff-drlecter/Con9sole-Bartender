"""Narrow channel preparation before removal of two known service admin roles."""
import discord
from features.anti_scam_fix import current

SERVICES={'carl':1362785654492369280,'bartender':1417493340819292360}
CARL_OUTPUT={1401346745346297966,1421103987599610018,1421128161491419186,1421143797571784895,1010456227769229355}
BASE=('view_channel','read_message_history','send_messages','send_messages_in_threads','embed_links','attach_files','add_reactions','use_external_emojis')
ROLE_FIELDS={
 'carl':BASE+('view_audit_log','manage_roles','manage_messages','kick_members','ban_members','moderate_members'),
 'bartender':BASE+('manage_guild','manage_channels','manage_roles','manage_messages','manage_threads','create_public_threads','create_instant_invite','connect','move_members'),
}

def role_permissions(service):
    return discord.Permissions(**dict.fromkeys(ROLE_FIELDS[service],True))

def required(service,channel):
    fields=['view_channel','read_message_history']
    kind=str(channel.type)
    if service=='bartender' or channel.id in CARL_OUTPUT:
        fields+=['send_messages','send_messages_in_threads','embed_links','attach_files']
    if service=='bartender':
        fields+=['manage_channels','manage_roles']
        if kind in ('voice','stage_voice','category'):fields+=['connect','move_members']
        if kind not in ('voice','stage_voice'):fields+=['create_public_threads','manage_threads','manage_messages']
        if channel.id==1278976821710426133:fields+=['create_instant_invite']
    return discord.Permissions(**dict.fromkeys(fields,True)).value

async def inventory(guild,service):
    roles=await guild.fetch_roles()
    role=next((r for r in roles if r.id==SERVICES[service]),None)
    if role is None or not role.is_bot_managed() or not role.tags or not role.tags.bot_id:
        raise ValueError('指定服務角色／Bot身分不符，停止。')
    member=await guild.fetch_member(role.tags.bot_id)
    # Explicit per-member denies override role allows. Do not silently change them.
    channels=await guild.fetch_channels()
    for channel in channels:
        _,deny=channel.overwrites_for(member).pair()
        if deny.value & required(service,channel):raise ValueError('Bot存在所需權限的個人拒絕，需先核對。')
    return role,member,channels

async def plan(guild,service,actor):
    import time,uuid
    role,member,channels=await inventory(guild,service)
    if not role.permissions.administrator:
        raise ValueError('只可在服務仍有Administrator時準備存取；降權後用驗收，唔自動擴權。')
    ops=[]
    for channel in sorted(channels,key=lambda c:(str(c.type)!='category',c.id)):
        # A synced child is covered by its parent; direct exceptions remain direct.
        if getattr(channel,'permissions_synced',False) and channel.category_id:
            parent=next((c for c in channels if c.id==channel.category_id),None)
            if parent is not None and required(service,parent)&required(service,channel)==required(service,channel):continue
        before=[p.value for p in channel.overwrites_for(role).pair()]
        mask=required(service,channel)
        after=[before[0]|mask,before[1]&~mask]
        if before!=after:
            ops.append(dict(kind='overwrite',channel=channel.id,target=role.id,name=f'{channel.name}/{role.name}',before=before,after=after,state='prepared',mask=mask))
    return dict(id=uuid.uuid4().hex[:12],guild=guild.id,actor=actor,stamp=time.time(),scope='service_access',service=service,ops=ops[:20],remaining=len(ops),role_before=role.permissions.value,role_after=role_permissions(service).value)

async def validate_live(guild,service):
    role,member,channels=await inventory(guild,service)
    from features.permission_audit import role_permissions as effective,overwrite_rows,permissions
    # Simulate the service-specific role without Administrator; retain real other roles.
    role_rows=[dict(id=str(r.id),permissions=permissions(role_permissions(service).value if r.id==role.id else r.permissions.value)) for r in await guild.fetch_roles()]
    if any(r.permissions.administrator for r in member.roles if r.id!=role.id):raise ValueError('Bot另一個角色仍有Administrator，需先核對。')
    missing=[]
    for c in channels:
        value=effective(role_rows,dict(overwrites=overwrite_rows(c)),str(guild.id),[r.id for r in member.roles]).value
        ow=c.overwrites_for(member);allow,deny=ow.pair();value=(value&~deny.value)|allow.value
        mask=required(service,c)
        if value&mask!=mask:missing.append(dict(channel=c.id,name=c.name,missing=mask&~value))
    return dict(service=service,administrator=role.permissions.administrator,channels_checked=len(channels),missing=missing,role_actual=role.permissions.value,role_expected=role_permissions(service).value)

async def execute(guild,p,authorize,restore=False):
    import asyncio
    from features import anti_scam_fix as journal
    service=p.get('service')
    if p.get('scope')!='service_access' or service not in SERVICES:raise ValueError('錯誤服務計劃。')
    role,_,_=await inventory(guild,service)
    if not restore and (not role.permissions.administrator or role.permissions.value!=p['role_before']):raise ValueError('服務角色已變更，未執行。')
    def validate(op,target,channel):
        if target.id!=SERVICES[service] or op['kind']!='overwrite' or channel is None:raise ValueError('目標超出範圍。')
        mask=required(service,channel)
        delta=(op['before'][0]^op['after'][0])|(op['before'][1]^op['after'][1])
        if delta&~mask or op['mask']!=mask:raise ValueError('權限超出服務需求。')
    try:
        async with asyncio.timeout(150):
            return await journal.execute(guild,p,authorize,restore=restore,validate=validate,max_ops=20,max_seconds=90)
    except TimeoutError:
        journal.save(p)
        return p
