from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from quick_bar_fakes import interaction, member

from cogs.cheers import Cheers
from cogs.drink import Drink
from data.drink_data import DrinkEntry
from features.member_picker import MemberPicker


class DrinkDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patches = []

        def stub(name, **kwargs):
            patcher = patch(f"cogs.drink.{name}", **kwargs)
            value = patcher.start()
            self.patches.append(patcher)
            return value

        self.cooldown = stub("get_drink_retry_after", return_value=0)
        self.gift_cooldown = stub("get_gift_drink_retry_after", return_value=0)
        self.touch = stub("touch_drink_cooldown")
        self.touch_gift = stub("touch_gift_drink_cooldown")
        self.history = stub("save_recent_draws")

        def recorded(**kwargs):
            kwargs["progress"].update(is_new=True, unlocked=["初嚐一杯"], total=1)
            return True

        self.record = stub("record_drink_event", side_effect=recorded)
        stub("init_drink_events_db")
        stub("load_recent_draw_map", return_value={})
        stub("pick_rarity", return_value="Rare")
        self.drink = DrinkEntry(
            eng="Test", zh="測試", desc="Test", typ="short", rarity="Rare"
        )
        stub("pick_weighted_drink", return_value=self.drink)
        self.cog = Drink(MagicMock())
        self.cog._record_usage = AsyncMock()
        self.cog._complete_daily_bar = AsyncMock()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    async def test_delivered_result_commits_cooldown_history_and_event(self):
        i = interaction()
        self.assertTrue(await self.cog.do_drink(i))
        i.response.defer.assert_awaited_once_with(thinking=True, ephemeral=False)
        self.touch.assert_called_once_with(i.user.id)
        self.history.assert_called_once()
        self.record.assert_called_once()
        payload = i.edit_original_response.await_args_list[0].kwargs
        self.assertEqual(payload["embed"].fields[0].name, "✨ 新收藏")
        self.assertNotIn("file", payload)

    async def test_storage_failure_never_claims_collection_or_milestone(self):
        self.record.side_effect = None
        self.record.return_value = False
        i = interaction()
        self.assertTrue(await self.cog.do_drink(i))
        self.assertEqual(i.edit_original_response.await_count, 1)
        self.assertEqual(
            len(i.edit_original_response.await_args.kwargs["embed"].fields), 0
        )
        self.assertIn("保存唔到", i.followup.send.await_args.args[0])

    async def test_notice_edit_failure_does_not_undo_saved_drink(self):
        i = interaction()
        i.edit_original_response.side_effect = [
            None,
            discord.HTTPException(
                MagicMock(status=503, reason="Unavailable"), "failed"
            ),
        ]
        with self.assertLogs("con9sole-bartender.drink", level="WARNING"):
            self.assertTrue(await self.cog.do_drink(i))
        self.record.assert_called_once()
        self.touch.assert_called_once()

    async def test_delivery_failure_does_not_charge_or_record(self):
        i = interaction()
        i.edit_original_response.side_effect = [
            discord.HTTPException(
                MagicMock(status=503, reason="Unavailable"), "failed"
            ),
            None,
        ]
        with self.assertLogs("con9sole-bartender.drink", level="ERROR"):
            self.assertFalse(await self.cog.do_drink(i))
        self.touch.assert_not_called()
        self.touch_gift.assert_not_called()
        self.history.assert_not_called()
        self.record.assert_not_called()
        self.assertEqual(list(self.cog.user_recent_draws[i.user.id]), [])

    async def test_read_only_channel_cannot_be_used_to_post(self):
        i = interaction(can_send=False)
        self.assertFalse(await self.cog.do_drink(i))
        i.edit_original_response.assert_not_awaited()
        self.record.assert_not_called()

    async def test_slash_and_picker_both_reject_bot(self):
        target = member(20, bot=True)
        i = interaction()
        self.assertFalse(await self.cog.do_drink(i, target))
        j = interaction()
        await Drink.drink.callback(self.cog, j, target)
        self.record.assert_not_called()
        self.touch_gift.assert_not_called()

    async def test_picker_self_target_is_rejected_without_cooldown(self):
        i = interaction()
        self.assertFalse(await self.cog._gift_from_picker(i, to=i.user))
        self.touch.assert_not_called()
        self.touch_gift.assert_not_called()

    async def test_picker_rechecks_cooldown_at_delivery(self):
        i = interaction()
        await self.cog.gift_drink_entry(i)
        self.gift_cooldown.return_value = 30
        j = interaction()
        self.assertFalse(await self.cog._gift_from_picker(j, to=member(20)))
        self.record.assert_not_called()

    async def test_gift_uses_gift_cooldown_and_only_mentions_recipient(self):
        i = interaction()
        target = member(20, guild=i.guild)
        i.guild.get_member.return_value = target
        self.assertTrue(await self.cog.do_drink(i, target))
        self.touch_gift.assert_called_once()
        self.touch.assert_not_called()
        payload = i.edit_original_response.await_args_list[0].kwargs
        self.assertEqual(payload["content"], "<@20>")
        self.assertEqual(payload["allowed_mentions"].users, [target])
        self.assertFalse(payload["allowed_mentions"].everyone)

    async def test_concurrent_clicks_only_deliver_once(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def pause(**kwargs):
            entered.set()
            await release.wait()

        first = interaction()
        first.edit_original_response.side_effect = pause
        task = asyncio.create_task(self.cog.do_drink(first))
        await entered.wait()
        second = interaction()
        self.assertFalse(await self.cog.do_drink(second))
        release.set()
        self.assertTrue(await task)
        self.record.assert_called_once()

    async def test_cancelled_delivery_releases_guard_without_committing(self):
        i = interaction()
        i.edit_original_response.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.cog.do_drink(i)
        self.touch.assert_not_called()
        self.assertTrue(await self.cog.do_drink(interaction()))


class PickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_only_and_timeout_removes_controls(self):
        view = MemberPicker(owner_id=10, deliver=AsyncMock(), label="請人飲")
        self.assertFalse(await view.interaction_check(interaction(member(99))))
        view.message = MagicMock(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(view.finished)
        self.assertIsNone(view.message.edit.await_args.kwargs["view"])

    async def test_failed_delivery_leaves_selection_available(self):
        deliver = AsyncMock(return_value=False)
        view = MemberPicker(owner_id=10, deliver=deliver, label="請人飲")
        view.selector._values = [member(20)]
        await view.select_member(interaction())
        self.assertFalse(view.finished)
        self.assertFalse(view.busy)

    async def test_successful_selection_cannot_repeat(self):
        deliver = AsyncMock(return_value=True)
        view = MemberPicker(owner_id=10, deliver=deliver, label="請人飲")
        view.selector._values = [member(20)]
        await view.select_member(interaction())
        await view.select_member(interaction())
        deliver.assert_awaited_once()
        self.assertTrue(view.finished)


class CheersTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_rejects_bot(self):
        cog = Cheers(MagicMock())
        i = interaction()
        await Cheers.cheers.callback(cog, i, member(20, bot=True))
        i.edit_original_response.assert_not_awaited()

    async def test_failed_send_does_not_consume_cooldown(self):
        cog = Cheers(MagicMock())
        i = interaction()
        i.edit_original_response.side_effect = discord.HTTPException(
            MagicMock(status=503, reason="fail"), "fail"
        )
        with (
            patch("cogs.cheers.get_cheers_retry_after", return_value=0),
            patch("cogs.cheers.touch_cheers_cooldown") as touch,
        ):
            with self.assertLogs("con9sole-bartender.cheers", level="ERROR"):
                self.assertFalse(await cog.do_cheers(i))
        touch.assert_not_called()
