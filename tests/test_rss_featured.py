import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from core.rss_digest import DigestStore,DigestConfig,HK
from core.rss_preferences import DEFAULT,PreferenceStore
from core.rss_featured import highlights,parse_chart,chart_rows,verified_game


class FeaturedTests(unittest.TestCase):
    def test_calendar_boundaries_expiry_filter_and_dedup(self):
        now=datetime(2026,11,11,12,tzinfo=HK).timestamp()
        def article(key,title,date):
            return dict(key=key,title=title,summary='',link='https://example.com/'+key,published=datetime.fromisoformat(date).replace(tzinfo=HK).timestamp())
        with tempfile.TemporaryDirectory() as tmp:
            store=DigestStore(Path(tmp)/'news.db')
            store.ingest('ps',[],now)
            store.ingest('ps',[
                article('today','PS5 合作更新 AAA','2026-11-11T00:00'),
                article('duplicate','PS5 合作更新 AAA','2026-11-11T01:00'),
                article('yesterday','PS5 合作更新 BBB','2026-11-10T23:59'),
                article('month','PS5 合作更新 CCC','2026-11-01T00:00'),
                article('old','PS5 合作更新 DDD','2026-10-31T23:59'),
                article('future','PS5 合作更新 EEE','2026-11-12T00:00'),
                article('expired','PS5 合作更新 FFF','2026-11-11T02:00'),
            ],now)
            config=DigestConfig(offers={'https://example.com/expired':dict(kind='keep',deadline=now-1)})
            before=store.report()
            day=highlights(store,config,{'ps'},now,'today')
            month=highlights(store,config,{'ps'},now,'month')
            self.assertEqual(len(day),1)
            self.assertEqual(len(month),3)
            self.assertEqual(store.report(),before)
            self.assertEqual(store.batch_report(),[])
            self.assertEqual(highlights(store,config,{'ps'},now,'month',dict(DEFAULT,platforms=['pc'])),[])
            self.assertEqual(highlights(store,DigestConfig(exclude_any=['合作']),{'ps'},now,'month'),[])

    def test_chart_integrity_freshness_and_scope(self):
        self.assertFalse(verified_game(dict(type='game',name='Wallpaper Engine',genres=[{'id':'57'}])))
        self.assertTrue(verified_game(dict(type='game',name='Game',genres=[{'id':'1'}])))
        now=2000000000
        raw={'response':{'rollup_date':now-100,'ranks':[dict(rank=2,appid=730,peak_in_game=100),dict(rank=1,appid=570,peak_in_game=90)]}}
        asof,rows=parse_chart(raw,now)
        self.assertEqual([r['appid'] for r in rows],[570,730])
        snapshot=dict(asof=asof,fetched=now,rows=[dict(rows[0],name='Dota 2')])
        self.assertEqual(len(chart_rows(snapshot,DigestConfig(),now)),1)
        self.assertEqual(chart_rows(snapshot,DigestConfig(),now,dict(DEFAULT,platforms=['ps'])),[])
        self.assertEqual(chart_rows(snapshot,DigestConfig(),now,dict(DEFAULT,kinds=['keep'])),[])
        self.assertEqual(chart_rows(snapshot,DigestConfig(),now+86401),[])
        raw['response']['rollup_date']=now-8*86400
        with self.assertRaises(ValueError): parse_chart(raw,now)

    def test_snapshot_reservation_and_cache_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prefs.db'
            store=PreferenceStore(path)
            self.assertTrue(store.claim_featured('2026-11-11'))
            self.assertFalse(PreferenceStore(path).claim_featured('2026-11-11'))
            store.finish_featured('2026-11-11',123)
            self.assertEqual(store.latest_featured(),('2026-11-11','posted',123))
            store.put_chart({'rows':[],'asof':1,'fetched':2})
            self.assertEqual(PreferenceStore(path).get_chart()['fetched'],2)
