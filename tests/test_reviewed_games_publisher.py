"""Run each new manual release path against local SQLite and Discord/translator fakes."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import discord

from cogs.gta_translation import GTATranslation
from cogs.update_publisher import PublisherStartView
from core.fc27_publication import Receipts, Release, ReviewError
from core.gta_translation import OFFICIAL_UPDATE_CHANNELS, TranslationQueue
from core.reviewed_games import NBA_PAGE, ROUTES
from core.sqlite_storage import connect_sqlite
from features.fc27_publisher import publish, translated_draft
from test_fc27_publisher import Surface


WEEKLY = "https://www.rockstargames.com/newswire/article/4k17a844oakk5o/take-down-the-kortz-center-and-more-high-value-targets-in-this-week-s"
CASES = {
    "bf6": ("2.1.2.5", "BATTLEFIELD 6 GAME UPDATE 2.1.2.5",
            "https://www.ea.com/games/battlefield/battlefield-6/news/battlefield-6-game-update-2-1-2-5"),
    "hd2": ("7.2.0 / 原文範圍", "Devoid of Liberty: 7.2.0",
            "https://arrowhead.zendesk.com/hc/en-us/articles/31176395885596-Devoid-of-Liberty-7-2-0"),
    "gtao": ("1.73", "GTAV Title Update 1.73 Notes",
             "https://support.rockstargames.com/articles/4vRqEDvjUs9h7nqRUgc8YO/gtav-title-update-1-73-notes-ps5-ps4-xbox-series-x-or-s-xbox-one-pc-enhanced-legacy"),
    "gtaweek": ("2026-11-05 / 4k17a844oakk5o", "Take Down the Kortz Center and More High-Value Targets in This Week’s Heist Event", WEEKLY),
    "delta": ("2026-11-10 / 跨平台", "Major Update: Season Aurora Is Coming!",
              "https://www.playdeltaforce.com/en/detail/news-major-update-season-aurora-is-coming.html"),
    "wilds": ("1.042.00.03 / Steam", "Update Summary (Ver.1.042.00.03)",
              "https://store.steampowered.com/news/app/2246340/view/668380665149915562?l=english"),
    "wwmhmt": ("2026-11-26", "「飲馬渡秋水」11月26日2.4版本内容一覽",
               "https://www.wherewindsmeetgame.com/hmt/news/official/1126update.html"),
    "nba27": ("3.0", "NBA 2K27 v3.0", NBA_PAGE),
}
ENGLISH = "The example affects the listed platforms."
QUOTE = "A sample passage."
NATIVE = "這是人工撰寫的港澳台更新摘要。"


def draft(game):
    version, headline, url = CASES[game]
    source, quote = (NATIVE, "版本內容一覽") if game == "wwmhmt" else (ENGLISH, QUOTE)
    return Release.from_input(version, url, source, quote, game=game, headline=headline)


class ReviewedGamesTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.store = Receipts(self.directory / "gta_translation.sqlite3")

    async def test_menu_preview_confirm_resume_each_route(self):
        self.assertEqual(ROUTES.keys(), CASES.keys())
        for game in CASES:
            with self.subTest(game=game):
                sample = draft(game)
                self.assertEqual(OFFICIAL_UPDATE_CHANNELS[sample.channel_id], ROUTES[game].channel)
                ui = Surface(self.store, sample.channel_id)
                provider = AsyncMock(return_value="這是測試摘要。")
                ui.bot.get_cog.return_value = SimpleNamespace(translate_reviewed=provider)
                i = ui.interaction()
                panel = PublisherStartView(owner_id=i.user.id, guild_id=i.guild.id)
                selector = panel.reviewed_games
                self.assertIn(game, [o.value for o in selector.options])
                selector._values = [game]
                await selector.callback(i)
                modal = i.response.send_modal.await_args.args[0]
                for field, value in ((modal.version, sample.version), (modal.links, sample.urls[0]),
                                     (modal.notes, sample.english), (modal.quote, sample.quote), (modal.headline, sample.headline)):
                    field._refresh_state(i, {"value": value})
                with patch("features.fc27_review_ui.DATA_DIR", self.directory):
                    await modal.on_submit(i)
                payload = i.followup.send.await_args.kwargs
                self.assertTrue(payload["ephemeral"])
                self.assertFalse(ui.sends)
                if game == "wwmhmt":
                    self.assertEqual(payload["embeds"][0].description, NATIVE)
                    self.assertIn("官方繁中來源", payload["embeds"][1].title)
                    self.assertNotIn("英文", payload["embeds"][1].description)
                    self.assertEqual(len(payload["embeds"]), 2)
                    provider.assert_not_awaited()
                else:
                    self.assertEqual(provider.await_count, 2)
                    self.assertIn(sample.quote, payload["embeds"][1].description)
                await payload["view"].confirm.callback(i)
                self.assertEqual(len(ui.sends), 2)
                self.assertTrue(all(row["silent"] and row["allowed_mentions"].to_dict() == {"parse": []}
                                    and len(row["nonce"]) <= 25 for row in ui.sends))
                self.assertIn(sample.urls[0], ui.sends[1]["embed"].description)
                stored = Release.unpack(self.store.receipt(sample.key)[0])
                await publish(ui.bot, ui.guild, Receipts(self.store.path), stored)
                self.assertEqual(len(ui.sends), 2)

    def test_cross_game_unverified_sources_and_wrong_versions(self):
        for game, url in (("wilds", "https://steamcommunity.com/app/2246340/discussions/0/12"),
                          ("wilds", CASES["wilds"][2].replace("2246340", "582010")),
                          ("wwmhmt", CASES["wwmhmt"][2].replace("hmt", "global")),
                          ("wwmhmt", CASES["wwmhmt"][2].replace("1126", "1125")),
                          ("gtaweek", WEEKLY.replace("take-down-the-kortz-center-and-more-high-value-targets-in-this-week-s",
                                                     "grand-theft-auto-vi-trailer")),
                          ("delta", "https://www.playdeltaforce.com/en/detail/news-skin-preview.html"),
                          ("bf6", CASES["bf6"][2].replace("2-1-2-5", "2-1-2-6")),
                          ("nba27", "https://nba.2k.com/2k26/patch-updates/")):
            with self.subTest(game=game), self.assertRaises(ReviewError):
                s = draft(game)
                Release.from_input(s.version, url, s.english, s.quote, game=game, headline=s.headline)
        for game in ("nba27", "wilds"):
            s = draft(game)
            with self.assertRaises(ReviewError):
                Release.from_input(s.version, s.urls[0], ENGLISH, QUOTE, game=game, headline="Unrelated trailer")
        with self.assertRaises(ReviewError):
            replace(draft("wwmhmt"), gloss="另一句引文").check_translation()

    async def relay(self, ui, text):
        series = GTATranslation(ui.bot, TranslationQueue(self.store.path), None, "", "")
        await series.on_message(SimpleNamespace(id=501, guild=ui.guild, channel=ui.room,
                                webhook_id=1, flags=discord.MessageFlags(is_crossposted=True),
                                type=discord.MessageType.default, reference=None, embeds=[], content=text))

    async def test_existing_native_before_or_after_review_and_pure_link(self):
        weekly = draft("gtaweek")
        ui = Surface(self.store, weekly.channel_id)
        await self.relay(ui, WEEKLY)
        provider = AsyncMock(return_value="樣本摘要")
        with self.assertRaisesRegex(ReviewError, "轉發"):
            await translated_draft(self.store, weekly, provider)
        provider.assert_not_awaited()
        self.assertIsNone(TranslationQueue(self.store.path).claim(1))
        patch = draft("gtao")
        ready = await translated_draft(self.store, patch, provider)
        await publish(ui.bot, ui.guild, self.store, ready)
        await self.relay(ui, "GTAV Title Update 1.73.")
        self.assertIsNone(TranslationQueue(self.store.path).claim(1))

    async def test_native_and_english_share_receipts_but_only_english_spends(self):
        s = draft("wwmhmt")
        ui = Surface(self.store, s.channel_id)
        self.assertEqual(await translated_draft(self.store, s, None), s)
        ui.lose_reply = s.channel_id
        with self.assertRaises(TimeoutError):
            await publish(ui.bot, ui.guild, self.store, s)
        await publish(ui.bot, ui.guild, Receipts(self.store.path), s)
        self.assertEqual(len(ui.sends), 2)
        with connect_sqlite(self.store.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM usage").fetchone()[0], 0)
        nba = draft("nba27")
        current = replace(nba, recap="摘要", gloss="對照")
        self.store.begin(current)
        later = replace(current, version="3.1", headline="NBA 2K27 v3.1")
        self.store.begin(later)
        self.assertIsNotNone(self.store.receipt(later.key))

    async def test_select_denies_nonowner_and_revoked_manager(self):
        s = draft("delta")
        ui = Surface(self.store, s.channel_id)
        i = ui.interaction()
        for owner, perms in ((i.user.id + 1, discord.Permissions.all()), (i.user.id, discord.Permissions.none())):
            i.user.guild_permissions = perms
            select = PublisherStartView(owner_id=owner, guild_id=i.guild.id).reviewed_games
            select._values = ["delta"]
            await select.callback(i)
            i.response.send_modal.assert_not_awaited()
        self.assertFalse(ui.sends)

    def test_platform_and_mirror_receipts(self):
        delta = draft("delta")
        ready = replace(delta, recap="摘要", gloss="對照")
        self.store.begin(ready)
        article_id = "de0db9f6a0ac1a4621a864eaa9442413c49d"
        alias = "https://www.playdeltaforce.com/en/detail.html?content_id=" + article_id
        self.assertEqual(self.store.article(alias), self.store.article(delta.urls[0]))
        with self.assertRaises(ReviewError):
            self.store.check_sources(replace(ready, version="2026-11-10 / PC", urls=(alias,)))
