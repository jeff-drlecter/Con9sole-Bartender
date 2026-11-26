from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import config
from cogs import gta_translation as pilot
from core.automatic_receipts import AutomaticReceipts
from core.automatic_updates import APPS, DESTINATIONS, HMT, excerpt, hmt_notices, steam_notices
from core.fc27_publication import BOT_ID
from core.gta_translation import OFFICIAL_UPDATE_CHANNELS, TranslationQueue
from core.sqlite_storage import connect_sqlite
from features.automatic_updates import deliver, fetch

NOW = 1795700000
GAME = "Apex Legends"
CHANNEL = DESTINATIONS[GAME]
TITLE = "Apex Legends: Latest Update 11/25/2026"


def payload(name=GAME, title=TITLE):
    app = APPS[name]
    row = dict(appid=app, feedname="steam_community_announcements", feed_type=1, gid="123456789",
               url="https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/123456789",
               title=title, contents="Map visibility has improved. Damage increased by 2.5 percent.", date=NOW)
    return {"appnews": {"appid": app, "newsitems": [row]}}


def notice():
    return steam_notices(GAME, json.dumps(payload()))[0]


class FeedTests(unittest.TestCase):
    def test_nine_destinations_and_game_and_publisher_scope(self):
        self.assertEqual(set(APPS) | {HMT}, set(OFFICIAL_UPDATE_CHANNELS.values()))
        for game in APPS:
            data = payload(game, "December Patch Notes")
            with self.subTest(game=game):
                self.assertEqual(steam_notices(game, json.dumps(data))[0].channel, DESTINATIONS[game])
                data["appnews"]["newsitems"][0]["feedname"] = "external_magazine"
                self.assertEqual(steam_notices(game, json.dumps(data)), [])
        self.assertEqual(steam_notices(GAME, json.dumps(payload(title="Official fan art awards"))), [])
        self.assertIn("apex:2026-11-25", notice().keys)
        self.assertIn("2.5 percent.", notice().excerpt)
        self.assertIn("nba27:3.0", steam_notices("NBA 2K", json.dumps(payload("NBA 2K", "NBA 2K27 Patch Notes v3.0")))[0].keys)

    def test_hmt_publication_date_is_distinct_from_maintenance_date(self):
        html = """<ul class="news_list"><a href="https://www.wherewindsmeetgame.com/hmt/news/official/1126update.html"
        title="版本更新"><p class="news_text">本次維護將於2026年11月26日進行，維護期間可登入。</p>
        <p class="date_day">11.25</p><p class="date_year">2026</p></a></ul>"""
        item, = hmt_notices(html.encode())
        self.assertIn("wwmhmt:2026-11-26", item.keys)
        self.assertLess(item.published, NOW)
        with self.assertRaises(ValueError):
            hmt_notices(b"<h1>Maintenance</h1>")


