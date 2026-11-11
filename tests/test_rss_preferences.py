import tempfile
import unittest
from pathlib import Path
from core.rss_preferences import PreferenceStore, DEFAULT, fixtures, matches, personal_preview, tags
from core.rss_digest import DigestStore, DigestConfig


class PreferencesTests(unittest.TestCase):
    def test_persistence_isolation_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prefs.db'
            store=PreferenceStore(path)
            pref=store.get(1)
            pref.update(platforms=['pc'],stores=['epic'],kinds=['keep'],exclude=['手遊'])
            store.put(1,pref)
            self.assertEqual(PreferenceStore(path).get(1),pref)
            self.assertEqual(store.get(2),DEFAULT)
            with self.assertRaises(ValueError): store.put(1,dict(pref,platforms=[]))
            self.assertEqual(store.get(1),pref)

    def test_offer_types_store_platform_and_exclusion(self):
        rows=fixtures(2000000000)
        pref=dict(DEFAULT,platforms=['pc'],stores=['epic'],kinds=['keep'])
        self.assertEqual([a['key'] for a in rows if matches(a,pref)],['epic'])
        pref.update(stores=['steam'],kinds=['trial'])
        self.assertEqual([a['key'] for a in rows if matches(a,pref)],['trial'])
        pref.update(include=['合作'],exclude=['合作'])
        self.assertFalse(any(matches(a,pref) for a in rows))
        self.assertEqual(tags(dict(title='動畫新聞',summary='',source='4gamers'))[0],set())
        self.assertEqual(tags(dict(title='PC Steam 限免傳聞',summary='',source='4gamers'))[2],'news')

    def test_filter_before_cap_and_read_only_dedup(self):
        now=2000000000
        with tempfile.TemporaryDirectory() as tmp:
            store=DigestStore(Path(tmp)/'news.db')
            rows=[dict(key=str(i),title='PS5 unrelated news '+str(i),summary='',link='https://example.com/'+str(i),published=now) for i in range(12)]
            rows += [dict(key='pc',title='PC Steam 合作遊戲更新',summary='',link='https://example.com/pc',published=now-1),dict(key='alias',title='PC Steam 合作遊戲更新',summary='',link='https://example.com/alias',published=now-2)]
            store.ingest('4gamers',rows,now)
            before=store.report()
            selected=personal_preview(store,DigestConfig(),{'4gamers'},dict(DEFAULT,platforms=['pc']),now)
            self.assertEqual(len(selected),1)
            self.assertEqual(selected[0]['key'],'pc')
            self.assertEqual(store.report(),before)
            self.assertEqual(store.batch_report(),[])
            self.assertEqual(personal_preview(store,DigestConfig(exclude_any=['合作']),{'4gamers'},dict(DEFAULT,platforms=['pc']),now),[])
