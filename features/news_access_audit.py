"""Pure permission modelling for private 02/06 review; never writes Discord state."""
from itertools import combinations
import discord
import config
from features.news_channel_categories import CHANNELS, ROLE_NAMES

FLAGS = {'view':1<<10, 'history':1<<16, 'send':1<<11, 'commands':1<<31}


def permissions(guild_id, roles, member, channel, owner_id=None):
    ids = {str(guild_id), *map(str, member['roles'])}
    value = 0
    for role in roles:
        if str(role['id']) in ids:
            value |= int(role['permissions'])
    if str(member['user']['id']) == str(owner_id) or value & 8:
        return discord.Permissions.all().value
    overwrites = channel.get('permission_overwrites', [])
    everyone = next((o for o in overwrites if o['type']==0 and str(o['id'])==str(guild_id)), {})
    value = (value & ~int(everyone.get('deny', 0))) | int(everyone.get('allow', 0))
    allow = deny = 0
    for o in overwrites:
        if o['type']==0 and str(o['id']) in ids-{str(guild_id)}:
            allow |= int(o['allow']); deny |= int(o['deny'])
    value = (value & ~deny) | allow
    person = next((o for o in overwrites if o['type']==1 and str(o['id'])==str(member['user']['id'])), {})
    return (value & ~int(person.get('deny', 0))) | int(person.get('allow', 0))


def access(value):
    result = {k:bool(value & mask) for k,mask in FLAGS.items()}
    if not result['view']:
        result.update(history=False, send=False, commands=False)
    result['summary_visible'] = result['view'] and result['history']
    # This is a permission prerequisite, NOT a live component-interaction test.
    result['button_prerequisites'] = result['summary_visible']
    return result


def audit(snapshot):
    guild = snapshot['guild']
    if str(guild['id']) != str(config.GUILD_ID):
        raise ValueError('Unexpected guild')
    roles, channels = snapshot['roles'], snapshot['channels']
    role_ids = {}
    for key, name in ROLE_NAMES.items():
        matches = [r for r in roles if r['name']==name]
        if len(matches)!=1 or matches[0].get('managed') or int(matches[0]['permissions']):
            raise ValueError('Missing, ambiguous or privileged category role: '+key)
        role_ids[key] = str(matches[0]['id'])
    legacy = [r for r in roles if r['name'] in {'news-sub','no-news-sub'}]
    watched = {str(r['id']) for r in legacy} | set(role_ids.values()) | set(map(str,config.HELPER_ROLE_IDS))
    dependencies = []
    for c in channels:
        for o in c.get('permission_overwrites', []):
            if o['type']==0 and str(o['id']) in watched:
                dependencies.append(dict(kind='channel_overwrite', channel=str(c['id']), name=c['name'],
                    role=str(o['id']), allow=str(o['allow']), deny=str(o['deny'])))
    for prompt in snapshot.get('onboarding', {}).get('prompts', []):
        for option in prompt.get('options', []):
            for rid in set(map(str,option.get('role_ids', []))) & watched:
                dependencies.append(dict(kind='onboarding', prompt=str(prompt['id']), option=str(option.get('id','')),
                    title=option['title'], role=rid))
    by_channel = {str(c['id']):c for c in channels}
    matrix = []
    for helper in (False, True):
        for count in range(4):
            for choice in combinations(CHANNELS,count):
                for legacy_ids in ([], *[[str(r['id'])] for r in legacy], [str(r['id']) for r in legacy]):
                    ids = [str(config.VERIFIED_ROLE_ID), *legacy_ids, *[role_ids[k] for k in choice]]
                    if helper: ids += list(map(str,config.HELPER_ROLE_IDS))
                    member = dict(user=dict(id='0'),roles=ids)
                    targets = {}
                    for key,cid in CHANNELS.items():
                        channel = by_channel.get(str(cid))
                        targets[key] = None if channel is None else access(permissions(guild['id'],roles,member,channel,guild.get('owner_id')))
                    matrix.append(dict(kind='Helper' if helper else 'member', selected=list(choice),legacy=legacy_ids,channels=targets))
    accounts = []
    for member in snapshot.get('members', []):
        roles_for_member = [dict(id=str(r['id']),name=r['name']) for r in roles if str(r['id']) in set(map(str,member['roles']))]
        accounts.append(dict(id=str(member['user']['id']), roles=roles_for_member,
            channels={key:access(permissions(guild['id'],roles,member,by_channel[str(cid)],guild.get('owner_id')))
                      for key,cid in CHANNELS.items() if str(cid) in by_channel}))
    return dict(kind='read_only_permission_model_not_UI_test', captured_at=snapshot.get('captured_at'),
        category_roles=role_ids, legacy_roles=[dict(id=str(r['id']),name=r['name'],permissions=str(r['permissions'])) for r in legacy],
        dependencies=dependencies, matrix=matrix, accounts=accounts,
        member_counts=snapshot.get('member_counts','not_collected'),
        external_bot_dependencies='not_observable_from_Discord_permission_snapshot',
        changes_applied=[], role_deletion_proposed=False)
