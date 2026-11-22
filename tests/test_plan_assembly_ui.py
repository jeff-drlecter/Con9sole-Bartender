"""Offline replay using real Discord components and a persisted plan book."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import config
from cogs.squad_plans import AssemblyView, PlanView, ReminderView, SquadPlans, StartView, card
from features.plan_delivery_ui import Draft
from features.plan_services import AccessError
from features.squad_plans import PlanBook


def button(view, label):
    return next(item for item in view.children if item.label == label)


class AssemblyReplay(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 10000
        self.path = Path(tmp.name) / 'plans.json'
        self.book = PlanBook(self.path, clock=lambda: self.now)
        self.guild = N(id=config.GUILD_ID)
        self.ch = N(id=20, category_id=40)
        self.actor = lambda uid: N(id=uid, roles=[])
        self.room_calls = []

        async def room(interaction, *, before_create):
            before_create()
            self.room_calls.append(interaction.user.id)
            await asyncio.sleep(0)
            return N(id=300)

        self.temp = N(room_for_plan=room)
        self.cards = N(state={'settings': {'routes': {'40': 20}}})
        self.bot = N(user=N(id=9), get_cog={'TempVC': self.temp, 'SquadCards': self.cards}.get)
        self.cog = N(lock=asyncio.Lock(), book=self.book, bot=self.bot, refresh=AsyncMock(return_value=True))
        self.data = dict(game='FC', mode='Clubs', start=11000, party=1, capacity=8)
        p = self.book.create(guild=self.guild.id, channel=self.ch.id, owner=1, assembly_host=True, **self.data)
        self.key = p['id']
        self.book.publish(self.key, 100)
        self.enterContext(patch('cogs.squad_plans.allowed', return_value=True))
        self.source = self.enterContext(patch('features.plan_assembly_ui.source', new=AsyncMock(
            side_effect=lambda cog, guild, uid, plan: (self.actor(uid), self.ch))))

    def plan(self):
        return self.book.get(self.key)

    def interaction(self, uid, message=100, author=9):
        return N(user=self.actor(uid), channel=self.ch, channel_id=self.ch.id,
                 guild=self.guild, guild_id=self.guild.id, message=N(id=message, author=N(id=author)),
                 response=N(defer=AsyncMock(), send_message=AsyncMock()), followup=N(send=AsyncMock()),
                 edit_original_response=AsyncMock())

    def due(self):
        self.now = self.data['start']
        self.book.expire()
        self.assertTrue(self.book.assembly_receipt(self.key, 1, 'due', None, 'sending'))
        self.assertTrue(self.book.assembly_receipt(self.key, 1, 'due', 'sending', 'sent', message=101))

    async def test_only_host_opens_once_both_public_surfaces_link_same_room(self):
        self.due()
        original, notice = PlanView(self.cog, self.plan()), AssemblyView(self.cog, self.plan())
        self.assertTrue(notice.is_persistent())
        self.assertTrue(original.is_persistent())
        for uid, msg, author in [(2, 101, 9), (1, 100, 9), (1, 101, 7)]:
            await button(notice, '🎙️ 確認開局').callback(self.interaction(uid, msg, author))
        self.assertFalse(self.room_calls)
        await asyncio.gather(button(original, '🎙️ 確認開局').callback(self.interaction(1)),
                             button(notice, '🎙️ 確認開局').callback(self.interaction(1, 101)))
        self.assertEqual(self.room_calls, [1])
        for cls in (PlanView, AssemblyView):
            view = cls(self.cog, self.plan())
            self.assertEqual(button(view, '🎧 加入語音').url, f'https://discord.com/channels/{self.guild.id}/300')
            self.assertNotIn('🔔 提醒發起人開局', [b.label for b in view.children])
        self.assertIsNone(self.plan().get('session'))
        self.assertEqual(self.plan()['status'], 'gathering')

    async def test_signups_consent_wait_and_nudge_through_live_buttons(self):
        source = AsyncMock(side_effect=lambda cog, guild, uid, plan: (self.actor(uid), self.ch))
        with patch('features.plan_services.source', new=source):
            original = PlanView(self.cog, self.plan())
            for uid, choice in ((2, '⏰ 我參加，到時提醒我'), (3, '只報名')):
                await button(original, choice).callback(self.interaction(uid))
        self.assertEqual(self.plan()['assembly']['members'], [2])
        self.assertFalse(self.plan()['reminders'])
        self.due()
        view = AssemblyView(self.cog, self.plan())
        wait = button(view, '🙋 我到咗')
        await wait.callback(self.interaction(4, 101))  # unregistered
        await wait.callback(self.interaction(1, 101))  # owner
        self.assertFalse(self.plan()['assembly']['waiting'])
        for uid in (2, 2, 3):
            await wait.callback(self.interaction(uid, 101))
        p = self.plan()
        self.assertEqual(p['assembly']['waiting'], [2, 3])
        self.assertTrue(p['dirty'])  # A failed card edit can be reconciled on the next tick.
        self.assertIn('等候開局 2 人', str(card(p).to_dict()))
        self.assertNotIn('<@', str(card(p).to_dict()))
        self.assertIsNone(p.get('session'))
        nudge = button(view, '🔔 提醒發起人開局')
        self.now += 299
        await nudge.callback(self.interaction(3, 101))
        self.assertFalse(self.plan()['assembly']['nudge'])
        self.now += 1
        await asyncio.gather(*(nudge.callback(self.interaction(uid, 101)) for uid in (3, 2)))
        self.assertEqual(self.plan()['assembly']['nudge']['state'], 'requested')
        self.assertIn(self.plan()['assembly']['nudge']['actor'], (2, 3))
        self.assertFalse(self.room_calls)

    async def test_cancel_reschedule_revoked_source_and_old_private_controls(self):
        self.book.act(self.key, 2, 'join_only', generation=1)
        self.due()
        view = AssemblyView(self.cog, self.plan())
        private = StartView(self.cog, self.key, 1)
        self.source.side_effect = AccessError('denied')
        await button(view, '🙋 我到咗').callback(self.interaction(2, 101))
        await button(view, '🎙️ 確認開局').callback(self.interaction(1, 101))
        self.assertFalse(self.plan()['assembly']['waiting'])
        self.source.side_effect = lambda cog, guild, uid, plan: (self.actor(uid), self.ch)
        self.book.act(self.key, 1, 'edit', changes=dict(self.data, start=self.now + 100))
        self.now += 100
        self.book.expire()
        await button(view, '🎙️ 確認開局').callback(self.interaction(1, 101))
        await private.start.callback(self.interaction(1))
        updated = PlanView(self.cog, self.plan())
        self.book.act(self.key, 1, 'cancel')
        await button(updated, '🎙️ 確認開局').callback(self.interaction(1))
        self.assertFalse(self.room_calls)

    async def test_released_room_cannot_be_recreated_from_either_entry(self):
        self.due()
        original = PlanView(self.cog, self.plan())
        await button(original, '🎙️ 確認開局').callback(self.interaction(1))
        self.book.release_voice(self.key)
        await StartView(self.cog, self.key, 1).start.callback(self.interaction(1))
        await button(original, '🎙️ 確認開局').callback(self.interaction(1))
        self.assertEqual(self.room_calls, [1])
        self.assertIsNone(self.plan().get('voice'))

    async def test_transient_original_edit_is_retried_after_restart(self):
        self.due()
        self.book.link_voice(self.key, 1, 300)
        msg = N(author=self.bot.user, content='', edit=AsyncMock(side_effect=[TimeoutError(), None]))
        self.ch.guild = self.guild
        self.ch.fetch_message = AsyncMock(return_value=msg)
        self.bot.get_channel = lambda channel: None
        self.bot.fetch_channel = AsyncMock(return_value=self.ch)
        self.assertFalse(await SquadPlans.refresh_card(self.cog, self.plan()))
        self.cog.book = self.book = PlanBook(self.path, clock=lambda: self.now)
        self.assertTrue(self.plan()['dirty'])
        self.assertTrue(await SquadPlans.refresh_card(self.cog, self.plan()))
        self.assertFalse(self.plan()['dirty'])
        self.assertTrue(button(msg.edit.await_args.kwargs['view'], '🎧 加入語音').url.endswith('/300'))

    async def test_early_room_keeps_both_registration_routes_across_restart_at_due(self):
        self.book.link_voice(self.key, 1, 300)
        original = PlanView(self.cog, self.plan())
        self.now = self.data['start']
        self.cog.book = self.book = PlanBook(self.path, clock=lambda: self.now)
        restarted = PlanView(self.cog, self.plan())
        before = {c.custom_id for c in original.children if c.custom_id}
        after = {c.custom_id for c in restarted.children if c.custom_id}
        self.assertFalse(before - after)
        self.assertTrue(button(restarted, '到時提醒已截止').disabled)

    async def test_host_preview_and_bound_published_opt_out(self):
        draft = Draft(self.cog, self.ch, self.actor(1), self.data)
        self.assertIn('原頻道 @ 我：開啟', draft.summary())
        self.assertIn(draft.assembly, draft.children)
        with patch('features.plan_services.fresh_source', new=AsyncMock(return_value=(self.actor(1), self.ch))):
            await draft.assembly.callback(self.interaction(1))
        self.assertIs(draft.assembly_host, False)
        self.assertIn('原頻道 @ 我：關閉', draft.summary())
        instant = Draft(self.cog, self.ch, self.actor(1), dict(self.data, instant=True))
        self.assertNotIn(instant.assembly, instant.children)
        pref = ReminderView(self.cog, self.key, self.actor(1))
        toggle = button(pref, '關閉：到時及催開局時 @ 我')
        await toggle.callback(self.interaction(2))
        self.assertTrue(self.plan()['assembly']['host'])
        await toggle.callback(self.interaction(1))
        self.assertFalse(self.plan()['assembly']['host'])
        self.due()
        self.assertNotIn('🔔 提醒發起人開局', [b.label for b in AssemblyView(self.cog, self.plan()).children])

    async def test_restart_restores_scoped_views_and_cache_miss_keeps_room(self):
        self.due()
        self.book.link_voice(self.key, 1, 300)
        self.cog.book = PlanBook(self.path, clock=lambda: self.now)
        self.cog.delivery = MagicMock()
        self.cog.assembly_delivery = N(tick=AsyncMock())
        self.cog.tick = MagicMock()
        self.bot.add_view = MagicMock()
        self.bot.is_ready = lambda: True
        self.bot.get_channel = lambda channel: None
        self.bot.fetch_channel = AsyncMock(return_value=N(id=300))
        await SquadPlans.cog_load(self.cog)
        restored = {call.kwargs.get('message_id'): call.args[0] for call in self.bot.add_view.call_args_list}
        self.assertIsInstance(restored[100], PlanView)
        self.assertIsInstance(restored[101], AssemblyView)
        await SquadPlans.tick.coro(self.cog)
        self.bot.fetch_channel.assert_awaited_once_with(300)
        self.assertEqual(self.cog.book.get(self.key)['voice'], 300)
        self.cog.assembly_delivery.tick.assert_awaited_once()
