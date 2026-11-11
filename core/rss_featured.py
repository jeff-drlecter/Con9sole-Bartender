"""Read-only calendar highlights and source-attributed Steam chart snapshots."""
from datetime import datetime
from core.rss_digest import HK, identity, canonical_url, normalized
from core.rss_preferences import DEFAULT, matches, tags
from core.rss_delivery import safe_link

CHART_URL='https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/'
CHART_PAGE='https://store.steampowered.com/charts/mostplayed'


def highlights(store,config,sources,now,period,pref=None,limit=5):
    if period not in {'today','month'}: raise ValueError('unknown period')
    local=datetime.fromtimestamp(now,HK)
    start=local.replace(hour=0,minute=0,second=0,microsecond=0)
    if period=='month': start=start.replace(day=1)
    with store.connect() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM articles WHERE published>=? AND published<=? AND state!='invalid_link' ORDER BY published DESC",(start.timestamp(),now))]
    ranked=[]
    for a in rows:
        if a['source'] not in sources or not safe_link(a['link']): continue
        a['offer']=config.offers.get(canonical_url(a['link']))
        if a['offer'] and a['offer']['deadline']<=now: continue
        score=config.score(a)
        if score is None or not matches(a,pref or DEFAULT): continue
        text=normalized(a['title']+' '+a['summary'])
        kind=tags(a)[2]
        score += 5 if a['offer'] else 3 if kind=='member' else 0
        score += 2 if any(w in text for w in ('更新','跨平台','合作','update','cross-play','co-op')) else 0
        # No filler: generic unprioritized articles are not called highlights.
        if score<=0: continue
        a['reason']='會員遊戲' if kind=='member' else '更新／合作' if any(w in text for w in ('更新','跨平台','合作','update','cross-play','co-op')) else '關注主題'
        if a['offer']: a['reason']={'keep':'永久領取','trial':'限時試玩','member':'會員福利','f2p':'本身免費'}[kind]
        ranked.append((score,a))
    ranked.sort(key=lambda x:(-x[0],-x[1]['published'],x[1]['source'],x[1]['key']))
    # Merge all exact URL/title aliases before selecting representatives.
    groups=[]
    for _,a in ranked:
        ids={v for v in identity(a) if v}
        overlapping=[g for g in groups if g & ids]
        for g in overlapping:
            ids.update(g)
            groups.remove(g)
        groups.append(ids)
    selected=[]
    seen=set()
    for _,a in ranked:
        ids=next(g for g in groups if identity(a)[0] in g)
        if seen & ids: continue
        seen.update(ids)
        selected.append(a)
        if len(selected)>=limit: break
    return selected


def parse_chart(data,now):
    response=data['response']
    stamp=response['rollup_date']
    if type(stamp) is not int or not now-7*86400<=stamp<=now+300: raise ValueError('stale chart date')
    result=[]
    seen=set()
    for row in response['ranks']:
        if any(type(row.get(k)) is not int for k in ('rank','appid','peak_in_game')): raise ValueError('invalid chart values')
        if row['rank']<1 or row['appid']<1 or row['peak_in_game']<0: raise ValueError('invalid chart values')
        if row['appid'] in seen: continue
        seen.add(row['appid'])
        result.append({k:row[k] for k in ('rank','appid','peak_in_game')})
    if not result: raise ValueError('empty chart')
    return stamp,sorted(result,key=lambda r:r['rank'])[:10]


def chart_rows(snapshot,config,now,pref=None):
    if not snapshot or now-snapshot['fetched']>86400 or now-snapshot['asof']>7*86400: return []
    pref=pref or DEFAULT
    rows=[]
    for row in snapshot['rows']:
        article=dict(title=row['name'],summary='PC Steam',source='4gamers')
        if config.score(article) is None or not matches(article,pref): continue
        rows.append(row)
    return rows[:5]


def verified_game(data):
    # Steam labels some utilities as type=game; genre IDs are language-independent.
    software_genres={'51','53','55','57'}  # modeling, design, photo editing, utilities
    genres={str(g.get('id')) for g in data.get('genres',[]) if isinstance(g,dict)}
    return data.get('type')=='game' and isinstance(data.get('name'),str) and bool(data['name'].strip()) and not genres & software_genres
