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


class FullLayoutTest(unittest.TestCase):
    @staticmethod
    def cli(*args):
        import subprocess
        import sys
        script = Path(__file__).resolve().parents[1] / "scripts" / "preview_fc27_updates.py"
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=10)

    def assert_full_output(self, plan, blocks):
        import discord
        from core.fc27_layout import BLUE, PURPLE, units
        self.assertEqual(plan["thread"]["parent"], "parent")
        self.assertIn("English Original", plan["thread"]["name"])
        for lang, color, messages in (("chinese", BLUE, [plan["parent"]]),
                                      ("english", PURPLE, plan["thread"]["messages"])):
            recovered = []
            for msg in messages:
                embeds = [discord.Embed.from_dict(payload) for payload in msg["embeds"]]
                self.assertLessEqual(len(embeds), 10)
                self.assertLessEqual(sum(units(e.title) + units(e.description) for e in embeds), 6000)
                self.assertEqual(msg["allowed_mentions"]["parse"], [])
                for e in embeds:
                    self.assertEqual(e.colour.value, color)
                    self.assertLessEqual(units(e.description), 4096)
                    self.assertEqual(e.title, "繁體中文｜全文" if lang == "chinese" else "English Original")
                    self.assertFalse(e.to_dict().get("image") or e.to_dict().get("video"))
                if "text_attachment" in msg:
                    recovered.append(msg["text_attachment"]["text"])
                else:
                    recovered.extend(e.description for e in embeds)
            # Independent reconstruction from fixture input. Check every character
            # and link, not just heading counts, a prefix, or one end marker.
            expected = []
            for block in blocks:
                text = getattr(block, lang)
                for pos, url in enumerate(block.links):
                    text = text.replace("{ref" + str(pos) + "}", f"<{url}>")
                expected.append(text)
            self.assertEqual("".join(recovered), "\n\n".join(expected))

    def test_latest_pitch_notes_topology_media_and_full_cli_output(self):
        import json
        from scripts.fc27_layout_fixture import pitch_notes_fixture
        result = self.cli("--json", "--metrics")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        blocks = pitch_notes_fixture()
        self.assert_full_output(plan, blocks)
        self.assertNotIn("text_attachment", plan["parent"])
        self.assertGreater(len(plan["parent"]["embeds"]), 1)
        self.assertGreater(len(plan["thread"]["messages"]), 1)
        headings = [b.key for b in blocks if b.key.endswith(".heading")]
        self.assertEqual([b.section for b in blocks if b.english.startswith("# ") and b.key != "title"],
                         ["gameplay", "grounds", "career", "tribute", "feedback"])
        self.assertEqual(len(headings), 5 + 19)
        toc = next(b for b in blocks if b.key == "contents")
        self.assertEqual([len(line) - len(line.lstrip()) for line in toc.english.splitlines()[1:]],
                         [0] + [2] * 13 + [0] + [2] * 3 + [0] + [2] * 3 + [0, 0])
        keys = [b.key for b in blocks]
        self.assertEqual(keys[:7], ["title", "cover", "opening.p1", "opening.p2", "opening.p3", "opening.p4", "contents"])
        expected_counts = {
            "opening": 4, "gameplay": 1, "dribbling": 2, "near-post": 2, "physicality": 1, "shoulder": 1,
            "flick": 1, "fouls": 2, "tackling": 1, "loose-ball": 1, "reach": 1, "recovery": 1, "midfield": 1,
            "clipping": 1, "fullbacks": 1, "grounds": 1, "matchmaking": 1, "amps": 1, "facilities": 1,
            "career": 1, "general": 3, "transfers": 5, "management": 1, "tribute": 3, "feedback": 2,
        }
        self.assertEqual([k for k in keys if ".p" in k],
                         [f"{topic}.p{i}" for topic, count in expected_counts.items() for i in range(1, count + 1)])
        self.assertEqual([b.section for b in blocks if b.key.endswith(".figure")],
                         ["dribbling", "near-post", "physicality", "reach"])
        self.assertEqual([b.section for b in blocks if b.key.endswith(".caption")], ["dribbling", "reach"])
        self.assertEqual(keys[-1], "signature")
        self.assertNotIn("13897645", result.stdout)
        for msg_lang, embeds in (("zh", plan["parent"]["embeds"]),
                                 ("en", [e for m in plan["thread"]["messages"] for e in m["embeds"]])):
            for key in ("dribbling", "near-post", "physicality", "reach"):
                group = [b for b in blocks if b.section == key]
                self.assertTrue(any(all(b.render(msg_lang) in e["description"] for b in group) for e in embeds))

    def test_large_table_long_paragraph_overflow_and_media_links(self):
        import json
        from scripts.fc27_layout_fixture import illustrated_table_fixture
        result = self.cli("--case", "illustrated-table", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn("完整", plan["parent"]["content"])
        self.assertTrue(plan["parent"]["text_attachment"]["filename"].endswith(".md"))
        self.assert_full_output(plan, illustrated_table_fixture())
        pages = [m["embeds"][0]["description"] for m in plan["thread"]["messages"]]
        for n in range(1, 151):
            row = f"| Drill {n} | Marker {n} on the left | Marker {n + 1} on the right |"
            self.assertTrue(any(row in page for page in pages))

    def test_missing_translation_structure_or_reference_blocks_publication(self):
        from core.fc27_layout import Block, full_layout
        for en, zh, urls in [("Long paragraph", "", ()), ("one\n\ntwo", "一段", ()),
                             ("[article](https://a.invalid)", "文章", ()),
                             ("|a|b|\n|1|2|", "|甲|乙|\n|一||", ()),
                             ("- outer\n  - inner", "- 外\n- 內", ()),
                             ("a {ref0} b {ref1}", "乙 {ref1} 甲 {ref0}", ("https://a.invalid", "https://b.invalid"))]:
            with self.subTest(en=en), self.assertRaises(ValueError):
                full_layout([Block("case", "section", en, zh, urls)])
        result = self.cli("--source-only", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("全文未備妥", result.stderr)

    def test_link_at_unicode_split_and_unbreakable_link(self):
        from core.fc27_layout import Block, full_layout
        for path_size in (100, 4200):
            url = "https://example.invalid/" + "x" * path_size
            text = "🏟" * 2000 + " [original link]({ref0}) end"
            block = Block("one", "fixture", text, text, (url,))
            plan = full_layout([block])
            self.assert_full_output(plan, [block])
            if path_size == 100:
                self.assertTrue(any(f"[original link](<{url}>)" in m["embeds"][0]["description"]
                                    for m in plan["thread"]["messages"]))
            else:
                self.assertIn("text_attachment", plan["parent"])
