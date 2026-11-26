"""Exercise the private publisher with synthetic messages and an isolated receipt database."""
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from cogs.gta_translation import GTATranslation
from cogs.update_publisher import UpdatePublisher
from core import apex_updates
from core.fc27_publication import Receipts, Release, ReviewError
from core.gta_translation import APEX_CHANNEL_ID, FC_CHANNEL_ID, MONTHLY_LIMIT, TranslationQueue
from core.sqlite_storage import connect_sqlite
from features.admin_actions import admin_update_publisher_from_button
from features.fc27_publisher import publish, translated_draft
from features.fc27_review_ui import Review
from test_fc27_publisher import READY as FC_RELEASE, Surface


DAY = "2026-11-25"
HOTFIX = apex_updates.HUB + "apex-legends-latest-update---11-252026/13898085"
PATCH = apex_updates.NEWS + "cipher-patch-notes"
DRAFT = Release.from_input(DAY, HOTFIX, "The example lasts 2.50 seconds on PC.",
                           "The example lasts 2.50 seconds.", game="apex")
READY = replace(DRAFT, recap="此示例在 PC 上持續 2.50 秒。", gloss="此示例持續 2.50 秒。")


class ApexPublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.store = Receipts(self.directory / "gta_translation.sqlite3")
        self.ui = Surface(self.store, APEX_CHANNEL_ID)
        self.provider = AsyncMock(side_effect=lambda text, **kw: READY.recap if text == DRAFT.english else READY.gloss)

    async def menu(self, i):
        i.response.is_done = lambda: True
        publisher = UpdatePublisher(i.client)
        i.client.get_cog.side_effect = lambda name: {
            "UpdatePublisher": publisher,
            "GTATranslation": SimpleNamespace(translate_reviewed=self.provider),
        }.get(name)
        with (patch("cogs.update_publisher.latest_announcement_version", return_value=(4, 0, 0)),
              patch("cogs.update_publisher.get_pending_games", return_value=[]),
              patch("cogs.update_publisher.version_guidance", return_value="下一版")):
            await admin_update_publisher_from_button(i)
        return i.followup.send.await_args.kwargs["view"]

    async def enter(self, *, resume=False):
        i = self.ui.interaction()
        menu = await self.menu(i)
        await menu.apex.callback(i)
        modal = i.response.send_modal.await_args.args[0]
        self.assertEqual(modal.title, "Apex 官方更新")
        self.assertIn("2026-11-25", modal.version.placeholder)
        inputs = [(modal.version, DAY)]
        if not resume:
            inputs += [(modal.links, HOTFIX), (modal.notes, DRAFT.english), (modal.quote, DRAFT.quote)]
        for item, value in inputs:
            item._refresh_state(i, {"value": value})
        with patch("features.fc27_review_ui.DATA_DIR", self.directory):
            await modal.on_submit(i)
        response = i.followup.send.await_args.kwargs
        self.assertTrue(response["ephemeral"])
        return i, response["view"]

    async def test_private_entry_edit_silent_publish_and_restart_replay(self):
        i, review = await self.enter()
        preview = i.followup.send.await_args.kwargs["embeds"]
        self.assertEqual(preview[0].title, "Apex Legends 2026-11-25｜Con9sole 繁中整理")
        self.assertIn(DRAFT.english, preview[2].description)
        self.assertFalse(self.ui.sends)
        for call in self.provider.await_args_list:
            self.assertEqual(call.kwargs["channel_id"], APEX_CHANNEL_ID)
        await review.edit.callback(i)
        edit = i.response.send_modal.await_args.args[0]
        edit.recap._refresh_state(i, {"value": READY.recap})
        edit.gloss._refresh_state(i, {"value": READY.gloss})
        await edit.on_submit(i)
        await i.response.edit_message.await_args.kwargs["view"].confirm.callback(i)
        self.assertEqual(len(self.ui.sends), 2)
        parent, source = self.ui.sends
        self.assertEqual(parent["embed"].description, READY.recap)
        self.assertIn("EA · Apex Legends", source["embed"].description)
        self.assertTrue(all(s in source["embed"].description for s in (DRAFT.quote, READY.gloss, HOTFIX)))
        self.assertNotIn(DRAFT.english, source["embed"].description)
        for sent in self.ui.sends:
            self.assertTrue(sent["silent"])
            self.assertEqual(sent["allowed_mentions"].to_dict(), {"parse": []})
        fresh, saved = await self.enter(resume=True)
        await saved.confirm.callback(fresh)
        self.assertIn("英文來源串", fresh.followup.send.await_args.args[0])
        self.assertEqual((len(self.ui.sends), self.provider.await_count), (2, 2))

    async def relay(self, message_text):
        cog = GTATranslation(self.ui.bot, TranslationQueue(self.store.path), None, "", "")
        msg = SimpleNamespace(guild=self.ui.guild, channel=self.ui.room, webhook_id=1, id=500,
                              flags=discord.MessageFlags(is_crossposted=True), type=discord.MessageType.default,
                              reference=None, embeds=[], content=message_text)
        await cog.on_message(msg)

    async def test_relay_first_blocks_review_before_translation(self):
        await self.relay("Apex Legends: Latest Update - 11/ 25/2026")
        with self.assertRaisesRegex(ReviewError, "轉發"):
            await translated_draft(self.store, DRAFT, self.provider)
        self.provider.assert_not_awaited()
        self.assertIsNotNone(TranslationQueue(self.store.path).claim(1))
        self.assertIsNone(self.store.receipt(DRAFT.key))

    async def test_review_first_recognizes_relay_without_retranslating(self):
        await publish(self.ui.bot, self.ui.guild, self.store, READY)
        await self.relay("Map change " + HOTFIX.replace("latest-update---11-252026", "hotfix") + "?campaign=link")
        self.assertIsNone(TranslationQueue(self.store.path).claim(1))

    async def test_official_patch_mirror_and_multi_article_roundup(self):
        patch = replace(READY, version="7.3.0", urls=(PATCH,))
        await publish(self.ui.bot, self.ui.guild, self.store, patch)
        forum = apex_updates.HUB + "apex-legends%E2%84%A2-cipher-patch-notes/13845884"
        await translated_draft(self.store, patch, self.provider)
        await translated_draft(self.store, replace(patch, urls=(forum,)), self.provider)
        self.assertEqual(self.provider.await_count, 2)
        await self.relay("Patch Notes " + forum)
        self.assertIsNone(TranslationQueue(self.store.path).claim(1))
        with self.assertRaisesRegex(ReviewError, "另一版本"):
            self.store.check_sources(replace(patch, version="7.4.0", urls=(forum,)))
        await self.relay("Patch roundup " + forum + " and " + HOTFIX)
        self.assertIsNotNone(TranslationQueue(self.store.path).claim(1))

    async def test_partial_send_and_wrong_channel(self):
        self.ui.room.id = FC_CHANNEL_ID
        with self.assertRaisesRegex(ReviewError, "頻道"):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        self.assertIsNone(self.store.receipt(READY.key))
        self.ui.room.id = APEX_CHANNEL_ID
        self.ui.lose_reply = APEX_CHANNEL_ID
        with self.assertRaises(TimeoutError):
            await publish(self.ui.bot, self.ui.guild, self.store, READY)
        await publish(self.ui.bot, self.ui.guild, Receipts(self.store.path), READY)
        self.assertEqual(len(self.ui.sends), 2)
        self.assertEqual(self.store.receipt(READY.key)[1], "done")

    async def test_private_operator_identity_and_revoked_permissions(self):
        i = self.ui.interaction()
        menu = await self.menu(i)
        self.ui.user.guild_permissions = discord.Permissions.none()
        await menu.apex.callback(i)
        i.response.send_modal.assert_not_awaited()
        self.ui.user.guild_permissions = discord.Permissions.all()
        i, view = await self.enter()
        self.ui.user.id += 1
        await view.confirm.callback(i)
        i.response.send_message.assert_awaited()
        self.assertFalse(self.ui.sends)

    async def test_edit_looks_up_selected_game_receipt(self):
        self.store.begin(FC_RELEASE)
        apex = replace(READY, version=FC_RELEASE.version, urls=(PATCH,))
        i = self.ui.interaction()
        view = Review(i.user.id, self.store, apex)
        await view.edit.callback(i)
        i.response.send_modal.assert_awaited_once()
        self.store.begin(apex)
        await view.edit.callback(i)
        i.response.send_modal.assert_awaited_once()
        i.response.send_message.assert_awaited_once()
        self.assertTrue(i.response.send_message.await_args.kwargs["ephemeral"])

    def test_separate_keys_for_same_version_and_legacy_fc_packet(self):
        apex = Release.from_input(FC_RELEASE.version, PATCH, DRAFT.english, DRAFT.quote, game="apex")
        self.store.begin(FC_RELEASE)
        self.store.begin(replace(apex, recap=READY.recap, gloss=READY.gloss))
        old = self.store.receipt(FC_RELEASE.version)[0]
        self.assertNotIn("game", json.loads(old))
        self.assertEqual(Release.unpack(old).pack(), old)
        self.assertEqual(Release.unpack(self.store.receipt(apex.key)[0]).game, "apex")
        self.assertNotEqual(FC_RELEASE.key, apex.key)

    async def test_alias_and_monthly_limits_before_provider(self):
        await translated_draft(self.store, DRAFT, self.provider)
        alias = replace(DRAFT, urls=(HOTFIX.replace("latest-update---11-252026", "hotfix"),))
        await translated_draft(self.store, alias, self.provider)
        self.assertEqual(self.provider.await_count, 2)
        self.store.begin(READY)
        with self.assertRaisesRegex(ReviewError, "另一版本"):
            self.store.check_sources(replace(alias, version="2026-11-26"))
        with connect_sqlite(self.store.path) as db:
            actual = db.execute("SELECT sum(characters) FROM usage").fetchone()[0]
            self.assertEqual(actual, len(DRAFT.english) + len(DRAFT.quote))
            db.execute("UPDATE usage SET characters=?", (MONTHLY_LIMIT,))
        with self.assertRaisesRegex(ReviewError, "共用"):
            await translated_draft(self.store, replace(DRAFT, english="Another example."), self.provider)
        with connect_sqlite(self.store.path) as db:
            db.execute("UPDATE usage SET characters=0")
            db.execute("UPDATE fc27_source_usage SET characters=6000")
        with self.assertRaisesRegex(ReviewError, "來源"):
            await translated_draft(self.store, replace(DRAFT, english="Another example."), self.provider)
        self.assertEqual(self.provider.await_count, 2)

    def test_article_and_release_validation(self):
        self.assertEqual(apex_updates.dated_hotfix(HOTFIX), DAY)
        self.assertEqual(apex_updates.dated_hotfix(apex_updates.HUB + "apex-legends-latest-update-18-11-2026/1"),
                         "2026-11-18")
        for label, link in (("2026-11-24", HOTFIX), ("2026-02-30", PATCH),
                            ("1.2.3", HOTFIX + " " + apex_updates.HUB + "apex-legends-hotfix-18-11-2026/13885172"),
                            ("1.2.3", PATCH + " " + apex_updates.NEWS + "other-patch-notes"),
                            (DAY, FC_RELEASE.urls[0]), (DAY, "https://trello.com/b/ZVrHV38P/apex-tracker"),
                            (DAY, apex_updates.NEWS + "ranked-roadmap"), (DAY, PATCH + "?next=test"),
                            (DAY, "https://forums.ea.com/discussions/apex-legends-general-discussion/hotfix/1"),
                            (DAY, apex_updates.NEWS + "../news/cipher-patch-notes"),
                            (DAY, apex_updates.HUB + "apex-legends-latest-update/123/replies/456")):
            with self.subTest(label=label, link=link), self.assertRaises(ReviewError):
                Release.from_input(label, link, DRAFT.english, DRAFT.quote, game="apex")
        with self.assertRaises(ReviewError):
            Release.from_input(DAY, HOTFIX, "@everyone", DRAFT.quote, game="apex")
        with self.assertRaises(ReviewError):
            replace(READY, recap="示例使用 2.5 秒。").check_translation()
