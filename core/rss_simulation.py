"""Explicit fictional scenarios in a disposable DB, never the delivery database."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from core.rss_digest import DigestConfig, DigestStore, HK


def scenarios(now):
    midday = datetime.fromtimestamp(now,HK).replace(hour=12,minute=30,second=0,microsecond=0)
    evening = midday.replace(hour=19,minute=0)
    def article(key, **changes):
        return dict(dict(key=key,title='【虛構範例】PC 遊戲 '+key,summary='虛構資料，用作測試摘要篩選及版面。',
                         link='https://example.com/'+key,published=midday.timestamp()-60),**changes)
    cfg=DigestConfig.from_dict(dict(exclude_any=['手遊'],boost_any=['限免'],offers={
        'https://example.com/keep':dict(kind='keep',region='虛構測試地區',verified=True,ends_at=(midday+timedelta(days=1)).isoformat()),
        'https://example.com/ending':dict(kind='trial',region='虛構測試地區',verified=True,ends_at=midday.replace(hour=18).isoformat()),
        'https://example.com/expired':dict(kind='keep',region='虛構測試地區',verified=True,ends_at=midday.replace(hour=12,minute=0).isoformat())}))
    articles=[article('keep',title='【虛構範例】PC 遊戲 A 限免'),article('duplicate',link='https://example.com/keep?utm_source=test',title='【虛構範例】PC 遊戲 A 限免'),
              article('mobile',title='【虛構範例】手遊廣告'),article('ending'),article('expired')]
    articles += [article('news'+str(i)) for i in range(10)]
    with TemporaryDirectory() as tmp:
        store=DigestStore(Path(tmp)/'fixtures.sqlite3')
        store.ingest('ps',[],midday.timestamp()-120)
        store.ingest('ps',articles,midday.timestamp())
        digest=store.claim_batch(cfg,{'ps'},evening.timestamp())
        reminder=store.claim_batch(cfg,{'ps'},midday.timestamp())
        repeat=store.claim_batch(cfg,{'ps'},midday.timestamp()+60)
        keys=[a['key'] for a in digest['articles']]
        checks={'摘要最多8條':len(keys)==8,'排除手遊': 'mobile' not in keys,
                '相同新聞只留一條':len(set(keys)&{'keep','duplicate'})==1,
                '已到期優惠不出': 'expired' not in keys,
                '到期提醒只選正確優惠':[a['key'] for a in reminder['articles']]==['ending'],
                '重跑不重發':repeat is None}
        return {'digest':digest,'reminder':reminder,'checks':checks,
                'midday':midday.timestamp(),'evening':evening.timestamp()}
