from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.fc27_updates import HUB, NEWS, PreviewLedger
from core.gta_translation import GTA_CHANNEL_ID, LEASE_SECONDS, MONTHLY_LIMIT, TranslationQueue
from core.sqlite_storage import connect_sqlite
from scripts.preview_fc27_updates import examples, preview

NOW = 1_795_651_200


class FC27PreviewTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "translation.sqlite3"
        self.store = PreviewLedger(self.path)
        self.old, self.old_hub, self.pitch, self.mirror, self.patch = examples()

    def baseline(self):
        self.assertEqual(self.store.ingest([self.old], [self.old_hub]), 0)
        self.assertIsNone(self.store.claim(NOW))

    def test_preview_entrypoint_baseline_mirrors_distinct_articles_and_demo(self):
        cards, calls, chars = preview(self.path)
        self.assertEqual((len(cards), calls, chars), (2, 2, len(self.pitch.brief) + len(self.patch.brief)))
        self.assertIn(self.pitch.url + "#:~:text=The%20player%20shown%20in%20this%20video", cards[1])
        self.assertIn(self.patch.url, cards[0])
        self.assertIn("The Grounds", cards[1])
        self.assertNotIn("@", "".join(cards))
        self.assertEqual(preview(self.path), (cards, 0, chars))

    def test_snapshot_error_preserves_baseline_and_admits_no_partial_new_items(self):
        for bad in ([], [self.old_hub] * 101, [replace(self.old_hub, rank="Member")],
                    [replace(self.old_hub, author="EA_Community_Fan")],
                    [replace(self.old_hub, url=HUB.replace("/blog/", "/discussions/") + "fc/9")]):
            with self.subTest(bad=bool(bad)), self.assertRaises(ValueError):
                self.store.ingest([self.old], bad)
        self.baseline()
        for bad in (replace(self.mirror, canonical="https://example.org/fc"),
                    replace(self.mirror, url=self.mirror.url + "?redirect=1"),
                    replace(self.mirror, brief="@everyone"), replace(self.mirror, brief="a" * 361),
                    replace(self.mirror, title="General news", canonical="")):
            with self.assertRaises(ValueError):
                self.store.ingest([self.pitch], [bad])
            self.assertIsNone(self.store.claim(NOW))

    def test_hub_first_then_website_promotes_canonical_without_duplicate(self):
        self.baseline()
        forum_first = replace(self.mirror, canonical="")
        self.assertEqual(self.store.ingest([self.old], [forum_first]), 1)
        identity, _ = self.store.claim(NOW)
        self.store.finish(identity, "預覽")
        self.assertIn(forum_first.url, self.store.cards()[0])
        reopened = PreviewLedger(self.path)
        self.assertEqual(reopened.ingest([self.pitch], [self.old_hub]), 0)
        self.assertIsNone(reopened.claim(NOW))
        self.assertIn(self.pitch.url, reopened.cards()[0])
        self.assertNotIn(forum_first.url, reopened.cards()[0])

    def test_website_first_then_hub_and_different_headline_with_explicit_canonical(self):
        self.baseline()
        self.store.ingest([self.pitch], [self.old_hub])
        self.assertEqual(self.store.ingest([self.old], [self.mirror]), 0)
        self.assertEqual(self.store.ingest([self.old], [replace(self.mirror, title="November developer notes")]), 0)
        other = replace(self.pitch, title="Clubs in v1.3.0", url=NEWS + "clubs-in-v1-3")
        self.assertEqual(self.store.ingest([other], [self.old_hub]), 1)

    def test_same_forum_article_survives_changing_title_canonical_and_slug_in_either_order(self):
        explicit = replace(self.mirror, title="November developer notes")
        typed = replace(self.mirror, canonical="", url=HUB + "new-pitch-notes-slug/13897390")
        for first, later in ((explicit, typed), (typed, explicit)):
            with self.subTest(first=first.title), TemporaryDirectory() as tmp:
                path = Path(tmp) / "preview.sqlite3"
                ledger = PreviewLedger(path)
                ledger.ingest([self.old], [self.old_hub])
                self.assertEqual(ledger.ingest([self.old], [first]), 1)
                job, brief = ledger.claim(NOW)
                ledger.finish(job, "已翻譯")
                reopened = PreviewLedger(path)
                self.assertEqual(reopened.ingest([self.old], [later]), 0)
                self.assertEqual(reopened.ingest([self.pitch], [first, later]), 0)
                self.assertIsNone(reopened.claim(NOW))
                self.assertEqual(len(reopened.cards()), 1)
                self.assertIn(self.pitch.url, reopened.cards()[0])
                self.assertTrue(reopened.cards()[0].startswith(self.pitch.title))
                with connect_sqlite(path) as db:
                    self.assertEqual(db.execute("SELECT characters FROM usage").fetchone()[0], len(brief))

    def test_shared_last_characters_are_atomic_and_quota_fallback_keeps_source(self):
        queue = TranslationQueue(self.path)
        queue.add(1, 11, "a" * (MONTHLY_LIMIT - len(self.pitch.brief)), channel_id=GTA_CHANNEL_ID)
        queue.claim(NOW)
        self.baseline()
        self.store.ingest([self.pitch], [self.mirror])
        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: PreviewLedger(self.path).claim(NOW), range(2)))
        self.assertEqual(sum(bool(j) for j in jobs), 1)
        self.store.ingest([self.pitch], [self.patch])
        self.assertIsNone(self.store.claim(NOW))
        self.assertIn(self.patch.url, self.store.cards()[0])
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone()[0], MONTHLY_LIMIT)

    def test_timeout_restart_keeps_link_and_never_translates_again(self):
        self.baseline()
        self.store.ingest([self.pitch], [self.mirror])
        identity, _ = self.store.claim(NOW)
        recovered = PreviewLedger(self.path)
        self.assertIsNone(recovered.claim(NOW + LEASE_SECONDS))
        recovered.finish(identity, "過期結果")
        self.assertNotIn("過期結果", recovered.cards()[0])
        self.assertIn(self.pitch.url, recovered.cards()[0])

    def test_provider_unavailable_keeps_both_sources(self):
        cards, _, _ = preview(self.path, source_only=True)
        self.assertTrue(all("繁中摘要暫未提供" in card for card in cards))
        self.assertIn(self.patch.url, cards[0])
        self.assertIn(self.pitch.url, cards[1])


