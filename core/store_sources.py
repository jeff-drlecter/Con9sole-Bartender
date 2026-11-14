"""Bounded store collectors for private browsing only; no Discord sends or claims."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from core.rss_delivery import DeliveryStore
from core.rss_digest import HK, identity
from core.rss_preferences import matches

MARKETS = {'hk': '香港', 'tw': '台灣'}
EPIC_HOST = 'https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions'
MAX_ITEMS = 300


def epic_url(market):
    if market not in MARKETS: raise ValueError('unknown market')
    return EPIC_HOST + '?' + urlencode(dict(locale='zh-Hant', country=market.upper(), allowCountries=market.upper()))


def timestamp(value):
    if not isinstance(value, str): raise ValueError('missing dated promotion')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None: raise ValueError('promotion time needs timezone')
    return dt.timestamp()


def text(value, limit):
    if not isinstance(value, str) or not value.strip(): raise ValueError('missing store text')
    return html.unescape(re.sub(r'<[^>]*>|\[/?[^\]]*\]', '', value)).strip()[:limit]


def epic_offers(data, market, now):
    """Only active paid-base-game promotions with zero checkout price qualify."""
    if market not in MARKETS: raise ValueError('unknown market')
    if data.get('errors'): raise ValueError('Epic returned API errors')
    rows = data['data']['Catalog']['searchStore']['elements']
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS: raise ValueError('invalid Epic catalog')
    result = []
    for item in rows:
        if item.get('offerType') != 'BASE_GAME' or item.get('status') != 'ACTIVE' or item.get('isCodeRedemptionOnly'):
            continue
        promos = item.get('promotions')
        if not promos: continue
        groups = promos.get('promotionalOffers')
        if not isinstance(groups, list): raise ValueError('invalid promotion groups')
        price = item['price']['totalPrice']
        if any(type(price.get(k)) is not int for k in ('discountPrice', 'originalPrice', 'voucherDiscount')):
            raise ValueError('invalid Epic price')
        if price['discountPrice'] != 0 or price['originalPrice'] <= 0 or price['voucherDiscount'] != 0:
            continue
        if price.get('currencyCode') != {'hk':'HKD','tw':'TWD'}[market]:
            raise ValueError('unexpected regional currency')
        categories = {c.get('path') for c in item.get('categories', [])}
        if 'games/edition/base' not in categories: continue
        mappings = item.get('catalogNs', {}).get('mappings', [])
        slug = next((m['pageSlug'] for m in mappings if m.get('pageType') == 'productHome'), item.get('productSlug'))
        if not isinstance(slug, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
            continue
        game_id = item.get('id')
        if not isinstance(game_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', game_id):
            raise ValueError('invalid Epic offer ID')
        for group in groups:
            offers = group['promotionalOffers']
            if not isinstance(offers, list): raise ValueError('invalid promotions')
            for promo in offers:
                discount = promo['discountSetting']
                if discount.get('discountType') != 'PERCENTAGE' or type(discount.get('discountPercentage')) is not int or discount['discountPercentage'] != 0:
                    continue
                start, end = timestamp(promo['startDate']), timestamp(promo['endDate'])
                if not start <= now < end: continue
                result.append(dict(source='epic',key=f'{game_id}:{int(start)}',title=text(item['title'],200),
                    summary='PC Epic Games｜' + text(item.get('description') or item['title'],700),
                    link='https://store.epicgames.com/p/'+slug,published=start,
                    offer=dict(kind='keep',region=MARKETS[market],regions=[market],starts=start,deadline=end,
                               checked=now,verified=True,evidence=epic_url(market))))
    return result


def steam_news(data, appid, name, now):
    app = data['appnews']
    if app.get('appid') != appid: raise ValueError('Steam AppID mismatch')
    rows = app['newsitems']
    if not isinstance(rows,list) or len(rows)>20: raise ValueError('invalid Steam news')
    result=[]
    for row in rows:
        if row.get('appid') != appid or row.get('feedname') != 'steam_community_announcements': continue
        stamp=row.get('date'); gid=str(row.get('gid',''))
        if type(stamp) is not int or not gid.isdigit(): raise ValueError('invalid Steam news identity/date')
        if not now-35*86400 <= stamp <= now+300: continue
        # Keep the API's actual link; news IDs need not be Steam event-view IDs.
        link=row.get('url','')
        url=urlsplit(link)
        valid = ((url.hostname=='steamstore-a.akamaihd.net' and url.path==f'/news/externalpost/steam_community_announcements/{gid}')
                 or (url.hostname=='store.steampowered.com' and url.path==f'/news/app/{appid}/view/{gid}')
                 or (url.hostname=='steamcommunity.com' and url.path==f'/games/{appid}/announcements/detail/{gid}'))
        if url.scheme!='https' or url.username or url.password or url.query or url.fragment or not valid:
            raise ValueError('unrecognized official Steam announcement URL')
        result.append(dict(source='steam',key=f'{appid}:{gid}',title=f'{name}｜'+text(row['title'],150),
            summary='PC Steam｜'+text(row.get('contents') or row['title'],700),
            link=link,published=stamp,offer=None))
    return result


def reviewed_steam_offer(entry, app, market, now):
    """Operator-reviewed evidence plus live regional checks; never infer a giveaway from 'free'."""
    required={'appid','kind','starts_at','ends_at','regions','evidence_url','reviewed'}
    if not isinstance(entry,dict) or set(entry)!=required or entry['reviewed'] is not True:
        raise ValueError('Steam offer needs reviewed official evidence')
    appid=entry['appid']; kind=entry['kind']
    if type(appid) is not int or appid<=0 or kind not in {'keep','trial'}: raise ValueError('invalid Steam offer')
    if not isinstance(entry['regions'],list) or not entry['regions'] or set(entry['regions'])-MARKETS.keys():
        raise ValueError('invalid reviewed regions')
    url=urlsplit(entry['evidence_url'])
    if url.scheme!='https' or url.hostname!='store.steampowered.com' or not re.fullmatch(rf'/news/app/{appid}/view/[0-9]+/?',url.path) or url.query or url.fragment:
        raise ValueError('official matching Steam announcement required')
    start,end=timestamp(entry['starts_at']),timestamp(entry['ends_at'])
    if start>=end: raise ValueError('invalid reviewed window')
    if market not in entry['regions'] or not start<=now<end: return None
    if app.get('type')!='game' or app.get('steam_appid')!=appid or app.get('is_free') is not False: return None
    if kind=='keep':
        price=app.get('price_overview',{})
        if (price.get('currency')!={'hk':'HKD','tw':'TWD'}[market] or type(price.get('initial')) is not int
            or price['initial']<=0 or type(price.get('final')) is not int or price['final']!=0 or price.get('discount_percent')!=100):
            return None
    # For trial offers the reviewed official announcement asserts temporary access;
    # the normal store price can remain nonzero. This is not automatic verification.
    return dict(source='steam',key=f'offer:{appid}:{kind}:{int(start)}',title=text(app['name'],200),
        summary='PC Steam｜'+('永久領取' if kind=='keep' else '限時試玩，活動後不保留遊玩權限'),
        link=f'https://store.steampowered.com/app/{appid}/',published=start,
        offer=dict(kind=kind,region=MARKETS[market],regions=[market],starts=start,deadline=end,checked=now,
                   verified=True,evidence=entry['evidence_url']))


class StoreNewsStore(DeliveryStore):
    def __init__(self,path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS store_snapshots (bucket TEXT PRIMARY KEY, checked REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS store_items (bucket TEXT, key TEXT, payload TEXT, PRIMARY KEY(bucket,key));
            ''')

    def replace(self,bucket,rows,now):
        if len(rows)>MAX_ITEMS: raise ValueError('too many store items')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM store_items WHERE bucket=?',(bucket,))
            db.executemany('INSERT INTO store_items VALUES (?,?,?)',[(bucket,a['key'],json.dumps(a,ensure_ascii=False)) for a in rows])
            db.execute('INSERT OR REPLACE INTO store_snapshots VALUES (?,?)',(bucket,now))

    def collect_news(self,bucket,rows,now):
        # Accumulate at most a month of watched-game updates, with a hard per-game cap.
        with self.connect() as db:
            previous=[json.loads(r[0]) for r in db.execute('SELECT payload FROM store_items WHERE bucket=?',(bucket,))]
        merged={a['key']:a for a in previous+rows if a['published']>=now-35*86400}
        self.replace(bucket,sorted(merged.values(),key=lambda a:a['published'],reverse=True)[:250],now)

    def status(self):
        with self.connect() as db:
            return [tuple(r) for r in db.execute('SELECT s.bucket,s.checked,count(i.key) FROM store_snapshots s LEFT JOIN store_items i USING(bucket) GROUP BY s.bucket,s.checked')]

    def preview(self,config,pref,now,period='daily'):
        local=datetime.fromtimestamp(now,HK)
        start=(now-86400 if period=='daily' else local.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
               if period=='month' else local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        with self.connect() as db:
            rows=[(json.loads(r[0]),r[1]) for r in db.execute('SELECT payload,checked FROM store_items JOIN store_snapshots USING(bucket)')]
        result=[]
        for a,checked in rows:
            offer=a.get('offer')
            if checked>now+300 or now-checked>(7200 if offer else 86400): continue
            if offer:
                if not offer['starts']<=now<offer['deadline']: continue
            elif not start<=a['published']<=now+300: continue
            if config.score(a) is None or not matches(a,pref): continue
            a['reason']='永久領取' if offer and offer['kind']=='keep' else '限時試玩' if offer else '遊戲更新'
            result.append(a)
        return result


def combine_articles(rows,limit=8,config=None):
    """Merge regional copies only after member filtering; keep earliest verified deadline."""
    rows=sorted(rows,key=lambda a:(-((10 if a.get('offer') else 0)+(config.score(a) or 0 if config else 0)),-a['published']))
    selected=[];seen=set()
    def identities(a):
        if a.get('offer'):
            offer=a['offer']
            return {(a['source'],a['link'],offer['kind'],offer['starts'])}
        # Repeated titles such as 'Counter-Strike 2 Update' are distinct posts.
        if a['source']=='steam': return {a['link']}
        return {v for v in identity(a) if v}
    for a in rows:
        ids=identities(a)
        if seen & ids:
            existing=next((b for b in selected if identities(b) & ids),None)
            if existing and existing.get('offer') and a.get('offer'):
                existing['offer']=dict(existing['offer'])
                markets=sorted(set(existing['offer'].get('regions',[])) | set(a['offer'].get('regions',[])))
                existing['offer']['regions']=markets
                existing['offer']['region']='／'.join(MARKETS[m] for m in markets)
                existing['offer']['deadline']=min(existing['offer']['deadline'],a['offer']['deadline'])
            continue
        seen.update(ids); selected.append(dict(a))
    return selected[:limit]
