import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from core.rss_digest import DigestConfig, DigestStore, HK, slot


def ts(day=12,hour=19,minute=0):
    return datetime(2026,11,day,hour,minute,tzinfo=HK).timestamp()


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'rss.db'
        self.store=DigestStore(self.path)
        self.config=DigestConfig.from_dict({})
        self.sources={'ps','xbox','4gamers'}
        for source in self.sources: self.store.ingest(source,[],ts(hour=10))

    def a(self,key,**changes):
        return dict(dict(key=key,title='Important gaming news '+key,summary='PC gameplay update',link='https://example.com/'+key,published=ts(hour=11)),**changes)

    def test_schedule_and_no_catchup(self):
        self.assertEqual(slot(ts())[1],'digest')
        self.assertEqual(slot(ts(hour=12,minute=30))[1],'reminder')
        for hour,minute in ((12,29),(12,45),(18,59),(19,15),(23,0)):
            self.assertIsNone(slot(ts(hour=hour,minute=minute)))
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,ts()))
        self.assertEqual(self.store.batch_report(),[])

    def test_filters_priority_and_exact_cross_source_dedup(self):
        self.config=DigestConfig.from_dict({'include_any':['PC'],'exclude_any':['手遊'],'boost_any':['FC'],'max_items':8})
        articles=[self.a('a'),self.a('b',title='FC patch'),self.a('c',summary='PC 手遊'),self.a('d',summary='console')]
        self.store.ingest('ps',articles,ts(hour=11))
        self.store.ingest('xbox',[self.a('dup',link='https://example.com/a?utm_source=x')],ts(hour=11))
        self.store.ingest('4gamers',[self.a('other',title=articles[0]['title'])],ts(hour=11))
        batch=self.store.claim_batch(self.config,self.sources,ts())
        self.assertEqual([a['key'] for a in batch['articles']],['b','other'])
        self.assertEqual(len(batch['articles']),2)
        self.assertIsNone(DigestStore(self.path).claim_batch(self.config,self.sources,ts(minute=1)))
        self.store.finish_batch(batch['slot'],'sent',ts())
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,ts(minute=2)))

    def test_eight_item_cap_and_preview_does_not_claim(self):
        self.store.ingest('ps',[self.a(str(i)) for i in range(20)],ts(hour=11))
        self.assertEqual(len(self.store.preview(self.config,self.sources,ts())),8)
        self.assertEqual(self.store.batch_report(),[])
        batch=self.store.claim_batch(self.config,self.sources,ts())
        self.assertEqual(len(batch['articles']),8)
        self.store.finish_batch(batch['slot'],'uncertain',ts())
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,ts(minute=1)))

    def offer_config(self,deadline,kind='keep'):
        return DigestConfig.from_dict({'offers':{'https://example.com/deal':{'verified':True,'kind':kind,'region':'香港','ends_at':deadline}}})

    def test_reminder_once_even_if_already_in_digest(self):
        self.store.ingest('ps',[self.a('deal',published=ts(day=11,hour=18))],ts(day=11,hour=18))
        cfg=self.offer_config('2026-11-12T18:00:00+08:00')
        first=self.store.claim_batch(cfg,self.sources,ts(day=11))
        self.store.finish_batch(first['slot'],'sent',ts(day=11))
        batch=self.store.claim_batch(cfg,self.sources,ts(hour=12,minute=30))
        self.assertEqual(batch['kind'],'reminder')
        self.assertEqual(batch['articles'][0]['offer']['kind'],'keep')
        self.store.finish_batch(batch['slot'],'sent',ts(hour=12,minute=30))
        self.assertIsNone(self.store.claim_batch(cfg,self.sources,ts(hour=12,minute=31)))
        self.assertEqual(self.store.preview(cfg,self.sources,ts(hour=12,minute=32),'reminder'),[])

    def test_no_guessing_deadlines_or_expired_free_to_play(self):
        self.store.ingest('ps',[self.a('deal',title='Free game')],ts(hour=11))
        now=ts(hour=12,minute=30)
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,now))
        for deadline,kind in [('2026-11-12T12:00:00+08:00','keep'),('2026-11-12T20:00:00+08:00','keep'),('2026-11-12T18:00:00+08:00','f2p')]:
            self.assertIsNone(self.store.claim_batch(self.offer_config(deadline,kind),self.sources,now))

    def test_retry_bound_and_restart(self):
        self.store.ingest('ps',[self.a('a')],ts(hour=11))
        for minute in (0,1,3):
            store=DigestStore(self.path)
            b=store.claim_batch(self.config,self.sources,ts(minute=minute))
            self.assertIsNotNone(b)
            store.finish_batch(b['slot'],'retry',ts(minute=minute))
        self.assertEqual(self.store.batch_report()[0][1],'failed')
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,ts(minute=7)))

    def test_invalid_config_and_link(self):
        for config in ({'max_items':9},{'enabled':True},{'exclude_any':['']},{'include_any':'PC'},{'unknown':1}):
            with self.assertRaises(ValueError): DigestConfig.from_dict(config)
        with self.assertRaises(ValueError): self.offer_config('2026-11-12T18:00:00')
        self.store.ingest('ps',[self.a('a',link='https://example.com/'+('a'*600))],ts(hour=11))
        self.assertIsNone(self.store.claim_batch(self.config,self.sources,ts()))

if __name__=='__main__': unittest.main()
