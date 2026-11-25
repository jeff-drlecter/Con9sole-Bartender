import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import config
from cogs import gta_translation as pilot
from core.gta_translation import (
    GTA_CHANNEL_ID, HONG_KONG, LEASE_SECONDS, MONTHLY_LIMIT, OFFICIAL_UPDATE_CHANNELS, TranslationQueue,
)
from core.sqlite_storage import connect_sqlite


NOW = datetime(2026, 12, 31, 23, 59, 59, tzinfo=HONG_KONG).timestamp()
TEST_URL = "https://script.google.com/macros/s/test/exec"
TEST_TOKEN = "a" * 64
FC_CHANNEL_ID = 1424226055446593556
NBA_CHANNEL_ID = 1424320426095415397


def post(mid=111, origin=88, **changes):
    fields = dict(id=mid, guild=SimpleNamespace(id=config.GUILD_ID),
                  channel=SimpleNamespace(id=GTA_CHANNEL_ID), webhook_id=7,
                  reference=SimpleNamespace(message_id=origin), flags=discord.MessageFlags(is_crossposted=True),
                  type=discord.MessageType.default, content="New race", embeds=[])
    return SimpleNamespace(**(fields | changes))


class QueueTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "pilot.db"
        self.store = TranslationQueue(self.path)

    def test_atomic_cap_exact_and_rollover_after_restart(self):
        self.store.add(1, 10, "a" * (MONTHLY_LIMIT - 2))
        first = self.store.claim(NOW)
        self.store.advance(first, "deliver", "英文譯文")
        published = self.store.claim(NOW)
        self.store.start_posting(published)
        self.store.sent(1)
        self.store.add(2, 11, "🏁a", channel_id=FC_CHANNEL_ID)
        self.store.add(3, 12, "bc", channel_id=NBA_CHANNEL_ID)
        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: TranslationQueue(self.path).claim(NOW), range(2)))
        self.assertEqual([j.message_id for j in jobs if j], [2])
        self.assertIsNone(self.store.claim(NOW))
        reopened = TranslationQueue(self.path)
        january = reopened.claim(NOW + 1)
        self.assertEqual((january.message_id, january.channel_id), (3, NBA_CHANNEL_ID))
        with connect_sqlite(self.path) as db:
            self.assertEqual(dict(db.execute("SELECT * FROM usage")),
                             {"2026-12": MONTHLY_LIMIT, "2027-01": 2})

    def test_upgrade_keeps_gta_receipts_pending_delivery_and_used_quota(self):
        legacy = self.path.with_name("legacy.db")
        with connect_sqlite(legacy) as db:
            db.executescript("""
                CREATE TABLE posts(message_id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL UNIQUE,
                    stage TEXT NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0,body TEXT NOT NULL);
                CREATE TABLE usage(month TEXT PRIMARY KEY,characters INTEGER NOT NULL);
                INSERT INTO posts VALUES(1,11,'sent',1,0,''),(2,22,'deliver',0,0,'已翻譯'),
                    (3,33,'posting',1,0,'待核對');
                INSERT INTO usage VALUES('2026-12',449999);
            """)
        with ThreadPoolExecutor(2) as pool:
            queue, restarted = list(pool.map(TranslationQueue, (legacy, legacy)))
        queue.add(41, 11, "replay", channel_id=FC_CHANNEL_ID)
        queue.add(42, 44, "ab", channel_id=NBA_CHANNEL_ID)
        delivery = restarted.claim(NOW)
        self.assertEqual((delivery.message_id, delivery.channel_id, delivery.text), (2, GTA_CHANNEL_ID, "已翻譯"))
        self.assertIsNone(queue.claim(NOW))
        with connect_sqlite(legacy) as db:
            self.assertEqual(db.execute("SELECT message_id,stage,channel_id FROM posts ORDER BY message_id").fetchall(),
                             [(1, "sent", GTA_CHANNEL_ID), (2, "deliver", GTA_CHANNEL_ID),
                              (3, "posting", GTA_CHANNEL_ID), (42, "translate", NBA_CHANNEL_ID)])
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone(), (449999,))

    def test_quota_counts_exact_provider_text_for_each_game(self):
        text = "Earn a vehicle and 2 rewards."
        for message_id, channel_id in enumerate((GTA_CHANNEL_ID, FC_CHANNEL_ID), start=1):
            self.store.add(message_id, message_id, text, channel_id=channel_id)
            self.assertEqual(self.store.claim(NOW).channel_id, channel_id)
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone(),
                             (len("Earn GTA0V and 2 rewards.") + len(text),))

    def test_expired_attempt_is_recharged_and_stale_translation_cannot_publish(self):
        self.store.add(1, 9, "test")
        first = self.store.claim(NOW)
        later = self.store.claim(NOW + LEASE_SECONDS)
        self.assertFalse(self.store.advance(first, "deliver", "過期"))
        self.assertTrue(self.store.advance(later, "deliver", "譯文"))
        self.assertEqual(self.store.claim(NOW + LEASE_SECONDS).text, "譯文")
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT SUM(characters) FROM usage").fetchone(), (8,))

    def test_retry_limit_survives_restart(self):
        self.store.add(1, 9, "test")
        for attempt in range(3):
            self.assertEqual(TranslationQueue(self.path).claim(NOW + LEASE_SECONDS * attempt).attempt,
                             attempt + 1)
        self.assertIsNone(self.store.claim(NOW + 3 * LEASE_SECONDS))
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT stage,body FROM posts").fetchone(), ("failed", ""))


class PilotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "pilot.db"
        self.store = TranslationQueue(self.path)
        self.channel = SimpleNamespace(id=GTA_CHANNEL_ID, guild=SimpleNamespace(id=config.GUILD_ID),
                                       send=AsyncMock())
        self.bot = MagicMock()
        self.bot.get_channel.return_value = self.channel
        self.http = MagicMock()
        self.response = self.http.post.return_value.__aenter__.return_value
        self.response.status = 200
        self.response.raise_for_status = MagicMock()
        self.response.json = AsyncMock(return_value={"translation": "新賽道 & 新車"})
        self.cog = pilot.GTATranslation(self.bot, self.store, self.http, TEST_URL, TEST_TOKEN)

    async def test_official_post_gets_one_silent_reply_across_replays(self):
        embed = discord.Embed(title="New race", description="Drive [now](https://example.com/gta)")
        embed.add_field(name="Reward", value="2x XP")
        entry = post(content="New race <@&123>", embeds=[embed])
        await asyncio.gather(self.cog.on_message(entry), self.cog.on_message(post(112)))
        # Both messages reference the same original; ordering is unspecified.
        key = self.store.claim(NOW)
        text = key.text
        linked = "New race\n\nDrive now <https://example.com/gta>\n\nReward\n\n2x XP"
        self.assertIn(text, ("New race", linked))
        self.assertEqual(pilot.source_text(entry), linked)
        outbound, links = pilot.translation_input(text)
        self.response.json.return_value = {"translation": "新賽道 & 新車 " + " ".join(links)}
        await self.cog.process_job(key)
        self.http.post.assert_called_once_with(TEST_URL, json={"text": outbound, "token": TEST_TOKEN},
                                               allow_redirects=False)
        delivery = TranslationQueue(self.path).claim(NOW)
        await self.cog.process_job(delivery)
        await self.cog.on_message(entry)
        self.assertIsNone(self.store.claim(NOW + 2 * LEASE_SECONDS))
        self.channel.send.assert_awaited_once()
        args, kwargs = self.channel.send.await_args
        self.assertIn("新賽道 & 新車", args[0])
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.assertTrue(kwargs["silent"])
        self.assertFalse(kwargs["mention_author"])
        self.assertTrue(kwargs["reference"].fail_if_not_exists)
        self.assertEqual(kwargs["reference"].message_id, key.message_id)
        self.assertEqual(kwargs["reference"].type, discord.MessageReferenceType.reply)
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT stage,body FROM posts").fetchall(), [("sent", "")])

    async def test_scope_and_content_filters(self):
        for msg in (post(guild=None), post(guild=SimpleNamespace(id=1)),
                    post(channel=SimpleNamespace(id=2)), post(webhook_id=None),
                    post(flags=discord.MessageFlags()), post(type=discord.MessageType.reply),
                    post(content="<@&123> https://example.com/post"),
                    post(content="<HTTPS://example.com/post>")):
            await self.cog.on_message(msg)
        self.assertIsNone(self.store.claim(NOW))
        self.assertEqual(pilot.source_text(post(content="[Newswire](hTtPs://example.com/post)")),
                         "Newswire <hTtPs://example.com/post>")
        await self.cog.on_message(post(reference=None))
        await self.cog.on_message(post(reference=None))
        self.assertEqual(self.store.claim(NOW).message_id, 111)
        self.assertIsNone(self.store.claim(NOW))

    async def test_every_configured_channel_delivers_to_its_own_post_once(self):
        for i, (channel_id, game) in enumerate(OFFICIAL_UPDATE_CHANNELS.items(), start=1):
            with self.subTest(game=game):
                mid = 1000 + i
                event = post(mid=mid, origin=i, channel=SimpleNamespace(id=channel_id))
                await self.cog.on_message(event)
                await self.cog.on_message(event)
                await self.cog.process_job(self.store.claim(NOW))
                delivery = TranslationQueue(self.path).claim(NOW)
                self.assertEqual(delivery.channel_id, channel_id)
                self.channel.id = channel_id
                self.channel.send.reset_mock()
                await self.cog.process_job(delivery)
                self.bot.get_channel.assert_called_with(channel_id)
                self.channel.send.assert_awaited_once()
                reply = self.channel.send.await_args.kwargs["reference"]
                self.assertEqual((reply.guild_id, reply.channel_id, reply.message_id),
                                 (config.GUILD_ID, channel_id, mid))
                await self.cog.on_message(event)
                self.assertIsNone(self.store.claim(NOW))

    async def test_non_gta_uses_its_own_vocabulary_and_rejects_a_wrong_channel(self):
        event = post(channel=SimpleNamespace(id=FC_CHANNEL_ID), content="Earn a vehicle and 2 rewards.")
        await self.cog.on_message(event)
        await self.cog.process_job(self.store.claim(NOW))
        self.assertEqual(self.http.post.call_args.kwargs["json"]["text"], event.content)
        # Simulate an incorrect channel lookup; no send may target another game.
        with self.assertRaisesRegex(RuntimeError, "official update channel unavailable"):
            await self.cog.process_job(self.store.claim(NOW))
        self.channel.send.assert_not_awaited()

    async def test_discord_album_link_survives_restart_without_translating_its_url_or_ping(self):
        url = "https://music.example/Deluxe_(Mix)?s=A%2FB&ref=en#Listen"
        entry = post(content="## Album (Deluxe Edition) @Announcements \n23 bonus tracks\n"
                     f"## Listen now: [music.example/Deluxe](<{url}>)")
        await self.cog.on_message(entry)
        job = TranslationQueue(self.path).claim(NOW)
        outbound = "## Album (Deluxe Edition)\n23 bonus tracks\n## GTALINK0Z"
        self.response.json.return_value = {"translation": "豪華版，23 首額外曲目\n## GTALINK0Z"}
        await self.cog.process_job(job)
        self.assertEqual(self.http.post.call_args.kwargs["json"]["text"], outbound)
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone(), (len(outbound),))
        await self.cog.process_job(TranslationQueue(self.path).claim(NOW))
        self.assertIn(f"## [立即收聽](<{url}>)", self.channel.send.await_args.args[0])
        self.assertNotIn("@", self.channel.send.await_args.args[0])

    async def test_link_mapping_handles_multiple_targets_and_marker_collisions(self):
        source = pilot.source_text(post(content="GTALINK0Z @AnnouncementsHQ @公告 <@&123>\n"
            "[Get it](https://a.example/item_(PS5)) and (https://b.example/?q=@Announcements)."))
        outbound, links = pilot.translation_input(source)
        self.assertEqual(outbound, "GTALINK0Z @AnnouncementsHQ\nGet it GTALINKX0Z and (GTALINKX1Z).")
        self.response.json.return_value = {"translation": "GTALINKX1Z 及 GTALINKX0Z"}
        self.assertEqual(await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source),
            "<https://b.example/?q=@Announcements> 及 <https://a.example/item_(PS5)>")
        for invalid in (next(iter(links)), "GTALINKX0Z GTALINKX0Z GTALINKX1Z"):
            self.response.json.return_value = {"translation": invalid}
            with self.assertRaisesRegex(ValueError, "protected translation marker"):
                await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source)
        self.assertEqual(pilot.source_text(post(content="@Announcements [a.example](<https://a.example/>)")), "")

    async def test_long_translation_replies_to_original_with_one_utf8_attachment(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "🏁" * 1200)
        async def inspect_upload(content, *, file, **kwargs):
            self.assertEqual(file.fp.read().decode("utf-8"), "🏁" * 1200)
            self.assertEqual(file.filename, "GTA-繁中翻譯.txt")
            self.assertEqual(kwargs["reference"].message_id, 111)
            self.assertTrue(kwargs["reference"].fail_if_not_exists)
            self.assertFalse(kwargs["mention_author"])
        self.channel.send.side_effect = inspect_upload
        await self.cog.process_job(TranslationQueue(self.path).claim(NOW))
        self.channel.send.assert_awaited_once()
        self.http.post.assert_not_called()

    async def test_ambiguous_send_cannot_be_replayed(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "測試")
        job = self.store.claim(NOW)
        self.channel.send.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await self.cog.process_job(job)
        await self.cog.process_job(job)
        self.assertIsNone(TranslationQueue(self.path).claim(NOW + 3600))
        self.channel.send.assert_awaited_once()

    async def test_deleted_original_never_falls_back_to_an_unreferenced_message(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "譯文")
        self.channel.send.side_effect = discord.NotFound(MagicMock(status=404), "original missing")
        for attempt in range(3):
            with self.assertRaises(discord.NotFound):
                await self.cog.process_job(self.store.claim(NOW + LEASE_SECONDS * attempt))
        self.assertIsNone(self.store.claim(NOW + 3 * LEASE_SECONDS))
        for sent in self.channel.send.await_args_list:
            self.assertEqual(sent.kwargs["reference"].message_id, 111)
            self.assertTrue(sent.kwargs["reference"].fail_if_not_exists)
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT stage FROM posts").fetchone(), ("failed",))

    async def test_definite_send_rejection_reuses_translation_and_reply_target(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "測試")
        self.channel.send.side_effect = [discord.Forbidden(MagicMock(status=403), "permission"), None]
        with self.assertRaises(discord.Forbidden):
            await self.cog.process_job(self.store.claim(NOW))
        await self.cog.process_job(self.store.claim(NOW + LEASE_SECONDS))
        self.assertIsNone(self.store.claim(NOW + 3600))
        self.assertEqual([call.kwargs["reference"].message_id for call in self.channel.send.await_args_list],
                         [111, 111])
        self.http.post.assert_not_called()

    async def test_provider_failure_sends_no_reply_and_budget_is_kept(self):
        self.response.status = 503
        await self.cog.on_message(post())
        await self.cog.process.coro(self.cog)
        self.channel.send.assert_not_awaited()
        with connect_sqlite(self.path) as db:
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone(), (len("New race"),))
        self.assertIsNone(self.store.claim(0))

    async def test_unconfigured_extension_has_no_background_activity(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(pilot.aiohttp, "ClientSession") as session:
            await pilot.setup(self.bot)
        self.bot.add_cog.assert_not_called()
        session.assert_not_called()

    async def test_content_service_redirect_fetches_result_without_credentials(self):
        self.response.status = 302
        target = "https://script.googleusercontent.com/macros/echo?fixture=abc"
        self.response.headers = {"Location": target}
        result = self.http.get.return_value.__aenter__.return_value
        result.status = 200
        result.json = AsyncMock(return_value={"translation": "新賽道"})
        self.assertEqual(await pilot.translate(self.http, TEST_URL, TEST_TOKEN, "race"), "新賽道")
        self.http.get.assert_called_once_with(target, allow_redirects=False)
        self.response.headers["Location"] = "https://example.org/result"
        with self.assertRaises(ValueError):
            await pilot.translate(self.http, TEST_URL, TEST_TOKEN, "race")
        self.assertEqual(self.http.get.call_count, 1)

    async def test_provider_quota_keeps_job_until_reset(self):
        for reason, delay in (("month_full", 1), ("daily_limit", 86400)):
            with self.subTest(reason=reason), patch.object(pilot.time, "time", return_value=NOW):
                self.store.add(delay, delay, "race")
                self.response.json.return_value = {"error": reason}
                await self.cog.process_job(self.store.claim(NOW))
                self.assertIsNone(self.store.claim(NOW + delay - 1))
                resumed = self.store.claim(NOW + delay)
                self.assertEqual(resumed.text, "race")
                self.store.advance(resumed, "failed")
                self.channel.send.assert_not_awaited()

    async def test_generic_vehicle_reward_does_not_acquire_a_racing_class(self):
        source = "Win a vehicle and 2 prizes. Visit a vehicle warehouse or buy a race car."
        self.response.json.return_value = {"translation": "贏得GTA0V和2份獎品。可前往載具倉庫或購買賽車。"}
        translated = await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source)
        self.assertEqual(translated, "贏得一輛載具和2份獎品。可前往載具倉庫或購買賽車。")
        self.assertEqual(self.http.post.call_args.kwargs["json"]["text"],
                         "Win GTA0V and 2 prizes. Visit a vehicle warehouse or buy a race car.")
        self.response.json.return_value = {"translation": "贏得2份獎品。"}
        with self.assertRaisesRegex(ValueError, "protected translation marker"):
            await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source)

    async def test_vehicle_modifiers_do_not_turn_into_vehicle_rewards(self):
        for source in ("Install a vehicle and weapon workshop.",
                       "Get a vehicle, weapon, or property discount."):
            with self.subTest(source=source):
                self.response.json.return_value = {"translation": "譯文"}
                self.assertEqual(await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source), "譯文")
                self.assertEqual(self.http.post.call_args.kwargs["json"]["text"], source)


class AppsScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required for the Apps Script service fixture")
    def test_deployed_source_with_fake_google_services(self):
        subprocess.run(["node", str(Path(__file__).with_name("gta_translation_script.cjs"))], check=True)
