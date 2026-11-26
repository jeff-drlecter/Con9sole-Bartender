from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.update_publisher import PublisherStartView
from core.gta_translation import TranslationQueue
from core.reviewed_games import NBA_PAGE
from core.sqlite_storage import connect_sqlite
from features.official_reply import ConfirmReply, Draft, inspect_original, receipt
from core.fc27_publication import ReviewError
from test_fc27_publisher import Surface


class OfficialReplyTests(IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.q = TranslationQueue(self.dir / "gta_translation.sqlite3")
        self.ui = Surface(self.q, 1424320426095415397)
        self.i = self.ui.interaction()
        self.channel = self.ui.room
        self.msg = MagicMock(spec=discord.Message)
        self.msg.id = 1572534310077079632
        self.msg.content = "PATCH NOTES v3.0"
        self.msg.channel = self.channel
        self.msg.type = discord.MessageType.default
        self.msg.reference = None
        self.msg.flags = discord.MessageFlags(is_crossposted=True)
        self.msg.webhook_id = 1
        self.msg.embeds = []
        self.link = f"https://discord.com/channels/{self.i.guild.id}/{self.channel.id}/{self.msg.id}"
        self.msg.jump_url = self.link
        self.ui.messages[self.channel.id] = [self.msg]
        self.channel.send = AsyncMock()
        self.draft = Draft.parse(self.link, "v3.0", "繁中測試", NBA_PAGE)

    async def test_user_entry_and_silent_reply(self):
        panel = PublisherStartView(owner_id=self.i.user.id, guild_id=self.i.guild.id)
        await panel.existing_reply.callback(self.i)
        modal = self.i.response.send_modal.await_args.args[0]
        for field, value in zip(modal.children, [self.link, "v3.0", "繁中測試", NBA_PAGE]):
            field._refresh_state(self.i, {"value": value})
        with patch("features.official_reply.DATA_DIR", self.dir):
            await modal.on_submit(self.i)
        preview = self.i.followup.send.await_args.kwargs
        self.assertTrue(preview["ephemeral"])
        self.channel.send.assert_not_awaited()
        await preview["view"].confirm.callback(self.i)
        self.channel.send.assert_awaited_once()
        kwargs = self.channel.send.await_args.kwargs
        self.assertTrue(kwargs["silent"])
        self.assertFalse(kwargs["mention_author"])
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.msg.to_reference.assert_called_once_with(fail_if_not_exists=True)
        self.assertIn(NBA_PAGE, self.channel.send.await_args.args[0])
        with connect_sqlite(self.q.path) as db:
            self.assertEqual(db.execute("SELECT stage FROM posts").fetchone()[0], "sent")
        await preview["view"].confirm.callback(self.i)
        self.channel.send.assert_awaited_once()

    async def test_lost_response_and_automatic_follow_compete(self):
        self.channel.send.side_effect = TimeoutError()
        view = ConfirmReply(self.i.user.id, self.q, self.draft)
        await view.confirm.callback(self.i)
        self.q.add(self.msg.id, self.msg.id, "legacy", channel_id=self.channel.id)
        self.assertIsNone(self.q.claim(1))
        await ConfirmReply(self.i.user.id, TranslationQueue(self.q.path), self.draft).confirm.callback(self.i)
        self.channel.send.assert_awaited_once()

    async def test_existing_translation_or_inflight_blocks_preview(self):
        existing = MagicMock(spec=discord.Message)
        existing.content, existing.embeds = "2K v3.0 繁中整理", []
        existing.reference = None
        self.ui.messages[self.channel.id].append(existing)
        with self.assertRaises(ReviewError):
            await inspect_original(self.i, self.draft, self.q)
        self.ui.messages[self.channel.id].pop()
        self.q.add(self.msg.id, self.msg.id, "already queued", channel_id=self.channel.id)
        with self.assertRaises(ReviewError):
            receipt(self.q, self.msg, {"nba27:3.0"}, True)

    async def test_revoke_delete_or_change_after_preview(self):
        self.i.user.guild_permissions = discord.Permissions.none()
        await ConfirmReply(self.i.user.id, self.q, self.draft).confirm.callback(self.i)
        self.i.response.send_message.assert_awaited_once()
        self.channel.send.assert_not_awaited()
        self.i.user.guild_permissions = discord.Permissions.all()
        self.msg.content = "PATCH NOTES v3.0.1"
        with self.assertRaises(ReviewError):
            await inspect_original(self.i, self.draft, self.q)
        self.msg.content = "PATCH NOTES v3.0"
        self.msg.webhook_id = None
        with self.assertRaises(ReviewError):
            await inspect_original(self.i, self.draft, self.q)
        self.channel.fetch_message.side_effect = discord.NotFound(MagicMock(status=404), "deleted")
        await ConfirmReply(self.i.user.id, self.q, self.draft).confirm.callback(self.i)
        self.channel.send.assert_not_awaited()

    async def test_foreign_link_and_thread_or_new_reply_stop_confirmation(self):
        draft = Draft.parse(self.link, "v3.0", "測試", "https://discord.com/channels/123456789012345678/234567890123456789/345678901234567890")
        with self.assertRaisesRegex(ReviewError, "來源"):
            await inspect_original(self.i, draft, self.q)
        existing = MagicMock(spec=discord.Message)
        existing.reference.message_id = self.msg.id
        existing.content, existing.embeds = "", []
        self.ui.messages[self.channel.id].append(existing)
        await ConfirmReply(self.i.user.id, self.q, self.draft).confirm.callback(self.i)
        self.channel.send.assert_not_awaited()
        self.ui.messages[self.channel.id].pop()
        self.msg.flags = discord.MessageFlags(is_crossposted=True, has_thread=True)
        thread = MagicMock(spec=discord.Thread)
        thread.parent_id = self.channel.id
        thread.permissions_for.return_value = discord.Permissions.all()
        async def history(**kwargs):
            yield existing
        thread.history = history
        self.ui.bot.fetch_channel = AsyncMock(return_value=thread)
        with self.assertRaisesRegex(ReviewError, "討論串"):
            await inspect_original(self.i, self.draft, self.q)

    async def test_distinct_follow_origins_share_version_with_manual_confirm(self):
        from core.reviewed_games import relay_keys
        text = ":NBA2K27_Neon_1: PATCH NOTES v3.0"
        keys = tuple(relay_keys("nba27", text))
        self.assertIn("nba27:3.0", keys)
        self.q.add(self.msg.id + 1, self.msg.id + 99, text, channel_id=self.channel.id, review_keys=keys)
        with self.assertRaisesRegex(ReviewError, "同一更新"):
            await inspect_original(self.i, self.draft, self.q)

    def test_fc_source_and_history_use_normalized_version(self):
        from dataclasses import replace
        from core.fc27_publication import NEWS
        from core.gta_translation import FC_CHANNEL_ID
        from features.official_reply import version_marker, release_keys
        fc = replace(self.draft, channel=FC_CHANNEL_ID, identifier="v1.3.0", sources=(NEWS + "update-v1-3-pitch-notes",))
        self.assertIn("1.3.0", release_keys(fc, "FC27 v1.3"))
        self.assertTrue(version_marker(fc).search("FC27 v1.3｜繁中整理"))
        with self.assertRaisesRegex(ReviewError, "來源"):
            release_keys(replace(fc, sources=(NEWS + "update-v1-2-pitch-notes",)), "FC27 v1.3")

    def test_observed_follow_allows_manual_reply_but_cannot_hide_queued_work(self):
        from core.gta_translation import APEX_CHANNEL_ID, FC_CHANNEL_ID
        for channel, key in ((FC_CHANNEL_ID, "1.3.0"), (APEX_CHANNEL_ID, "apex:1.3.0")):
            with self.subTest(channel=channel):
                msg = MagicMock(id=channel, reference=None)
                msg.channel.id = channel
                paused = TranslationQueue(self.q.path, paused_follow_channels=[channel])
                paused.add(msg.id, msg.id, "Native", channel_id=channel, review_keys=(key,))
                receipt(self.q, msg, {key}, True)
                self.q.add(msg.id + 1, msg.id + 1, "Native", channel_id=channel, review_keys=(key,))
                self.assertIsNone(self.q.claim(1))
        self.q.add(123, 321, "Native", channel_id=FC_CHANNEL_ID, review_keys=("2.4.0",))
        paused = TranslationQueue(self.q.path, paused_follow_channels=[FC_CHANNEL_ID])
        paused.add(456, 654, "Native", channel_id=FC_CHANNEL_ID, review_keys=("2.4.0",))
        with self.assertRaisesRegex(ReviewError, "同一更新"):
            receipt(self.q, MagicMock(id=456, reference=None), {"2.4.0"}, True)
