import tempfile
import unittest
from pathlib import Path

from core.rss_trial import TrialStore, TRIAL_SECONDS, decision, parse_feed


class RSSTrialTests(unittest.TestCase):
    def article(self, **kwargs):
        return dict(key="abc", title="news", summary="", link="https://example.org/1", published=100000, **kwargs)

    def test_rss_atom_and_bad_xml(self):
        rss = b'<rss><channel><item><guid>one</guid><title>Game</title><pubDate>Tue, 10 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        self.assertIsNotNone(parse_feed(rss)[0]["published"])
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><link href="https://example.org/x"/><updated>2026-11-10T12:00:00Z</updated></entry></feed>'
        self.assertEqual(parse_feed(atom)[0]["link"], "https://example.org/x")
        for bad in (b'<html/>', b'<!DOCTYPE rss><rss/>', b'<rss>'):
            with self.assertRaises(ValueError):
                parse_feed(bad)

    def test_filters_are_any_and_case_sensitive(self):
        a = self.article()
        self.assertEqual(decision("4gamers", a, 100001), "filtered")
        a["summary"] = "PC"
        self.assertEqual(decision("4gamers", a, 100001), "would_deliver")
        a["summary"] = "pc"
        self.assertEqual(decision("4gamers", a, 100001), "filtered")
        a["title"] = "免費"
        self.assertEqual(decision("4gamers", a, 100001), "would_deliver")
        self.assertEqual(decision("xbox", self.article(), 100001), "would_deliver")

    def test_dates(self):
        a = self.article()
        self.assertEqual(decision("ps", a, 200000), "older_than_1_day")
        a["published"] = None
        self.assertEqual(decision("ps", a, 200000), "missing_date")

    def test_baseline_restart_dedup_error_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trial.db"
            store = TrialStore(path)
            store.record("ps", [], status="failed", now=100001)
            self.assertEqual(store.record("ps", [self.article()], now=100001), 1)
            store = TrialStore(path)
            self.assertEqual(store.record("ps", [self.article()], now=100002), 0)
            a = self.article()
            a["key"] = "new"
            store.record("ps", [a], now=100002)
            self.assertIn(("ps", "baseline", 1), store.report()["decisions"])
            self.assertIn(("ps", "would_deliver", 1), store.report()["decisions"])
            start = store.report()["start"]
            self.assertFalse(store.active(start + TRIAL_SECONDS))


if __name__ == "__main__":
    unittest.main()
