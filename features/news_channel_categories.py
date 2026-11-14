"""Explicit news-channel opt-ins; separate from personal RSS filters and game roles."""
from copy import deepcopy

CHANNELS = {'ps':1364201334798290994, 'xbox':1379699174668505098, 'pc':1364210080043630612}
LABELS = {'ps':'PlayStation 新聞', 'xbox':'Xbox 新聞', 'pc':'PC 新聞（Steam／Epic）'}
ROLE_NAMES = {key:'新聞接收｜'+key.upper() for key in CHANNELS}
DESCRIPTIONS = {'ps':'顯示 PlayStation 新聞、PS Plus 及相關更新。',
                'xbox':'顯示 Xbox 新聞、Game Pass 及相關更新。',
                'pc':'顯示 PC 遊戲新聞；Steam／Epic 新來源仍按驗收進度開放。'}
LEGACY_PROMPT='1426676369567387826'
VIEW=1<<10


def category_prompts(prompts, role_ids):
    """Expand only the known optional-area news answer; preserve other mappings/IDs."""
    result=deepcopy(prompts)
    matches=[p for p in result if p['title']=='想開啟哪些區域？（選填，可複選）']
    if len(matches)!=1: raise ValueError('optional-area question missing or ambiguous')
    prompt=matches[0]
    if prompt.get('required') or prompt.get('single_select'): raise ValueError('area question must remain optional multi-select')
    titles={o['title'] for o in prompt['options']}
    expected=set(LABELS.values())
    if expected<=titles:
        if any(str(p['id'])==LEGACY_PROMPT for p in result):
            raise ValueError('legacy news question still conflicts')
        for key,label in LABELS.items():
            if sum(o['title']==label for o in prompt['options'])!=1: raise ValueError('duplicate news category')
            option=next(o for o in prompt['options'] if o['title']==label)
            if list(map(str,option.get('role_ids',[])))!=[str(role_ids[key])] or list(map(str,option.get('channel_ids',[])))!=[str(CHANNELS[key])]: raise ValueError('existing category mapping differs')
        return result
    if '遊戲新聞區' not in titles: raise ValueError('old news area answer missing')
    options=[]
    for option in prompt['options']:
        if option['title']!='遊戲新聞區':
            options.append(option);continue
        for key,label in LABELS.items():
            options.append(dict(title=label,description=DESCRIPTIONS[key],role_ids=[str(role_ids[key])],
                                channel_ids=[str(CHANNELS[key])]))
    prompt['options']=options
    # The old all-news show/hide question would conflict with independent opt-ins.
    old=[p for p in result if str(p['id'])==LEGACY_PROMPT]
    if old:
        if len(old)!=1 or {o['title'] for o in old[0]['options']}!={'顯示新聞區','暫時隱藏'}:
            raise ValueError('legacy news question changed; refusing to remove it')
        result.remove(old[0])
    return result


def can_view(guild_id, roles, member, channel, owner_id=None):
    ids=set(map(str,member['roles']))|{str(guild_id)}
    permissions=0
    for role in roles:
        if str(role['id']) in ids: permissions|=int(role['permissions'])
    if member['user']['id']==owner_id or permissions & 8: return True
    overwrites=channel.get('permission_overwrites',[])
    base=next((o for o in overwrites if str(o['id'])==str(guild_id) and o['type']==0),{})
    permissions=(permissions & ~int(base.get('deny',0))) | int(base.get('allow',0))
    allow=deny=0
    for o in overwrites:
        if o['type']==0 and str(o['id']) in ids-{str(guild_id)}:
            allow|=int(o['allow']);deny|=int(o['deny'])
    permissions=(permissions & ~deny)|allow
    personal=next((o for o in overwrites if o['type']==1 and str(o['id'])==member['user']['id']),{})
    permissions=(permissions & ~int(personal.get('deny',0)))|int(personal.get('allow',0))
    return bool(permissions & VIEW)


def prompt_signature(prompt):
    """Compare editable behavior, not read-only/default/null response metadata."""
    options=[]
    for option in prompt.get('options',[]):
        emoji=option.get('emoji') or {}
        options.append((str(option.get('id','')),option['title'],option.get('description') or '',
            tuple(sorted(map(str,option.get('role_ids',[])))),tuple(sorted(map(str,option.get('channel_ids',[])))),
            str(emoji.get('id') or ''),emoji.get('name') or ''))
    return (str(prompt['id']),prompt['title'],bool(prompt.get('single_select')),bool(prompt.get('required')),
            bool(prompt.get('in_onboarding')),tuple(sorted(options)))


def overwrite_signature(overwrites):
    # Discord may return an equivalent overwrite set in a different list order.
    return sorted((str(o['id']),int(o['type']),int(o['allow']),int(o['deny'])) for o in overwrites)


def category_overwrites(guild_id, channel, chosen_role, all_news_roles, privileged_roles, bot_roles):
    result=deepcopy(channel.get('permission_overwrites',[]))
    for o in result:
        if o['type']==0 and str(o['id']) not in privileged_roles|bot_roles:
            o['allow']=str(int(o['allow']) & ~VIEW)
    def allow_role(rid):
        o=next((o for o in result if str(o['id'])==str(rid) and o['type']==0),None)
        if o is None:
            o=dict(id=str(rid),type=0,allow='0',deny='0');result.append(o)
        o['allow']=str(int(o['allow'])|VIEW);o['deny']=str(int(o['deny']) & ~VIEW)
    default=next((o for o in result if str(o['id'])==str(guild_id) and o['type']==0),None)
    if default is None:
        default=dict(id=str(guild_id),type=0,allow='0',deny='0');result.append(default)
    default['allow']=str(int(default['allow']) & ~VIEW)
    default['deny']=str(int(default['deny'])|VIEW)
    allow_role(chosen_role)
    for rid in bot_roles: allow_role(rid)
    return result
