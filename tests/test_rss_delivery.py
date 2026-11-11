import tempfile
import unittest
from pathlib import Path
from core.rss_delivery import DeliveryStore, enabled_sources, safe_link


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'rss.db'
        self.store = DeliveryStore(self.path)
        self.now = 200000

    def a(self, key, **changes):
        a = dict(key=key,title='Game',summary='PC',link='https://example.com/'+key,published=self.now)
        return dict(a, **changes)

    def test_activation_validation_and_link_safety(self):
        self.assertFalse(enabled_sources(''))
        self.assertEqual(enabled_sources('ps,xbox'), {'ps','xbox'})
        with self.assertRaises(ValueError): enabled_sources('steam')
        for link in ('http://example.com','javascript:alert(1)','https://user:pass@example.com','https://['):
            self.assertFalse(safe_link(link))

    def test_baseline_restart_and_ambiguous_send_no_duplicate(self):
        self.assertEqual(self.store.ingest('ps',[self.a('old')],self.now),0)
        self.assertEqual(self.store.ingest('ps',[self.a('old'),self.a('new')],self.now+1),1)
        claimed = self.store.claim('ps',self.now+2)
        self.assertEqual(claimed['key'],'new')
        restarted = DeliveryStore(self.path)
        self.assertIsNone(restarted.claim('ps',self.now+3))
        restarted.finish('ps','new','uncertain',self.now+3)
        self.assertIsNone(restarted.claim('ps',self.now+4))
        self.assertEqual(restarted.ingest('ps',[self.a('new')],self.now+5),0)

    def test_cap_is_rolling_and_per_source(self):
        for source in ('ps','xbox'): self.store.ingest(source,[],self.now)
        self.store.ingest('ps',[self.a(str(i)) for i in range(51)],self.now)
        for i in range(50):
            a=self.store.claim('ps',self.now+i)
            self.assertIsNotNone(a)
            self.store.finish('ps',a['key'],'sent',self.now+i)
        self.assertIsNone(self.store.claim('ps',self.now+50))
        self.store.ingest('xbox',[self.a('x')],self.now+50)
        self.assertIsNotNone(self.store.claim('xbox',self.now+50))
        self.assertIsNone(self.store.claim('ps',self.now+86401))  # remaining story expired

    def test_retry_backoff_and_attempt_bound(self):
        self.store.ingest('ps',[],self.now)
        self.store.ingest('ps',[self.a('a')],self.now)
        now=self.now
        for attempt in range(5):
            a=self.store.claim('ps',now)
            self.assertIsNotNone(a)
            self.store.finish('ps','a','retry',now)
            self.assertIsNone(self.store.claim('ps',now+1))
            now += 1800
        self.assertIn(('ps','failed',1),self.store.report())
        self.assertIsNone(self.store.claim('ps',now))

    def test_filter_and_dates_and_invalid_links(self):
        self.store.ingest('4gamers',[],self.now)
        self.store.ingest('4gamers',[self.a('old',published=1),self.a('invalid',link='file:///etc/passwd'),self.a('no',summary=''),self.a('good')],self.now)
        self.assertEqual(self.store.claim('4gamers',self.now)['key'],'good')
        self.assertIsNone(self.store.claim('4gamers',self.now))

if __name__ == '__main__': unittest.main()
