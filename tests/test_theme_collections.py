from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import discord
from quick_bar_fakes import interaction, member

from data.drink_data import ALL_DRINKS, IBA, RARITY_STYLE, SEASONAL_DRINKS
from features import drink_storage as storage
from features import theme_collections as tc
from features.collection_milestones import collection_snapshot, select_title
from features.drink_catalog import (
    build_pool_for_rarity,
    pick_rarity,
    pick_weighted_drink,
)
from features.theme_views import ThemeCollectionView, build_theme_embed

CATALOG = {d.eng: d for d in ALL_DRINKS}


class ThemeStorageFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(storage, "DATA_DIR", Path(self.temp.name)),
            patch.object(storage, "STATS_DB", Path(self.temp.name) / "stats.db"),
        ]
        for p in self.patches:
            p.start()
        storage.init_drink_events_db()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def record(self, name, *, actor=1, target=1, guild=10):
        progress = {}
        self.assertTrue(
            storage.record_drink_event(
                guild_id=guild,
                actor_id=actor,
                target_id=target,
                event_type="self_drink" if actor == target else "gift_drink",
                drink=CATALOG[name],
                progress=progress,
            )
        )
        return progress

    def seed_owned(self, names, *, guild="10", user=1):
        # Actual pre-feature ownership, including grandfathered outgoing gifts.
        with storage.connect_sqlite(storage.STATS_DB) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO drink_collection VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        guild,
                        user,
                        n,
                        CATALOG[n].zh,
                        CATALOG[n].rarity,
                        "2025-01-01T00:00:00+00:00",
                    )
                    for n in names
                ],
            )