class FC27PollingTest(unittest.IsolatedAsyncioTestCase):
    async def test_hourly_poll_retry_backoff_size_limit_and_atomic_baseline(self):
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock
        from core.fc27_updates import poll_indexes
        from core.rss_trial import MAX_BYTES

        old, old_hub, *_ = examples()
        calls = []
        mode = "transient"
        sleep = AsyncMock()

        @asynccontextmanager
        async def open_stream(source):
            async def chunks():
                calls.append(source)
                if source == "hub" and mode == "transient":
                    raise TimeoutError()
                if source == "hub" and mode == "oversize":
                    yield bytes(MAX_BYTES)
                    yield b"x"
                else:
                    yield b"normalized"
            yield chunks()

        def parse(source, body):
            self.assertEqual(body, b"normalized")
            return [old] if source == "news" else [old_hub]

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "preview.sqlite3"
            ledger = PreviewLedger(path)
            with self.assertRaises(TimeoutError):
                await poll_indexes(ledger, NOW, open_stream, parse, sleep=sleep)
            self.assertEqual(calls, ["news", "hub", "hub", "hub"])
            self.assertEqual([c.args[0] for c in sleep.await_args_list], [1, 2])
            self.assertIsNone(await poll_indexes(PreviewLedger(path), NOW + 3599, open_stream, parse))
            mode = "oversize"
            with self.assertRaisesRegex(ValueError, "byte limit"):
                await poll_indexes(ledger, NOW + 3600, open_stream, parse)
            with connect_sqlite(path) as db:
                self.assertFalse(db.execute("SELECT 1 FROM fc27_preview").fetchall())
            mode = "ok"
            self.assertEqual(await poll_indexes(ledger, NOW + 7200, open_stream, parse), 0)
