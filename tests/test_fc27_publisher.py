import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import config
from cogs.gta_translation import GTATranslation
from cogs.update_publisher import PublisherStartView
from core.fc27_publication import BOT_ID, HUB, NEWS, Receipts, Release, ReviewError, normalized, mentioned_versions
from core.gta_translation import FC_CHANNEL_ID, GTA_CHANNEL_ID, MONTHLY_LIMIT, TranslationQueue
from core.sqlite_storage import connect_sqlite
from features.fc27_publisher import cards, publish, translated_draft


URL = NEWS + "update-v7-3-pitch-notes"
FORUM = HUB + "ea-sports-fc%E2%84%A2-27--title-update-v7-3-0/123"
DRAFT = Release.from_input("v7.3", URL + "\n" + FORUM, "Only the example on PC uses 2.50 seconds.",
                           "The example uses 2.50 seconds.")
READY = replace(DRAFT, recap="只有 PC 示範使用 2.50 秒。", gloss="示範使用 2.50 秒。")


def missing():
    return discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), {"code": 10003, "message": "unknown"})


class Surface:
    def __init__(self, store, channel_id=FC_CHANNEL_ID):
        self.store = store
        self.room = MagicMock(spec=discord.TextChannel)
        self.room.id = channel_id
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.guild = SimpleNamespace(id=config.GUILD_ID, me=self.bot.user, get_channel=lambda _: self.room)
        self.room.guild = self.guild
        self.room.permissions_for.return_value = discord.Permissions.all()
        self.rooms = {channel_id: self.room}
        self.messages = {channel_id: [SimpleNamespace(id=1, type=discord.MessageType.default, content="Earlier release",
            embeds=[], author=SimpleNamespace(id=2), webhook_id=None, jump_url="earlier")]}
        self.sequence = 100
        self.sends = []
        self.lose_reply = None
        self.empty_on_failure = False
        self.attach(self.room)
        self.bot.fetch_channel = AsyncMock(side_effect=lambda mid: self.lookup(mid))
        self.user = MagicMock(spec=discord.Member)
        self.user.id = 17
        self.user.guild_permissions = discord.Permissions(manage_guild=True)
        self.provider = AsyncMock(side_effect=lambda text, **kw: READY.recap if text == DRAFT.english else READY.gloss)
        self.bot.get_cog.return_value = SimpleNamespace(translate_reviewed=self.provider)

    def lookup(self, mid):
        if mid not in self.rooms:
            raise missing()
        return self.rooms[mid]

    def attach(self, room):
        async def history(**kw):
            for message in self.messages[room.id][:kw["limit"]]:
                yield message

        async def send(**kwargs):
            self.sends.append(kwargs)
            self.sequence += 1
            mid = self.sequence
            message = SimpleNamespace(id=mid, author=self.bot.user, embeds=[kwargs["embed"]], webhook_id=None,
                                      content="", type=discord.MessageType.default, jump_url=f"https://discord.test/{mid}")

            async def make_thread(name, auto_archive_duration):
                self.assert_unused(mid)
                t = MagicMock(spec=discord.Thread)
                t.id, t.parent_id, t.guild, t.name = mid, room.id, self.guild, name
                t.type = discord.ChannelType.public_thread
                t.permissions_for.return_value = discord.Permissions.all()
                self.rooms[mid] = t
                self.messages[mid] = []
                self.attach(t)
                return t
            message.create_thread = make_thread
            if room.id == self.lose_reply:
                self.lose_reply = None
                if not self.empty_on_failure:
                    self.messages[room.id].append(message)
                raise TimeoutError()
            self.messages[room.id].append(message)
            return message
        room.history = history
        room.send = send
        room.fetch_message = AsyncMock(side_effect=lambda mid: next(m for m in self.messages[room.id] if m.id == mid))

    def assert_unused(self, mid):
        if mid in self.rooms:
            raise AssertionError("attempted duplicate thread")

    def interaction(self):
        return SimpleNamespace(guild=self.guild, guild_id=self.guild.id, user=self.user, client=self.bot,
                               response=AsyncMock(), followup=AsyncMock())


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.store = Receipts(self.directory / "gta_translation.sqlite3")
        self.ui = Surface(self.store)

    async def enter(self, *, resume=False):
        i = self.ui.interaction()
        menu = PublisherStartView(owner_id=i.user.id, guild_id=i.guild_id)
        button = next(b for b in menu.children if b.label == "FC27 官方更新")
        await button.callback(i)
        modal = i.response.send_modal.await_args.args[0]
        inputs = [(modal.version, "7.3")] if resume else [
            (modal.version, "7.3"), (modal.links, "\n".join(DRAFT.urls)),
            (modal.notes, DRAFT.english), (modal.quote, DRAFT.quote)]
        for item, value in inputs:
            item._refresh_state(i, {"value": value})
        with patch("features.fc27_review_ui.DATA_DIR", self.directory):
            await modal.on_submit(i)
        return i, i.followup.send.await_args.kwargs["view"]

    async def test_menu_preview_edit_publish_restart_replay(self):
        i, first = await self.enter()
        self.assertTrue(i.followup.send.await_args.kwargs["ephemeral"])
        self.assertFalse(self.ui.sends)
        await first.edit.callback(i)
        edit = i.response.send_modal.await_args.args[0]
        edit.recap._refresh_state(i, {"value": "僅 PC 示範使用 2.50 秒。"})
        edit.gloss._refresh_state(i, {"value": READY.gloss})
        await edit.on_submit(i)
        revised = i.response.edit_message.await_args.kwargs["view"]
        await revised.confirm.callback(i)
        self.assertEqual(len(self.ui.sends), 2)
        self.assertEqual(self.ui.sends[0]["embed"].description, revised.draft.recap)
        self.assertIn(DRAFT.quote, self.ui.sends[1]["embed"].description)
        for k in self.ui.sends:
            self.assertEqual(k["allowed_mentions"].to_dict(), {"parse": []})
            self.assertTrue(k["silent"])
        i, reopened = await self.enter(resume=True)
        await reopened.confirm.callback(i)
        self.assertIn("英文來源串", i.followup.send.await_args.args[0])
        self.assertEqual(self.ui.provider.await_count, 2)
        self.assertEqual(len(self.ui.sends), 2)

    async def test_permissions_owner_guild_bot_destination_and_quota_before_writes(self):
        i, view = await self.enter()
        self.ui.user.guild_permissions = discord.Permissions.none()
        await view.confirm.callback(i)
        i.response.send_message.assert_awaited()
        self.ui.user.guild_permissions = discord.Permissions.all()
        self.ui.user.id = 18
        await view.confirm.callback(i)
        self.assertIsNone(self.store.receipt("7.3.0"))
        for field, obj, value in [("id", self.ui.guild, 3), ("id", self.ui.bot.user, 42),
                                  ("id", self.ui.room, GTA_CHANNEL_ID)]:
            with patch.object(obj, field, value), self.assertRaises(ReviewError):
                await publish(self.ui.bot, self.ui.guild, self.store, READY)
        self.assertFalse(self.ui.sends)

    async def test_ambiguous_send_reconciles_parent_and_source_across_restart(self):
        self.ui.lose_reply = FC_CHANNEL_ID
        with self.assertRaises(TimeoutError):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        self.assertEqual(self.store.receipt("7.3.0")[1], "parent_pending")
        self.ui.lose_reply = self.ui.messages[FC_CHANNEL_ID][-1].id
        with self.assertRaises(TimeoutError):
            await publish(self.ui.bot, self.ui.guild, Receipts(self.store.path), READY)
        self.assertEqual(self.store.receipt("7.3.0")[1], "source_pending")
        links = await publish(self.ui.bot, self.ui.guild, Receipts(self.store.path), READY)
        self.assertEqual(len(links), 2)
        self.assertEqual(len(self.ui.sends), 2)
        self.assertEqual(len(self.ui.rooms), 2)

    async def test_ambiguous_missing_message_never_blindly_retried(self):
        self.ui.lose_reply, self.ui.empty_on_failure = FC_CHANNEL_ID, True
        with self.assertRaises(TimeoutError):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        with self.assertRaisesRegex(ReviewError, "確認"):
            await publish(self.ui.bot, self.ui.guild, Receipts(self.store.path), READY)
        self.assertEqual(len(self.ui.sends), 1)

    async def test_legacy_parent_blocks_second_publication(self):
        self.ui.messages[FC_CHANNEL_ID].append(SimpleNamespace(type=discord.MessageType.default, content="FC27 v7.3",
            embeds=[], author=SimpleNamespace(id=2), webhook_id=None, jump_url="https://discord.test/legacy"))
        with self.assertRaisesRegex(ReviewError, "legacy"):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        self.assertFalse(self.ui.sends)

    async def relay(self, version):
        cog = GTATranslation(self.ui.bot, TranslationQueue(self.store.path), None, "", "")
        with patch.object(cog, "process"):
            msg = SimpleNamespace(guild=self.ui.guild, channel=self.ui.room, webhook_id=1, id=10000,
                flags=discord.MessageFlags(is_crossposted=True), type=discord.MessageType.default,
                reference=None, embeds=[], content=f"EA SPORTS FC™ 27 | Title Update v{version} is available")
            await cog.on_message(msg)

    async def test_relay_and_review_both_arrival_orders(self):
        await self.relay("7.3")
        with self.assertRaisesRegex(ReviewError, "轉發"):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        with self.assertRaisesRegex(ReviewError, "轉發"):
            await translated_draft(self.store, DRAFT, self.ui.provider)
        self.ui.provider.assert_not_awaited()
        with connect_sqlite(self.store.path) as db:
            db.execute("DELETE FROM posts")
            db.execute("DELETE FROM fc27_delivery_owner")
        await publish(self.ui.bot, self.ui.guild, self.store, READY)
        await self.relay("7.3.0")
        self.assertIsNone(TranslationQueue(self.store.path).claim(1))
        self.assertEqual(len(self.ui.sends), 2)

    async def test_cache_shared_budget_and_single_claim(self):
        await asyncio.gather(*[translated_draft(self.store, DRAFT, self.ui.provider) for _ in range(2)],
                             return_exceptions=True)
        await translated_draft(Receipts(self.store.path), DRAFT, self.ui.provider)
        self.assertEqual(self.ui.provider.await_count, 2)
        with connect_sqlite(self.store.path) as db:
            self.assertEqual(db.execute("SELECT SUM(characters) FROM usage").fetchone()[0],
                             len(DRAFT.quote) + len(DRAFT.english))
            db.execute("UPDATE usage SET characters=?", (MONTHLY_LIMIT,))
        with self.assertRaisesRegex(ReviewError, "共用"):
            await translated_draft(self.store, replace(DRAFT, english="Changed notes"), self.ui.provider)
        with connect_sqlite(self.store.path) as db:
            db.execute("UPDATE usage SET characters=0")
            db.execute("UPDATE fc27_source_usage SET characters=6000")
        with self.assertRaisesRegex(ReviewError, "來源"):
            await translated_draft(self.store, replace(DRAFT, english="Changed notes"), self.ui.provider)
        self.assertEqual(self.ui.provider.await_count, 2)

    def test_source_validation_and_numeric_precision(self):
        for url in (URL + "?target=x", FORUM.replace("forums.ea.com", "other.org"), NEWS + "update-v8-0-pitch-notes",
                    "https://forums.ea.com/discussions/fc27/123", "https://www.ea.com@other.org/news"):
            with self.assertRaises(ReviewError):
                Release.from_input("7.3", url, DRAFT.english, DRAFT.quote)
        with self.assertRaises(ReviewError):
            Release.from_input("7.3", URL, DRAFT.english, "word " * 26)
        with self.assertRaises(ReviewError):
            replace(READY, gloss="示範為 2.5 秒。").check_translation()
        self.store.check_sources(DRAFT)
        with self.assertRaisesRegex(ReviewError, "另一版本"):
            self.store.check_sources(Release.from_input("7.4", FORUM.replace("v7-3-0", "v7-4-0"),
                                                        DRAFT.english, DRAFT.quote))
        self.assertEqual(normalized("7.3"), "7.3.0")
        self.assertEqual(mentioned_versions(URL), {"7.3.0"})
        self.assertEqual(mentioned_versions("FC26 v7.3.0"), set())

    async def test_revoked_permissions_and_foreign_operator_on_modal_and_edit(self):
        i, review = await self.enter()
        await review.edit.callback(i)
        edit = i.response.send_modal.await_args.args[0]
        other = self.ui.interaction()
        other.user = MagicMock(spec=discord.Member)
        other.user.id = 18
        other.user.guild_permissions = discord.Permissions.all()
        await edit.on_submit(other)
        other.response.send_message.assert_awaited()
        other.response.edit_message.assert_not_awaited()
        fresh = self.ui.interaction()
        menu = PublisherStartView(owner_id=fresh.user.id, guild_id=fresh.guild_id)
        await menu.fc27.callback(fresh)
        modal = fresh.response.send_modal.await_args.args[0]
        fresh.user.guild_permissions = discord.Permissions.none()
        await modal.on_submit(fresh)
        fresh.response.defer.assert_not_awaited()
        self.assertFalse(self.ui.sends)
        self.assertEqual(self.ui.provider.await_count, 2)

    async def test_failed_translation_retry_is_charged_then_cached_or_limited(self):
        url, text = DRAFT.urls[0], DRAFT.english
        _, old = self.store.translation(url, text, 1700000000)
        with self.assertRaises(ReviewError):
            self.store.translation(url, text, 1700000001)
        _, newer = self.store.translation(url, text, 1700000130)
        with self.assertRaises(ReviewError):
            self.store.cache_result(old, READY.recap)
        with self.assertRaises(ReviewError):
            self.store.translation(url, text, 1700000400)
        self.store.cache_result(newer, READY.recap)
        self.assertEqual(self.store.translation(url, text, 1700000500), (READY.recap, None))
        with connect_sqlite(self.store.path) as db:
            self.assertEqual(db.execute("SELECT characters FROM usage").fetchone()[0], 2 * len(text))

    async def test_permission_rejection_before_source_resume_and_same_version_changed_content(self):
        original = self.ui.room.send
        async def rejected(**kwargs):
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                                    {"code": 50013, "message": "Missing permissions"})
        self.ui.room.send = rejected
        with self.assertRaises(discord.Forbidden):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        self.assertEqual(self.store.receipt("7.3.0")[1], "parent")
        self.ui.room.send = original
        await publish(self.ui.bot, self.ui.guild, self.store, READY)
        with self.assertRaisesRegex(ReviewError, "確認稿"):
            await publish(self.ui.bot, self.ui.guild, self.store, replace(READY, recap="另一版本 2.50 秒。"))
        self.assertEqual(len(self.ui.sends), 2)

    async def test_other_patch_version_is_independent_and_english_is_preview_only(self):
        i, review = await self.enter()
        self.assertEqual(i.followup.send.await_args.kwargs["embeds"][-1].description, DRAFT.english)
        self.ui.messages[FC_CHANNEL_ID].append(SimpleNamespace(type=discord.MessageType.default,
            content="FC27 v7.3.1", embeds=[], author=SimpleNamespace(id=1), webhook_id=None, jump_url="elsewhere"))
        await review.confirm.callback(i)
        parent, source = [k["embed"] for k in self.ui.sends]
        self.assertEqual(parent.description, READY.recap)
        self.assertTrue(all(url in source.description for url in DRAFT.urls))
        self.assertIn(DRAFT.quote, source.description)
        self.assertNotIn(DRAFT.english, source.description)
        with self.assertRaises(ReviewError):
            replace(READY, english="Slightly decreased from -2.50%.", recap="略為減至 +2.50%。").check_translation()

    async def test_overlapping_confirmation_has_only_one_writer(self):
        posted = self.ui.room.send
        entered, resume = asyncio.Event(), asyncio.Event()

        async def delayed(**kwargs):
            entered.set()
            await resume.wait()
            return await posted(**kwargs)
        self.ui.room.send = delayed
        first = asyncio.create_task(publish(self.ui.bot, self.ui.guild, self.store, READY))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with self.assertRaisesRegex(ReviewError, "確認"):
                await publish(self.ui.bot, self.ui.guild, Receipts(self.store.path), READY)
        finally:
            resume.set()
            await first
        self.assertEqual(len(self.ui.sends), 2)

    async def test_admin_tool_entry_reaches_reviewed_intake_without_sending(self):
        from cogs.update_publisher import UpdatePublisher
        from features.admin_actions import admin_update_publisher_from_button

        i = self.ui.interaction()
        i.response.is_done = lambda: True
        i.client.get_cog.return_value = UpdatePublisher(i.client)
        with (patch("cogs.update_publisher.latest_announcement_version", return_value=(4, 0, 0)),
              patch("cogs.update_publisher.get_pending_games", return_value=[]),
              patch("cogs.update_publisher.version_guidance", return_value="下一版")):
            await admin_update_publisher_from_button(i)
        menu = i.followup.send.await_args.kwargs["view"]
        await menu.fc27.callback(i)
        self.assertEqual(i.response.send_modal.await_args.args[0].title, "FC27 官方更新")
        self.assertFalse(self.ui.sends)