class ThemeStorageTests(ThemeStorageFixture, unittest.TestCase):
    def test_pre_milestone_legacy_gift_counts_for_both_original_owners(self):
        path = Path(self.temp.name) / "legacy.db"
        with patch.object(storage, "STATS_DB", path):
            with storage.connect_sqlite(path) as conn:
                conn.execute(
                    "CREATE TABLE drink_events(id INTEGER PRIMARY KEY, guild_id INTEGER,event_type TEXT,actor_id INTEGER,target_id INTEGER,drink_eng TEXT,drink_zh TEXT,rarity TEXT,created_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO drink_events VALUES (1,10,'gift_drink',1,2,'Mojito','莫吉托','Common','2025-01-01T00:00:00+00:00')"
                )
            for owner in (1, 2):
                state = tc.snapshot(10, owner)
                self.assertEqual(state["names"], {"Mojito"})
                self.assertEqual(len(state["awards"]), 1)
                self.assertTrue(state["awards"][0]["backfilled"])
            self.record("Daiquiri", actor=1, target=2)
            self.assertEqual(tc.snapshot(10, 1)["names"], {"Mojito"})
            self.assertEqual(tc.snapshot(10, 2)["names"], {"Mojito", "Daiquiri"})

    def test_frozen_lists_match_reviewed_catalog(self):
        starter, tropical, classics = tc.themes()
        self.assertEqual([len(t.drinks) for t in tc.themes()], [2092, 334, 78])
        self.assertEqual(
            {d.eng for d in tropical.drinks},
            {d.eng for d in ALL_DRINKS if d.typ == "tropical"},
        )
        self.assertEqual({d.eng for d in classics.drinks}, {d[0] for d in IBA})
        seasonal = {d.eng for p in SEASONAL_DRINKS.values() for d in p}
        for theme in tc.themes():
            self.assertFalse(seasonal & {d.eng for d in theme.drinks})
            self.assertEqual(len(theme.drinks), len({d.eng for d in theme.drinks}))
            for d in theme.drinks:
                self.assertEqual(
                    (d.zh, d.typ, d.rarity),
                    (CATALOG[d.eng].zh, CATALOG[d.eng].typ, CATALOG[d.eng].rarity),
                )
        self.assertEqual(starter.targets, (3, 5))

    def test_old_ownership_backfills_all_stages_without_changing_existing_title(self):
        self.seed_owned(CATALOG)
        before = collection_snapshot(10, 1)
        self.assertTrue(select_title(10, 1, "count:50"))
        state = tc.snapshot(10, 1)
        self.assertEqual(len(state["awards"]), 8)
        self.assertTrue(all(a["backfilled"] for a in state["awards"]))
        self.assertEqual(len(state["names"]), 2094)
        self.assertEqual(len(before["names"]), len(state["names"]))
        with storage.connect_sqlite(storage.STATS_DB) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM drink_milestones WHERE milestone_id LIKE 'theme:%'"
                ).fetchone()[0],
                0,
            )
        self.assertEqual(collection_snapshot(10, 1)["selected"], "count:50")
        ids = [a["award_id"] for a in state["pending"]]
        tc.acknowledge(10, 1, ids)
        self.assertFalse(tc.snapshot(10, 1)["pending"])
        self.assertNotIn("theme_awards", self.record("Mojito"))

    def test_first_classic_counts_for_multiple_themes_and_duplicate_does_not_unlock(
        self,
    ):
        progress = self.record("Mojito")
        self.assertEqual(
            [a["award_id"] for a in progress["theme_awards"]], ["theme:v1:classics:1"]
        )
        state = tc.snapshot(10, 1)
        self.assertEqual([t.count(state["names"]) for t in tc.themes()], [1, 1, 1])
        self.assertFalse(state["awards"][0]["backfilled"])
        self.assertNotIn("theme_awards", self.record("Mojito"))

    def test_beginner_counts_types_not_distinct_names(self):
        for name in ("Mojito", "Daiquiri", "Paloma"):
            self.record(name)
        state = tc.snapshot(10, 1)
        self.assertEqual(tc.themes()[0].count(state["names"]), 1)
        self.assertNotIn("theme:v1:starter:3", {a["award_id"] for a in state["awards"]})
        self.record("Alexander")
        progress = self.record("Moscow Mule")
        self.assertIn(
            "theme:v1:starter:3", {a["award_id"] for a in progress["theme_awards"]}
        )

    def test_gift_and_guild_ownership_and_old_awards_not_announced_as_new(self):
        self.seed_owned(["Mojito", "Daiquiri", "Paloma"], user=2)
        progress = self.record("Alexander", actor=1, target=2)
        self.assertNotIn("theme_awards", progress)
        self.assertEqual(tc.snapshot(10, 1)["names"], set())
        state = tc.snapshot(10, 2)
        self.assertEqual(len(state["names"]), 4)
        self.assertTrue(all(a["backfilled"] for a in state["awards"]))
        self.assertEqual(tc.snapshot(99, 2)["awards"], [])
        self.assertEqual(tc.snapshot(None, 2)["awards"], [])

    def test_pending_ack_does_not_clear_concurrent_new_awards(self):
        self.record("Mojito")
        old_ids = [a["award_id"] for a in tc.snapshot(10, 1)["pending"]]
        self.record("Daiquiri")
        self.record("Paloma")
        tc.acknowledge(10, 1, old_ids)
        pending = tc.snapshot(10, 1)["pending"]
        self.assertEqual(
            {a["award_id"] for a in pending},
            {"theme:v1:tropical:3", "theme:v1:classics:3"},
        )

    def test_simultaneous_gifts_award_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(
                pool.map(
                    lambda actor: self.record("Mojito", actor=actor, target=9), (1, 2)
                )
            )
        self.assertEqual(sum(len(r.get("theme_awards", [])) for r in result), 1)
        self.assertEqual(len(tc.snapshot(10, 9)["awards"]), 1)

    def test_theme_failure_rolls_back_event_ownership_and_milestone(self):
        with (
            patch.object(
                tc,
                "reconcile",
                side_effect=[[], RuntimeError("injected write failure")],
            ),
            self.assertLogs("con9sole-bartender.drink.storage", level="ERROR"),
        ):
            self.assertFalse(
                storage.record_drink_event(
                    guild_id=10,
                    event_type="self_drink",
                    actor_id=1,
                    target_id=1,
                    drink=CATALOG["Mojito"],
                )
            )
        self.assertEqual(tc.snapshot(10, 1)["names"], set())
        self.assertEqual(collection_snapshot(10, 1)["awards"], [])
        self.assertEqual(storage.count_self_drinks(10, 1), 0)

    def test_theme_titles_tracking_and_awards_survive_new_process(self):
        self.seed_owned([d.eng for d in tc.themes()[1].drinks[:25]])
        first = tc.snapshot(10, 1)
        title = "theme:v1:tropical:25"
        self.assertTrue(select_title(10, 1, title))
        self.assertFalse(select_title(10, 2, title))
        self.assertFalse(tc.track(10, 1, "invented"))
        self.assertTrue(tc.track(10, 1, "classics"))
        script = """
import json
from features.theme_collections import snapshot
from features.collection_milestones import collection_snapshot
s = snapshot(10, 1)
print(json.dumps(dict(names=sorted(s['names']), awards=s['awards'], tracked=s['tracked'], selected=collection_snapshot(10,1)['selected'])))
"""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "TWITCH_BOT_OAUTH"}
        }
        env.update(DRINK_DATA_DIR=self.temp.name, STATS_DB_PATH=str(storage.STATS_DB))
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads(result.stdout)
        self.assertEqual(after["names"], sorted(first["names"]))
        self.assertEqual(after["awards"], first["awards"])
        self.assertEqual((after["tracked"], after["selected"]), ("classics", title))
        tc.track(10, 1, None)
        self.assertIsNone(tc.snapshot(10, 1)["tracked"])
        select_title(10, 1, "none")
        self.assertIsNone(collection_snapshot(10, 1)["selected"])

    def test_awards_never_revoked_when_catalog_changes(self):
        self.seed_owned(CATALOG)
        before = tc.snapshot(10, 1)["awards"]
        with patch("features.drink_catalog.drink_catalog", return_value={}):
            self.assertEqual(tc.snapshot(10, 1)["awards"], before)

    def test_probability_contract_and_recent_duplicates_remain_possible(self):
        self.assertEqual([v["weight"] for v in RARITY_STYLE.values()], [85, 12, 3])
        with patch(
            "features.drink_catalog.random.choices", return_value=["Common"]
        ) as choice:
            self.assertEqual(pick_rarity(), "Common")
            self.assertEqual(choice.call_args.kwargs["weights"], [85, 12, 3])
        for r, n in (("Common", 1517), ("Rare", 524), ("SSR", 55)):
            self.assertEqual(len(build_pool_for_rarity(r)), n)
        pool = [CATALOG["Mojito"], CATALOG["Daiquiri"]]
        with (
            patch("features.drink_catalog.build_pool_for_rarity", return_value=pool),
            patch(
                "features.drink_catalog.random.choices", return_value=[pool[0]]
            ) as choice,
        ):
            tc.track(10, 1, "classics")
            self.assertEqual(
                pick_weighted_drink(rarity="Common", recent_drink_names={"Mojito"}),
                pool[0],
            )
            self.assertEqual(choice.call_args.kwargs["weights"], [1, 4])


