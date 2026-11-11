"""Scheduled, bounded digests with literal keyword filters and durable batches."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from core.rss_delivery import DeliveryStore, SOURCE_IDS, safe_link

HK = ZoneInfo('Asia/Hong_Kong')
OFFER_LABELS = {'keep': '永久領取', 'trial': '限時試玩', 'member': '會員福利', 'f2p': '本身免費'}


def normalized(value):
    return unicodedata.normalize('NFKC', value).casefold()


def canonical_url(value):
    u = urlsplit(value)
    query = [(k,v) for k,v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'fbclid','gclid'}]
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path or '/',urlencode(sorted(query)),''))


def display_link(value):
    return canonical_url(value).replace('(', '%28').replace(')', '%29').replace('>', '%3E').replace('<', '%3C')


def identity(article):
    # Exact normalized titles only: no fuzzy merging of different updates.
    title = re.sub(r'\s+', ' ', normalized(article['title'])).strip()
    return canonical_url(article['link']), title if len(title) >= 12 else ''


@dataclass
class DigestConfig:
    channel_id: int = 0
    enabled: bool = False
    simulation: bool = True
    max_items: int = 8
    include_any: list[str] = field(default_factory=list)
    exclude_any: list[str] = field(default_factory=list)
    boost_any: list[str] = field(default_factory=list)
    offers: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('unknown digest configuration fields')
        c = cls(**data)
        if type(c.simulation) is not bool or type(c.enabled) is not bool or type(c.channel_id) is not int or c.channel_id < 0:
            raise ValueError('invalid enabled/channel_id')
        if c.enabled and not c.channel_id:
            raise ValueError('enabled digest requires a destination channel')
        if type(c.max_items) is not int or not 1 <= c.max_items <= 8:
            raise ValueError('max_items must be 1..8')
        for values in (c.include_any,c.exclude_any,c.boost_any):
            if not isinstance(values,list) or len(values)>100 or any(not isinstance(x,str) or not x.strip() or len(x)>100 for x in values):
                raise ValueError('keyword lists require at most 100 non-empty literal strings')
        if not isinstance(c.offers,dict) or len(c.offers)>100:
            raise ValueError('offers must be a bounded URL mapping')
        offers = {}
        for url, offer in c.offers.items():
            if not safe_link(url) or not isinstance(offer,dict):
                raise ValueError('invalid offer URL/metadata')
            if set(offer) != {'kind','ends_at','verified','region'} or offer['kind'] not in OFFER_LABELS or offer['verified'] is not True:
                raise ValueError('offer needs verified kind, region and deadline')
            if not isinstance(offer['region'],str) or not 1<=len(offer['region'])<=80:
                raise ValueError('offer needs region eligibility')
            end = datetime.fromisoformat(offer['ends_at'])
            if end.tzinfo is None:
                raise ValueError('offer deadline needs timezone')
            offers[canonical_url(url)] = dict(offer, deadline=end.timestamp())
        c.offers = offers
        return c

    def score(self, article):
        text = normalized(article['title']+' '+article['summary'])
        if any(normalized(w) in text for w in self.exclude_any):
            return None
        if self.include_any and not any(normalized(w) in text for w in self.include_any):
            return None
        return sum(normalized(w) in text for w in self.boost_any)


def slot(now):
    local = datetime.fromtimestamp(now,HK)
    # 15-minute dispatch window; no late catch-up floods after downtime.
    if local.hour == 19 and local.minute < 15:
        return local.date().isoformat()+':digest', 'digest'
    if local.hour == 12 and 30 <= local.minute < 45:
        return local.date().isoformat()+':reminder', 'reminder'
    return None


def excerpt(value, limit=150):
    value = re.sub(r'\s+',' ', re.sub(r'<[^>]*>','',value)).strip()
    return value[:limit] + ('…' if len(value)>limit else '')


class DigestStore(DeliveryStore):
    def __init__(self,path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE INDEX IF NOT EXISTS digest_article_date ON articles(state,published);
                CREATE INDEX IF NOT EXISTS digest_article_link ON articles(link);
                CREATE TABLE IF NOT EXISTS digest_batches (
                    slot TEXT PRIMARY KEY, kind TEXT, state TEXT,
                    payload TEXT, attempts INTEGER, next_attempt REAL, detail TEXT);
                CREATE TABLE IF NOT EXISTS digest_seen (identity TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS digest_reminded (url TEXT PRIMARY KEY);
            ''')

    def ingest(self,source,articles,now):
        # Digest filters are administrator-controlled, replacing the legacy
        # case-sensitive 4Gamers regex. Keep the same timestamp/safety gates.
        if source not in SOURCE_IDS: raise ValueError('unknown source')
        from core.rss_trial import decision
        added = 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            baseline = db.execute('SELECT 1 FROM baseline WHERE source=?',(source,)).fetchone() is None
            for a in articles:
                state = 'baseline' if baseline else decision('ps',a,now)
                if not safe_link(a['link']) or any(ord(c)<32 for c in a['link']) or len(display_link(a['link']))>500: state = 'invalid_link'
                if state == 'would_deliver': state='pending'
                cur=db.execute('INSERT OR IGNORE INTO articles (source,key,title,summary,link,published,state) VALUES (?,?,?,?,?,?,?)',
                               (source,a['key'],a['title'],a['summary'],canonical_url(a['link']) if state!='invalid_link' else a['link'],a['published'],state))
                added += cur.rowcount if state=='pending' else 0
            db.execute('INSERT OR IGNORE INTO baseline VALUES (?)',(source,))
        return added

    def select(self,db,kind,config,sources,now,snapshot=False):
        if kind == 'digest':
            states = "('pending','baseline','sent')" if snapshot else "('pending')"
            rows = [dict(r) for r in db.execute("SELECT * FROM articles WHERE state IN "+states+" AND published>=? AND published<=? ORDER BY published DESC,source,key",(now-86400,now+300))]
        else:
            if not config.offers: return []
            marks = ','.join('?' for _ in config.offers)
            rows = [dict(r) for r in db.execute("SELECT * FROM articles WHERE state IN ('pending','sent') AND link IN ("+marks+") ORDER BY published DESC,source,key",tuple(config.offers))]
        seen = {r[0] for r in db.execute('SELECT identity FROM digest_seen')} if kind=='digest' and not snapshot else set()
        reminded = {r[0] for r in db.execute('SELECT url FROM digest_reminded')}
        if kind=='reminder': seen.update(reminded)
        ranked = []
        evening = datetime.fromtimestamp(now,HK).replace(hour=19,minute=0,second=0,microsecond=0).timestamp()
        for a in rows:
            if a['source'] not in sources: continue
            score=config.score(a)
            if score is None: continue
            offer=config.offers.get(canonical_url(a['link']))
            if offer and offer['deadline'] <= now: continue
            if kind=='digest':
                if (not snapshot and a['state'] != 'pending') or a['published'] < now-86400 or a['published'] > now+300: continue
            else:
                if not offer or offer['kind']=='f2p' or not now < offer['deadline'] <= evening: continue
                if canonical_url(a['link']) in reminded: continue
            a['offer']=offer
            ranked.append((score+(10 if offer else 0),a))
        ranked.sort(key=lambda x:(-x[0],-x[1]['published'],x[1]['source'],x[1]['key']))
        # Union exact URL/title aliases before ranking, so A~B and B~C cannot
        # leak two copies when the bridge article ranks below A and C.
        parent = {}
        def root(value):
            parent.setdefault(value, value)
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value
        for _,a in ranked:
            ids = [value for value in identity(a) if value]
            root(ids[0])
            for value in ids[1:]: parent[root(value)] = root(ids[0])
        groups = {}
        for value in parent: groups.setdefault(root(value), set()).add(value)
        selected=[]
        for _,a in ranked:
            ids = groups[root(identity(a)[0])]
            if ids & seen: continue
            seen.update(ids)
            a['_identities'] = sorted(ids)
            selected.append(a)
            if len(selected)>=min(config.max_items,4 if kind=='reminder' else 8): break
        return selected

    def preview(self, config, sources, now, kind='digest', snapshot=False):
        with self.connect() as db:
            return self.select(db,kind,config,sources,now,snapshot=snapshot)

    def claim_batch(self, config, sources, now):
        current=slot(now)
        if not current: return None
        name,kind=current
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM digest_batches WHERE slot=?',(name,)).fetchone()
            if old:
                if old['state']!='retry' or old['next_attempt']>now: return None
                payload=json.loads(old['payload'])
                # A known-unsent batch can safely be abandoned if filters or
                # enabled sources changed while it waited for a retry.
                if any(a['source'] not in sources or config.score(a) is None or a.get('offer') != config.offers.get(canonical_url(a['link'])) or (a.get('offer') and a['offer']['deadline']<=now) for a in payload):
                    db.execute("UPDATE digest_batches SET state='cancelled' WHERE slot=?",(name,))
                    return None
                db.execute("UPDATE digest_batches SET state='sending',attempts=attempts+1 WHERE slot=?",(name,))
            else:
                payload=self.select(db,kind,config,sources,now)
                if not payload: return None
                db.execute('INSERT INTO digest_batches VALUES (?,?,?,?,1,0,?)',(name,kind,'sending',json.dumps(payload,ensure_ascii=False),''))
                for a in payload:
                    if kind=='digest':
                        db.execute("UPDATE articles SET state='sending' WHERE source=? AND key=?",(a['source'],a['key']))
                        for value in a['_identities']:
                            if value: db.execute('INSERT OR IGNORE INTO digest_seen VALUES (?)',(value,))
                    else:
                        for value in a['_identities']:
                            db.execute('INSERT OR IGNORE INTO digest_reminded VALUES (?)',(value,))
            return {'slot':name,'kind':kind,'articles':payload}

    def finish_batch(self,name,outcome,now,detail=''):
        if outcome not in {'sent','retry','failed','uncertain'}: raise ValueError('invalid outcome')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM digest_batches WHERE slot=?',(name,)).fetchone()
            if not old or old['state']!='sending': raise ValueError('batch not claimed')
            if outcome=='retry' and old['attempts']>=3: outcome='failed'
            db.execute('UPDATE digest_batches SET state=?,next_attempt=?,detail=? WHERE slot=?',
                       (outcome,now+60*2**(old['attempts']-1),detail[:240],name))
            if old['kind']=='digest' and outcome!='retry':
                for a in json.loads(old['payload']):
                    db.execute('UPDATE articles SET state=? WHERE source=? AND key=?',(outcome,a['source'],a['key']))

    def batch_report(self):
        with self.connect() as db:
            return [tuple(r) for r in db.execute('SELECT slot,state,attempts FROM digest_batches ORDER BY slot DESC LIMIT 8')]
