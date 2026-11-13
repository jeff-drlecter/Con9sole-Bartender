"""Sandbox-only personal preferences; never consumes the delivery queue."""
import json
import re
from core.rss_delivery import DeliveryStore
from core.rss_digest import normalized

OPTIONS = {
    'platforms': {'ps':'PlayStation', 'xbox':'Xbox', 'pc':'PC'},
    'stores': {'any':'不限商店', 'steam':'Steam', 'epic':'Epic'},
    'kinds': {'news':'新聞', 'keep':'永久限免', 'member':'會員遊戲', 'trial':'限時試玩'},
}
DEFAULT = {'platforms':['ps','xbox','pc'], 'stores':['any'], 'kinds':['news','keep','member','trial'], 'include':[], 'exclude':[]}


def validate(data):
    if set(data) != set(DEFAULT): raise ValueError('invalid preferences')
    for key, options in OPTIONS.items():
        if not isinstance(data[key], list) or not data[key] or set(data[key])-set(options):
            raise ValueError('請至少選一項有效選項。')
    for key in ('include','exclude'):
        if not isinstance(data[key],list) or len(data[key])>10 or any(not isinstance(w,str) or not w.strip() or len(w)>40 for w in data[key]):
            raise ValueError('每欄最多 10 個關鍵字，每個最多 40 字。')
    return data


def keywords(text):
    return [w.strip() for w in re.split('[,，\n]',text) if w.strip()]


class PreferenceStore(DeliveryStore):
    def __init__(self,path):
        super().__init__(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS preferences (user_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS panels (channel_id INTEGER PRIMARY KEY, state TEXT, message_id INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS featured_posts (slot TEXT PRIMARY KEY, state TEXT, message_id INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS featured_cache (name TEXT PRIMARY KEY, payload TEXT)')

    def get_chart(self):
        with self.connect() as db:
            row=db.execute("SELECT payload FROM featured_cache WHERE name='steam'").fetchone()
        return json.loads(row[0]) if row else None

    def put_chart(self,snapshot):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO featured_cache VALUES ('steam',?)",(json.dumps(snapshot),))

    def latest_featured(self):
        with self.connect() as db:
            row=db.execute('SELECT slot,state,message_id FROM featured_posts ORDER BY slot DESC LIMIT 1').fetchone()
        return tuple(row) if row else None

    def claim_featured(self,slot):
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO featured_posts VALUES (?, 'reserved', NULL)",(slot,)).rowcount==1

    def finish_featured(self,slot,message_id):
        with self.connect() as db:
            db.execute("UPDATE featured_posts SET state='posted',message_id=? WHERE slot=?",(message_id,slot))

    def claim_panel(self,channel_id):
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO panels VALUES (?, 'reserved', NULL)",(channel_id,)).rowcount == 1

    def finish_panel(self,channel_id,message_id):
        with self.connect() as db:
            db.execute("UPDATE panels SET state='posted', message_id=? WHERE channel_id=?",(message_id,channel_id))

    def panel_status(self,channel_id):
        with self.connect() as db:
            row=db.execute('SELECT state,message_id FROM panels WHERE channel_id=?',(channel_id,)).fetchone()
            return tuple(row) if row else None

    def get(self,user_id):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM preferences WHERE user_id=?',(user_id,)).fetchone()
        return json.loads(row[0]) if row else json.loads(json.dumps(DEFAULT))

    def put(self,user_id,data):
        validate(data)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',(user_id,json.dumps(data,ensure_ascii=False)))


def tags(article):
    # Conservative routing: 4Gamers is mixed, not automatically PC.
    text=normalized(article['title']+' '+article['summary'])
    platforms=set()
    if article['source']=='ps': platforms.add('ps')
    if article['source']=='xbox': platforms.add('xbox')
    for platform, pattern in [('ps',r'playstation|\bps[45]\b'),('xbox',r'xbox'),('pc',r'\bpc\b|steam|epic games')]:
        if re.search(pattern,text): platforms.add(platform)
    stores={s for s in ('steam','epic') if re.search(r'\b'+s+r'\b',text)}
    offer=article.get('offer')
    kind=offer['kind'] if offer else 'member' if any(w in text for w in ('game pass','playstation plus','ps plus')) else 'news'
    return platforms,stores,kind


def matches(article,pref):
    platforms,stores,kind=tags(article)
    text=normalized(article['title']+' '+article['summary'])
    return (bool(platforms & set(pref['platforms'])) and kind in pref['kinds']
            and ('any' in pref['stores'] or bool(stores & set(pref['stores'])))
            and (not pref['include'] or any(normalized(w) in text for w in pref['include']))
            and not any(normalized(w) in text for w in pref['exclude']))


def personal_preview(store,config,sources,pref,now):
    # Filter BEFORE max-eight ranking, while keeping admin exclusions and dedup.
    class PersonalConfig:
        max_items=8
        offers=config.offers
        def score(self,article):
            enriched=dict(article,offer=self.offers.get(article['link']))
            score=config.score(article)
            return score if score is not None and matches(enriched,pref) else None
    return store.preview(PersonalConfig(),sources,now,snapshot=True)


def fixtures(now):
    rows=[]
    for key,title,source,kind in [
        ('ps','PS5 PlayStation Plus 合作遊戲','ps','member'),
        ('xbox','Xbox Game Pass 合作遊戲','xbox','member'),
        ('steam','PC Steam 合作遊戲 永久限免','4gamers','keep'),
        ('epic','PC Epic Games 合作遊戲 永久限免','4gamers','keep'),
        ('trial','PC Steam 免費週末 限時試玩','4gamers','trial'),
        ('news','PC Steam 合作遊戲 更新新聞','4gamers','news'),
        ('hardware','PC 硬件 顯示卡新聞','4gamers','news')]:
        rows.append(dict(key=key,title='【虛構範例】'+title,source=source,summary='只供測試篩選，不是真實優惠。',link='https://example.com/'+key,published=now,
                         offer=None if kind=='news' else dict(kind=kind,region='虛構測試地區',deadline=now+86400)))
    return rows
