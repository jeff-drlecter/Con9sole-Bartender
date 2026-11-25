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
from core.gta_translation import GTA_CHANNEL_ID, HONG_KONG, LEASE_SECONDS, MONTHLY_LIMIT, TranslationQueue
from core.sqlite_storage import connect_sqlite


NOW = datetime(2026, 12, 31, 23, 59, 59, tzinfo=HONG_KONG).timestamp()
TEST_URL = "https://script.google.com/macros/s/test/exec"
TEST_TOKEN = "a" * 64


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
        self.store.add(2, 11, "🏁a")
        self.store.add(3, 12, "bc")
        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: TranslationQueue(self.path).claim(NOW), range(2)))
        self.assertEqual([j.message_id for j in jobs if j], [2])
        self.assertIsNone(self.store.claim(NOW))
        reopened = TranslationQueue(self.path)
        self.assertEqual(reopened.claim(NOW + 1).message_id, 3)
        with connect_sqlite(self.path) as db:
            self.assertEqual(dict(db.execute("SELECT * FROM usage")),
                             {"2026-12": MONTHLY_LIMIT, "2027-01": 2})

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
        self.thread = SimpleNamespace(id=111, parent_id=GTA_CHANNEL_ID, send=AsyncMock())
        self.message = MagicMock(id=111, thread=None)
        self.message.fetch_thread = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "absent"))
        self.message.create_thread = AsyncMock(return_value=self.thread)
        self.channel = SimpleNamespace(guild=SimpleNamespace(id=config.GUILD_ID),
                                       get_partial_message=MagicMock(return_value=self.message))
        self.bot = MagicMock()
        self.bot.get_channel.return_value = self.channel
        self.http = MagicMock()
        self.response = self.http.post.return_value.__aenter__.return_value
        self.response.status = 200
        self.response.raise_for_status = MagicMock()
        self.response.json = AsyncMock(return_value={"translation": "新賽道 & 新車"})
        self.cog = pilot.GTATranslation(self.bot, self.store, self.http, TEST_URL, TEST_TOKEN)

    async def test_official_post_to_one_thread_and_one_translation_across_replays(self):
        embed = discord.Embed(title="New race", description="Drive [now](https://example.com/gta)")
        embed.add_field(name="Reward", value="2x XP")
        entry = post(content="New race <@&123>", embeds=[embed])
        await asyncio.gather(self.cog.on_message(entry), self.cog.on_message(post(112)))
        # Both messages reference the same original; ordering is unspecified.
        key = self.store.claim(NOW)
        self.message.id = self.thread.id = key.message_id
        text = key.text
        self.assertIn(text, ("New race", "New race\n\nDrive now\n\nReward\n\n2x XP"))
        self.assertEqual(pilot.source_text(entry), "New race\n\nDrive now\n\nReward\n\n2x XP")
        await self.cog.process_job(key)
        self.http.post.assert_called_once_with(TEST_URL, json={"text": text, "token": TEST_TOKEN},
                                               allow_redirects=False)
        delivery = TranslationQueue(self.path).claim(NOW)
        await self.cog.process_job(delivery)
        await self.cog.on_message(entry)
        self.assertIsNone(self.store.claim(NOW + 2 * LEASE_SECONDS))
        self.message.create_thread.assert_awaited_once()
        self.thread.send.assert_awaited_once()
        args, kwargs = self.thread.send.await_args
        self.assertIn("新賽道 & 新車", args[0])
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.assertTrue(kwargs["silent"])
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
                         "Newswire")
        await self.cog.on_message(post(reference=None))
        await self.cog.on_message(post(reference=None))
        self.assertEqual(self.store.claim(NOW).message_id, 111)
        self.assertIsNone(self.store.claim(NOW))

    async def test_resume_translation_in_existing_thread_with_long_utf16_output(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "🏁" * 1200)
        self.message.fetch_thread = AsyncMock(return_value=self.thread)
        async def inspect_upload(content, *, file, **kwargs):
            self.assertEqual(file.fp.read().decode("utf-8"), "🏁" * 1200)
            self.assertEqual(file.filename, "GTA-繁中翻譯.txt")
        self.thread.send.side_effect = inspect_upload
        await self.cog.process_job(TranslationQueue(self.path).claim(NOW))
        self.message.create_thread.assert_not_awaited()
        self.http.post.assert_not_called()

    async def test_ambiguous_send_cannot_be_replayed(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "測試")
        job = self.store.claim(NOW)
        self.message.thread = self.thread
        self.thread.send.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await self.cog.process_job(job)
        await self.cog.process_job(job)
        self.assertIsNone(TranslationQueue(self.path).claim(NOW + 3600))
        self.thread.send.assert_awaited_once()

    async def test_recover_thread_creation_race(self):
        self.message.fetch_thread.side_effect = [discord.NotFound(MagicMock(status=404), "absent"),
                                                 self.thread]
        self.message.create_thread.side_effect = discord.HTTPException(MagicMock(status=400),
                                                          {"code": 160004, "message": "already exists"})
        self.assertIs(await pilot.thread_for(self.message), self.thread)

    async def test_definite_send_rejection_reuses_translation_and_thread(self):
        await self.cog.on_message(post())
        self.store.advance(self.store.claim(NOW), "deliver", "測試")
        self.message.thread = self.thread
        self.thread.send.side_effect = [discord.Forbidden(MagicMock(status=403), "permission"), None]
        with self.assertRaises(discord.Forbidden):
            await self.cog.process_job(self.store.claim(NOW))
        await self.cog.process_job(self.store.claim(NOW + LEASE_SECONDS))
        self.assertIsNone(self.store.claim(NOW + 3600))
        self.message.create_thread.assert_not_awaited()
        self.http.post.assert_not_called()

    async def test_provider_failure_creates_no_thread_and_budget_is_kept(self):
        self.response.status = 503
        await self.cog.on_message(post())
        await self.cog.process.coro(self.cog)
        self.message.create_thread.assert_not_awaited()
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
                self.message.create_thread.assert_not_awaited()

    async def test_generic_vehicle_reward_does_not_acquire_a_racing_class(self):
        source = "Win a vehicle and 2 prizes. Visit a vehicle warehouse or buy a race car."
        self.response.json.return_value = {"translation": "贏得GTA0V和2份獎品。可前往載具倉庫或購買賽車。"}
        translated = await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source)
        self.assertEqual(translated, "贏得一輛載具和2份獎品。可前往載具倉庫或購買賽車。")
        self.assertEqual(self.http.post.call_args.kwargs["json"]["text"],
                         "Win GTA0V and 2 prizes. Visit a vehicle warehouse or buy a race car.")
        self.response.json.return_value = {"translation": "贏得2份獎品。"}
        with self.assertRaisesRegex(ValueError, "protected GTA term"):
            await pilot.translate(self.http, TEST_URL, TEST_TOKEN, source)


class AppsScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required for the Apps Script service fixture")
    def test_deployed_source_with_fake_google_services(self):
        subprocess.run(["node", str(Path(__file__).with_name("gta_translation_script.cjs"))], check=True)