class ThemeViewTests(ThemeStorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_summary_acknowledges_interaction_before_database_read(self):
        from features.drink_views import (
            DrinkCollectionSummaryButton,
            DrinkCollectionView,
        )

        user = member(1)
        view = DrinkCollectionView(owner_id=1, guild=MagicMock(id=10), target_user=user)
        button = next(
            c for c in view.children if isinstance(c, DrinkCollectionSummaryButton)
        )
        i = interaction(user)

        def build(*args):
            self.assertTrue(i.response.is_done())
            return discord.Embed(title="收藏")

        with patch(
            "features.drink_views.build_drink_collection_embed", side_effect=build
        ):
            await button.callback(i)
        i.response.defer.assert_awaited_once()
        i.edit_original_response.assert_awaited_once()

    async def test_collection_entry_theme_selection_and_return(self):
        from features.drink_views import DrinkCollectionView, DrinkThemesButton
        from features.theme_views import ThemeSelect

        user = member(1)
        view = DrinkCollectionView(owner_id=1, guild=MagicMock(id=10), target_user=user)
        entry = next(c for c in view.children if isinstance(c, DrinkThemesButton))
        i = interaction(user)
        await entry.callback(i)
        theme_view = i.edit_original_response.await_args.kwargs["view"]
        self.assertIsInstance(theme_view, ThemeCollectionView)
        selector = next(c for c in theme_view.children if isinstance(c, ThemeSelect))
        selector._values = ["tropical"]
        await selector.callback(interaction(user))
        self.assertEqual(theme_view.theme.key, "tropical")
        back = next(
            c for c in theme_view.children if getattr(c, "action", "") == "collection"
        )
        j = interaction(user)
        await back.callback(j)
        self.assertIsInstance(
            j.edit_original_response.await_args.kwargs["view"], DrinkCollectionView
        )

    async def test_collection_open_delivers_pending_privately_only_after_success(self):
        from features.theme_views import deliver_pending_notice

        self.record("Mojito")
        i = interaction(member(1))
        i.guild_id = 10
        i.followup.send.side_effect = discord.HTTPException(
            MagicMock(status=503, reason="Unavailable"), "fail"
        )
        with self.assertLogs("con9sole-bartender.drink.themes", level="ERROR"):
            await deliver_pending_notice(i)
        self.assertTrue(tc.snapshot(10, 1)["pending"])
        i.followup.send.side_effect = None
        await deliver_pending_notice(i)
        self.assertTrue(i.followup.send.await_args.kwargs["ephemeral"])
        self.assertFalse(tc.snapshot(10, 1)["pending"])

    async def test_layout_pagination_and_names_visible(self):
        state = tc.snapshot(10, 1)
        user = member(1)
        guild = MagicMock(id=10)
        view = ThemeCollectionView(owner_id=1, guild=guild, target_user=user)
        i = interaction(user)
        for theme in tc.themes():
            for mode in ("detail", "missing", "all", "stages"):
                view.theme, view.mode, view.page = theme, mode, 9999
                await view.render(i)
                embed = i.edit_original_response.await_args.kwargs["embed"]
                self.assertLess(len(embed), 6000)
                self.assertLessEqual(len(embed.description), 4096)
                for row in range(5):
                    self.assertLessEqual(
                        sum(c.width for c in view.children if c.row == row), 5
                    )
                _, page, pages = build_theme_embed(state, theme, mode=mode, page=9999)
                if mode in {"missing", "all"}:
                    self.assertEqual(page, pages - 1)
                    next_button = next(
                        c for c in view.children if getattr(c, "action", "") == "next"
                    )
                    self.assertTrue(next_button.disabled)
        embed, _, _ = build_theme_embed(state, tc.themes()[2], mode="all")
        self.assertIn("Alexander", embed.description)
        self.assertNotIn("???", embed.description)

    async def test_notice_failure_stays_pending_and_other_user_cannot_ack(self):
        self.record("Mojito")
        user = member(1)
        view = ThemeCollectionView(owner_id=1, guild=MagicMock(id=10), target_user=user)
        i = interaction(user)
        i.edit_original_response.side_effect = discord.HTTPException(
            MagicMock(status=503, reason="Unavailable"), "fail"
        )
        with self.assertRaises(discord.HTTPException):
            await view.render(i)
        self.assertTrue(tc.snapshot(10, 1)["pending"])
        other = ThemeCollectionView(
            owner_id=2, guild=MagicMock(id=10), target_user=user
        )
        foreign = interaction(member(2))
        await other.render(foreign)
        self.assertNotIn(
            "收藏新進展",
            [
                f.name
                for f in foreign.edit_original_response.await_args.kwargs[
                    "embed"
                ].fields
            ],
        )
        self.assertTrue(tc.snapshot(10, 1)["pending"])
        i.edit_original_response.side_effect = None
        await view.render(i)
        self.assertFalse(tc.snapshot(10, 1)["pending"])

    async def test_owner_check_tracking_and_title_navigation(self):
        user = member(1)
        view = ThemeCollectionView(owner_id=1, guild=MagicMock(id=10), target_user=user)
        view.theme = tc.themes()[1]
        i = interaction(user)
        await view.render(i)
        self.assertFalse(await view.interaction_check(interaction(member(2))))
        button = next(c for c in view.children if getattr(c, "action", "") == "track")
        await button.callback(interaction(member(2)))
        self.assertIsNone(tc.snapshot(10, 1)["tracked"])
        await button.callback(i)
        self.assertEqual(tc.snapshot(10, 1)["tracked"], "tropical")
        self.seed_owned([d.eng for d in tc.themes()[1].drinks[:25]])
        titles = next(c for c in view.children if getattr(c, "action", "") == "titles")
        await titles.callback(i)
        from features.drink_views import CollectionTitleSelect

        collection_view = i.edit_original_response.await_args.kwargs["view"]
        selector = next(
            c for c in collection_view.children if isinstance(c, CollectionTitleSelect)
        )
        self.assertIn("theme:v1:tropical:25", {o.value for o in selector.options})
        self.assertLess(len(i.edit_original_response.await_args.kwargs["embed"]), 6000)
