from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from data.drink_data import DrinkEntry
from features import drink_storage as storage
from features.collection_milestones import collection_snapshot, milestones, select_title
from features.drink_catalog import drink_catalog


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(storage, "DATA_DIR", Path(self.temp.name)),
            patch.object(storage, "STATS_DB", Path(self.temp.name) / "stats.db"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def record(self, name="A", actor=1, target=1, guild=10):
        progress = {}
        result = storage.record_drink_event(
            guild_id=guild,
            actor_id=actor,
            target_id=target,
            event_type=storage.EVENT_SELF_DRINK
            if actor == target
            else storage.EVENT_GIFT_DRINK,
            drink=DrinkEntry(name, name, "test", "short", "Common"),
            progress=progress,
        )
        self.assertTrue(result)
        return progress

    def seed_legacy(self):
        # An actual old schema, with no collection tables or migration marker.
        with storage.connect_sqlite(storage.STATS_DB) as conn:
            conn.execute(
                "CREATE TABLE drink_events(id INTEGER PRIMARY KEY, guild_id INTEGER,event_type TEXT,actor_id INTEGER,target_id INTEGER,drink_eng TEXT,drink_zh TEXT,rarity TEXT,created_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO drink_events VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (
                        i + 1,
                        10,
                        "gift_drink",
                        1,
                        2,
                        chr(65 + i),
                        chr(65 + i),
                        "Common",
                        f"2025-01-0{i + 1}T00:00:00+00:00",
                    )
                    for i in range(5)
                ],
            )

    def test_real_catalog_and_thresholds(self):
        self.assertEqual(len(drink_catalog()), 2102)
        goals = milestones()
        self.assertEqual([g.target for g in goals[-4:]], [526, 1051, 1577, 2102])

    def test_old_outgoing_and_received_collections_both_preserved(self):
        self.seed_legacy()
        for user in (1, 2):
            snap = collection_snapshot(10, user)
            self.assertEqual(len(snap["names"]), 5)
            self.assertEqual(
                {a["milestone_id"] for a in snap["awards"]}, {"count:1", "count:5"}
            )
            self.assertEqual(
                next(a for a in snap["awards"] if a["milestone_id"] == "count:5")[
                    "unlocked_at"
                ][:10],
                "2025-01-05",
            )
        self.record("F", actor=1, target=2)
        self.assertEqual(len(collection_snapshot(10, 1)["names"]), 5)
        self.assertEqual(len(collection_snapshot(10, 2)["names"]), 6)
        self.assertEqual(len(storage.fetch_collection_rows(10, 1)), 5)
        self.assertEqual(len(storage.fetch_collection_rows(10, 2)), 6)
        with storage.connect_sqlite(storage.STATS_DB) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM drink_events").fetchone()[0], 6
            )

    def test_first_drink_unlocks_once_and_repeat_does_not_count(self):
        first = self.record()
        self.assertEqual(first, dict(is_new=True, unlocked=["初嚐一杯"], total=1))
        self.assertEqual(self.record(), dict(is_new=False, unlocked=[], total=1))
        self.assertEqual(len(collection_snapshot(10, 1)["awards"]), 1)

    def test_new_gift_only_counts_for_recipient_and_is_guild_scoped(self):
        self.record(actor=1, target=2)
        self.assertEqual(collection_snapshot(10, 1)["names"], set())
        self.assertEqual(collection_snapshot(10, 2)["names"], {"A"})
        self.assertEqual(collection_snapshot(99, 2)["names"], set())
        self.assertFalse(storage.has_collected_drink(10, 1, "A"))
        self.assertEqual(storage.fetch_collection_rarity_counts(10, 1), {})

    def test_backfill_does_not_emit_old_awards_again(self):
        self.seed_legacy()
        self.assertEqual(self.record("F", target=2)["unlocked"], [])
        self.assertEqual(self.record("G", target=2)["unlocked"], [])

    def test_titles_authorization_clear_and_persistence(self):
        self.record()
        self.assertFalse(select_title(10, 2, "count:1"))
        self.assertFalse(select_title(99, 1, "count:1"))
        self.assertTrue(select_title(10, 1, "count:1"))
        self.assertEqual(collection_snapshot(10, 1)["selected"], "count:1")
        self.assertTrue(select_title(10, 1, "none"))
        self.assertIsNone(collection_snapshot(10, 1)["selected"])

    def test_old_collection_awards_and_title_survive_fresh_process(self):
        self.seed_legacy()
        old = collection_snapshot(10, 1)
        self.assertTrue(select_title(10, 1, "count:5"))
        script = """
import json
from features.collection_milestones import collection_snapshot
snapshot = collection_snapshot(10, 1)
print(json.dumps({"names": sorted(snapshot["names"]), "awards": snapshot["awards"], "selected": snapshot["selected"]}))
"""
        env = dict(os.environ)
        for key in ("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "TWITCH_BOT_OAUTH"):
            env.pop(key, None)
        env.update(DRINK_DATA_DIR=self.temp.name, STATS_DB_PATH=str(storage.STATS_DB))
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(result.stdout)
            self.assertEqual(snapshot["names"], sorted(old["names"]))
            self.assertEqual(snapshot["awards"], old["awards"])
            self.assertEqual(snapshot["selected"], "count:5")

    def test_simultaneous_duplicate_events_only_one_unlock(self):
        storage.init_drink_events_db()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.record(), range(2)))
        self.assertEqual(sum(r["is_new"] for r in results), 1)
        self.assertEqual(sum(len(r["unlocked"]) for r in results), 1)

    def test_event_and_collection_roll_back_together(self):
        storage.init_drink_events_db()
        with patch(
            "features.drink_storage.reconcile", side_effect=[[], OSError("fail")]
        ):
            with self.assertLogs("con9sole-bartender.drink.storage", level="ERROR"):
                progress = {}
                self.assertFalse(
                    storage.record_drink_event(
                        guild_id=10,
                        event_type="self_drink",
                        actor_id=1,
                        target_id=1,
                        drink=DrinkEntry("A", "A", "test", "short"),
                        progress=progress,
                    )
                )
        self.assertEqual(progress, {})
        self.assertEqual(collection_snapshot(10, 1)["names"], set())
        self.assertEqual(storage.count_self_drinks(10, 1), 0)

    def test_catalog_expansion_keeps_old_awards(self):
        tiny = {str(i): DrinkEntry(str(i), str(i), "test", "short") for i in range(4)}
        with patch("features.collection_milestones.drink_catalog", return_value=tiny):
            for name in tiny:
                self.record(name)
            old = collection_snapshot(10, 1)["awards"]
            self.assertEqual(len([a for a in old if a["label"] == "酒譜 100%"]), 1)
        expanded = dict(tiny, extra=DrinkEntry("extra", "extra", "test", "short"))
        with patch(
            "features.collection_milestones.drink_catalog", return_value=expanded
        ):
            new = collection_snapshot(10, 1)["awards"]
            old_full = next(a for a in old if a["label"] == "酒譜 100%")
            self.assertIn(old_full, new)

    def test_ui_limits_and_title_view(self):
        from unittest.mock import MagicMock

        from quick_bar_fakes import member

        from features.drink_embeds import (
            build_drink_collection_embed,
            build_drink_milestones_embed,
        )
        from features.drink_views import CollectionTitleSelect, DrinkCollectionView

        self.record()
        guild = MagicMock(id=10)
        user = member(1)
        embed = build_drink_collection_embed(guild, user)
        self.assertIn("1 款", embed.description)
        self.assertIn("吧枱熟客", embed.fields[0].name)
        self.assertLess(len(build_drink_milestones_embed(guild, user)), 6000)

        async def check():
            view = DrinkCollectionView(owner_id=1, guild=guild, target_user=user)
            view.add_item(CollectionTitleSelect(collection_snapshot(10, 1)))
            for row in range(5):
                self.assertLessEqual(
                    sum(c.width for c in view.children if c.row == row), 5
                )

        asyncio.run(check())
