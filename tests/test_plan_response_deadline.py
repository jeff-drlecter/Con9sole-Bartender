"""Real View callbacks acknowledge before slow authorization; no live Discord IO."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch

import config
from features.plan_delivery_ui import Draft, Numbers, Settings
from features.plan_services import AccessError
from features.squad_plans import PlanBook


class ResponseDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner = N(id=1)
        self.guild = N(id=config.GUILD_ID)
        self.channel = N(id=20, category=None)
        self.cog = N(book=PlanBook(Path(self.tmp.name) / 'plans.json', clock=lambda:10000),
                     lock=asyncio.Lock(), refresh=AsyncMock())
        self.data = dict(game='Cross-game', mode='PC', party=1, capacity=3, start=11000)

    def interaction(self, user=None):
        response = N(done=False, send_message=AsyncMock(), send_modal=AsyncMock(), edit_message=AsyncMock())
        async def defer(**kwargs):
            self.assertFalse(response.done)
            response.done = True
        response.defer = AsyncMock(side_effect=defer)
        response.is_done = lambda:response.done
        return N(user=user or self.owner, guild=self.guild, guild_id=self.guild.id,
                 channel_id=20, channel=self.channel, response=response,
                 followup=N(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_cancel_owner_draft_even_when_rest_unavailable(self):
        view = Draft(self.cog, self.channel, self.owner, self.data)
        i = self.interaction()
        with patch('features.plan_services.fresh_source', new=AsyncMock(side_effect=OSError)) as read:
            self.assertTrue(await view.interaction_check(i))  # discord.py dispatch
            await view.cancel.callback(i)
            read.assert_not_awaited()
        self.assertTrue(view.used)
        self.assertEqual(i.response.edit_message.await_args.kwargs['content'], '草稿已取消。')
        self.assertFalse(self.cog.book.all())

    async def test_wrong_user_or_guild_cannot_cancel_or_open_draft_form(self):
        for action in ('cancel', 'numbers', 'publish'):
            for wrong_guild in (False, True):
                view = Draft(self.cog, self.channel, self.owner, self.data)
                i = self.interaction(self.owner if wrong_guild else N(id=2))
                if wrong_guild:
                    i.guild = N(id=999)
                await getattr(view, action).callback(i)
                self.assertFalse(view.used)
                i.response.send_message.assert_awaited_once()
                i.response.send_modal.assert_not_awaited()

    async def test_toggle_acknowledges_before_single_fresh_read(self):
        for action in ('auto', 'notice'):
            view = Draft(self.cog, self.channel, self.owner, self.data)
            i = self.interaction()
            async def read(*args):
                self.assertTrue(i.response.done)
                await asyncio.sleep(0)  # REST can yield without losing initial response.
                return self.owner, self.channel
            with patch('features.plan_services.fresh_source', new=AsyncMock(side_effect=read)) as access:
                self.assertTrue(await view.interaction_check(i))
                await getattr(view, action).callback(i)
                access.assert_awaited_once()
            i.edit_original_response.assert_awaited_once()

    async def test_cancel_while_authorizing_does_not_restore_preview(self):
        view = Draft(self.cog, self.channel, self.owner, self.data)
        toggle, cancel = self.interaction(), self.interaction()
        started, release = asyncio.Event(), asyncio.Event()
        async def read(*args):
            started.set()
            await release.wait()
            return self.owner, self.channel
        with patch('features.plan_services.fresh_source', new=read):
            task = asyncio.create_task(view.notice.callback(toggle))
            await started.wait()
            await view.cancel.callback(cancel)
            release.set()
            await task
        toggle.edit_original_response.assert_not_awaited()
        self.assertTrue(view.settings['host_notices'])
        self.assertTrue(view.used)

    async def test_number_form_opens_without_rest_but_submit_rechecks_revocation(self):
        view = Draft(self.cog, self.channel, self.owner, self.data)
        i = self.interaction()
        with patch('features.plan_services.fresh_source', new=AsyncMock(side_effect=AccessError('denied'))) as read:
            self.assertTrue(await view.interaction_check(i))
            await view.numbers.callback(i)
            read.assert_not_awaited()
            modal = i.response.send_modal.await_args.args[0]
            self.assertIsInstance(modal, Numbers)
            submit = self.interaction()
            await modal.on_submit(submit)
            self.assertTrue(submit.response.done)
            read.assert_awaited_once()
            submit.edit_original_response.assert_not_awaited()
            self.assertEqual(view.data, self.data)
            submit.followup.send.assert_awaited_once()

    async def test_plan_form_defers_before_permission_denial_and_never_posts(self):
        from cogs.squad_plans import PlanForm
        for confirmed in (False, True):
            i = self.interaction()
            async def read(*args):
                self.assertTrue(i.response.done)
                raise AccessError('denied')
            with patch('features.plan_services.fresh_source', new=read):
                await PlanForm(self.cog, self.channel, confirmed=confirmed).on_submit(i)
            self.assertFalse(self.cog.book.all())
            i.edit_original_response.assert_awaited_once()

    async def test_changing_numbers_preserves_event_and_notice_choices(self):
        for auto in (False, True):
            for notices in (False, True):
                view = Draft(self.cog, self.channel, self.owner, self.data)
                view.settings.update(auto_event=auto, host_notices=notices)
                form = Numbers(view, self.owner)
                form.minimum._value, form.capacity._value = '2', '4'
                with patch('features.plan_services.fresh_source', new=AsyncMock(return_value=(self.owner, self.channel))):
                    await form.on_submit(self.interaction())
                self.assertEqual(view.settings['auto_event'], auto)
                self.assertEqual(view.settings['host_notices'], notices)
                self.assertEqual((view.settings['minimum'], view.data['capacity']), (2, 4))

    async def test_blank_threshold_disables_event_and_new_number_does_not_opt_in(self):
        view = Draft(self.cog, self.channel, self.owner, self.data)
        with patch('features.plan_services.fresh_source', new=AsyncMock(return_value=(self.owner, self.channel))):
            for value in ('', '2'):
                form = Numbers(view, self.owner)
                form.minimum._value = value
                await form.on_submit(self.interaction())
                self.assertFalse(view.settings['auto_event'])
        self.assertFalse(view.auto.disabled)  # The owner can explicitly turn it on.

    async def test_published_settings_acknowledge_before_source_and_keep_cas(self):
        p = self.cog.book.create(guild=self.guild.id, channel=20, owner=1, **self.data)
        self.cog.book.publish(p['id'], 99)
        view = Settings(self.cog, self.cog.book.get(p['id']), self.owner)
        i = self.interaction()
        async def read(*args):
            self.assertTrue(i.response.done)
            # Another operation won the revision while this REST call was pending.
            self.cog.book.act(p['id'], 2, 'join')
            return self.owner, self.channel
        with patch('features.plan_services.source', new=read), patch('cogs.squad_plans.allowed', return_value=True):
            self.assertTrue(await view.interaction_check(i))
            await view.notice.callback(i)
        self.assertNotIn('delivery', self.cog.book.get(p['id']))
        self.cog.refresh.assert_not_awaited()
        self.assertIn('設定未更新', i.edit_original_response.await_args.kwargs['content'])