class AutomaticFlow(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "updates.db"
        self.store = AutomaticReceipts(self.path, NOW - 1)
        self.messages = []
        async def history(**kwargs):
            for msg in list(self.messages):
                yield msg
        self.channel = MagicMock(id=CHANNEL)
        self.channel.guild.id = config.GUILD_ID
        self.channel.history = history
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=123))
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.bot.get_channel.return_value = self.channel
        self.cog = pilot.GTATranslation(self.bot, TranslationQueue(self.path), None, "", "")
        self.cog.automatic = self.store
        self.cog.translate_reviewed = AsyncMock(return_value="地圖能見度已改善，傷害增加 2.5%。")

    def original(self, title=TITLE):
        dt = datetime.fromtimestamp(NOW, timezone.utc)
        mid = discord.utils.time_snowflake(dt)
        return SimpleNamespace(guild=self.channel.guild, channel=self.channel, id=mid, webhook_id=12,
                               type=discord.MessageType.default, content=title, embeds=[], reference=None,
                               created_at=dt, jump_url=f"https://discord.com/channels/{config.GUILD_ID}/{CHANNEL}/{mid}",
                               flags=SimpleNamespace(is_crossposted=True, has_thread=False))

    async def poll(self):
        async def fetch(session, name, store):
            return [notice()] if name == GAME else []
        with patch("cogs.gta_translation.automatic_updates.fetch", side_effect=fetch), patch("cogs.gta_translation.time.time", return_value=NOW):
            await self.cog.poll_publishers.coro(self.cog)

    async def send(self):
        with patch("cogs.gta_translation.time.time", return_value=NOW + 610):
            await self.cog.publish_notices.coro(self.cog)

    async def test_previous_version_in_patch_body_does_not_claim_the_new_version(self):
        for history in ("baseline", "sent"):
            with self.subTest(history=history):
                store = AutomaticReceipts(self.path.parent / (history + ".db"), NOW-1)
                old_feed = payload("EA SPORTS FC", "FC 27 v1.3.0 Patch Notes")
                old = steam_notices("EA SPORTS FC", json.dumps(old_feed))[0]
                store.observe(replace(old, published=NOW-2 if history == "baseline" else NOW), now=NOW)
                if history == "sent":
                    old_key = store.next(NOW+900)[0]
                    store.claim_send(old_key, None)
                    store.finish(old_key, "sent", from_stage="posting", message=12)
                new_feed = payload("EA SPORTS FC", "FC 27 v1.4.0 Patch Notes")
                row = new_feed["appnews"]["newsitems"][0]
                row.update(gid="222222222", contents="Fixed an issue introduced in FC 27 v1.3.0.")
                row["url"] = row["url"].replace("123456789", row["gid"])
                new = steam_notices("EA SPORTS FC", json.dumps(new_feed))[0]
                self.assertNotIn("1.3.0", new.keys)
                store.observe(new, now=NOW+1)
                self.assertIn("1.4.0", store.next(NOW+901)[3])

    async def test_platform_specific_follow_releases_stay_separate(self):
        from features.automatic_updates import from_follow
        channel = SimpleNamespace(id=DESTINATIONS["Helldivers 2"])
        for platform in ("PC", "PS5"):
            msg = self.original("Helldivers 2 Patch 7.2.0 for " + platform)
            msg.channel = channel
            item = from_follow(msg, NOW)
            self.assertIn("hd2:platform:7.2.0:" + platform, item.keys)
            self.store.observe(item, now=NOW)
        first = self.store.next(NOW+900)
        second = self.store.next(NOW+900)
        self.assertNotEqual(first[0], second[0])
        self.assertFalse(first[3] & second[3])

    def test_selecting_an_excerpt_keeps_platform_and_condition_headings(self):
        part = excerpt("[h2]PC only[/h2]\n[b]While aiming[/b]\nDamage increased by 2.5 percent. Reload speed improved.")
        self.assertIn("PC only\nWhile aiming\nDamage increased by 2.5 percent.", part)
        self.assertEqual(excerpt("Only when " + "x" * 480 + ":\nDamage increased by 2.5 percent."), "")

    async def test_steam_gid_resolves_to_official_article_only_for_new_items(self):
        http = MagicMock()
        response = http.get.return_value.__aenter__.return_value
        response.status = 200
        async def stream():
            yield json.dumps(payload()).encode()
        response.content = SimpleNamespace(iter_chunked=lambda size: stream())
        redirect = http.head.return_value.__aenter__.return_value
        redirect.status = 302
        redirect.headers = {"Location": "https://steamcommunity.com/ogg/1172470/announcements/detail/987654321"}
        item, = await fetch(http, GAME, self.store)
        self.assertTrue(item.url.endswith("/1172470/view/987654321"))
        self.assertIn("steam:1172470:987654321", item.keys)
        self.store.observe(item, now=NOW)
        self.assertEqual(await fetch(http, GAME, self.store), [])
        http.head.assert_called_once()
        separate = AutomaticReceipts(self.path.parent / "later.db", NOW + 1)
        old, = await fetch(http, GAME, separate)
        separate.observe(old, now=NOW + 1)
        self.assertIsNone(separate.next(NOW + 9000))
        http.head.assert_called_once()

    async def test_rechecks_parent_when_translation_is_in_flight(self):
        await self.poll()
        msg = self.original()
        async def translate(*args, **kwargs):
            self.messages.append(msg)
            await self.cog.on_message(msg)
            return "地圖已更新。"
        self.cog.translate_reviewed.side_effect = translate
        await self.send()
        self.channel.send.assert_not_awaited()
        later = self.store.next(NOW + 5000)
        await deliver(self.cog, later)
        self.assertEqual(self.channel.send.await_args.kwargs["reference"].message_id, msg.id)
        self.cog.translate_reviewed.assert_awaited_once()

    async def test_no_parent_posts_one_silent_message_then_late_follow_and_restart_skip(self):
        await self.poll()
        await self.send()
        self.assertIsNone(self.channel.send.await_args.kwargs["reference"])
        self.assertTrue(self.channel.send.await_args.kwargs["silent"])
        self.assertEqual(self.channel.send.await_args.kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.assertIn(notice().url, self.channel.send.await_args.args[0])
        self.cog.automatic = AutomaticReceipts(self.path, NOW + 5000)
        await self.cog.on_message(self.original())
        await self.poll()
        await self.send()
        self.channel.send.assert_awaited_once()
        self.cog.translate_reviewed.assert_awaited_once()

    async def test_feed_then_gateway_replies_directly(self):
        await self.poll()
        msg = self.original()
        self.messages.append(msg)
        await self.cog.on_message(msg)
        await self.send()
        self.assertEqual(self.channel.send.await_args.kwargs["reference"].message_id, msg.id)

    async def test_gateway_then_feed_combines_and_reuses_source(self):
        msg = self.original()
        self.messages.append(msg)
        with patch("cogs.gta_translation.time.time", return_value=NOW):
            await self.cog.on_message(msg)
        await self.poll()
        await self.send()
        self.channel.send.assert_awaited_once()
        self.assertIn(notice().url, self.channel.send.await_args.args[0])
        self.assertEqual(self.channel.send.await_args.kwargs["reference"].message_id, msg.id)

    async def test_no_backfill_even_if_old_item_arrives_late(self):
        self.store.observe(replace(notice(), published=NOW - 9000), now=NOW)
        await self.poll()
        await self.send()
        self.channel.send.assert_not_awaited()
        self.cog.translate_reviewed.assert_not_awaited()

    async def test_ambiguous_timeout_and_parallel_claim_cannot_post_twice(self):
        await self.poll()
        job = self.store.next(NOW + 610)
        self.channel.send.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await deliver(self.cog, job)
        self.assertFalse(self.store.claim_send(job[0], None))
        self.assertIsNone(AutomaticReceipts(self.path, NOW + 1).next(NOW + 9000))

    async def test_unidentified_follow_suppresses_standalone(self):
        msg = self.original()
        msg.content = "New official announcement https://example.invalid/short"
        self.messages.append(msg)
        await self.poll()
        await self.send()
        self.channel.send.assert_not_awaited()

    async def test_existing_chinese_reply_skips_translation(self):
        msg = self.original()
        reply = self.original("已經有繁中整理")
        reply.id += 1
        reply.webhook_id = None
        reply.type = discord.MessageType.reply
        reply.reference = SimpleNamespace(message_id=msg.id)
        self.messages.extend((msg, reply))
        await self.poll()
        await self.send()
        self.channel.send.assert_not_awaited()
        self.cog.translate_reviewed.assert_not_awaited()

    async def test_reviewed_receipt_and_shared_budget_block_delivery(self):
        with connect_sqlite(self.path) as db:
            db.execute("INSERT INTO fc27_delivery_owner VALUES ('apex:2026-11-25','reviewed')")
        await self.poll()
        self.assertIsNone(self.store.next(NOW + 610))
        self.store.observe(replace(notice(), keys=("apex:2026-12-01",)), now=NOW)
        with connect_sqlite(self.path) as db:
            db.execute("INSERT INTO usage VALUES ('2026-11',450000)")
        await self.send()
        self.cog.translate_reviewed.assert_not_awaited()
        self.channel.send.assert_not_awaited()
