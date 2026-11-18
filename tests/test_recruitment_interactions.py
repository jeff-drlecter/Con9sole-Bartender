"""Exercise recruitment callbacks with a contended lock and no Discord I/O."""
import ast
import asyncio
import pathlib
import types
import unittest
from unittest.mock import AsyncMock, Mock

import discord


SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'cogs' / 'squad_cards.py'


class RecruitmentInteractions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = {'ModePicker', 'Details', 'game_profile', 'humans'}
        nodes = [node for node in ast.parse(SOURCE.read_text()).body if
                 isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names or
                 isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id in ('GAME_LABELS', 'MODE_PRESETS')
                     for target in node.targets)]
        self.scope = dict(discord=discord, sync_mode_name=Mock(),
                          is_admin_or_helper=lambda user: user.kind in ('admin', 'helper'),
                          wording_text=lambda user, text: text,
                          wording_modal=lambda user, modal: modal)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.scope)
        self.user = types.SimpleNamespace(kind='player', bot=False)
        self.channel = types.SimpleNamespace(members=[self.user])
        self.session = dict(profile='fc', game='EA SPORTS FC', mode='Clubs 球會', missing=2)
        self.cog = types.SimpleNamespace(
            state={'sessions': {'10': self.session}}, lock=asyncio.Lock(), save=Mock(),
            bot=types.SimpleNamespace(get_channel=lambda key: self.channel), render=AsyncMock())

    def interaction(self):
        return types.SimpleNamespace(
            user=self.user,
            response=types.SimpleNamespace(
                defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()))

    def picker(self, value):
        picker = self.scope['ModePicker'](self.cog, '10', self.session, 'fc')
        picker._values = [value]
        return picker

    def change_context(self, change):
        if change == 'left':
            self.channel.members = []
        elif change == 'removed':
            self.cog.state['sessions'].clear()
        elif change == 'replaced':
            self.cog.state['sessions']['10'] = dict(self.session)
        elif change == 'ended':
            self.session['ended'] = 1234
        elif change == 'profile':
            self.session['profile'] = '2k27'
        elif change == 'channel':
            self.channel = None

    async def run_while_locked(self, callback, interaction, change=None):
        acknowledged = asyncio.Event()
        interaction.response.defer.side_effect = lambda **kwargs: acknowledged.set()
        await self.cog.lock.acquire()
        task = asyncio.create_task(callback(interaction))
        try:
            # The lock stays held until we observe the initial ACK. The original
            # callback times out here because it tries to acquire the lock first.
            await asyncio.wait_for(acknowledged.wait(), timeout=1)
            self.assertFalse(task.done())
            self.cog.save.assert_not_called()
            self.cog.render.assert_not_awaited()
            self.scope['sync_mode_name'].assert_not_called()
            interaction.followup.send.assert_not_awaited()
            self.change_context(change)
        finally:
            self.cog.lock.release()
            await asyncio.wait_for(task, timeout=1)

    async def test_presets_and_skip_acknowledge_before_lock_and_confirm_privately(self):
        for value, expected in [('Clubs Rush', 'Clubs Rush'), ('__none__', '')]:
            with self.subTest(value=value):
                self.setUp()
                interaction = self.interaction()
                await self.run_while_locked(self.picker(value).callback, interaction)
                interaction.response.defer.assert_awaited_once_with(ephemeral=True)
                interaction.response.send_message.assert_not_awaited()
                interaction.response.send_modal.assert_not_awaited()
                interaction.followup.send.assert_awaited_once_with('已更新遊戲模式。', ephemeral=True)
                self.assertEqual(self.session['mode'], expected)
                self.assertEqual(self.session['missing'], 2)
                self.assertTrue(self.session['dirty'])
                self.cog.save.assert_called_once_with()
                self.cog.render.assert_awaited_once_with(self.channel, self.session, manual_refresh=True)
                self.scope['sync_mode_name'].assert_called_once_with(self.cog, self.channel, self.session)

    async def test_preset_rechecks_context_after_waiting_and_uses_followup_errors(self):
        for change in ('left', 'removed', 'replaced', 'ended', 'profile', 'channel'):
            with self.subTest(change=change):
                self.setUp()
                interaction = self.interaction()
                await self.run_while_locked(self.picker('Clubs Rush').callback, interaction, change)
                self.assertEqual(self.session['mode'], 'Clubs 球會')
                self.cog.save.assert_not_called()
                self.cog.render.assert_not_awaited()
                interaction.response.send_message.assert_not_awaited()
                interaction.response.send_modal.assert_not_awaited()
                interaction.followup.send.assert_awaited_once()
                self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
                self.assertNotEqual(interaction.followup.send.call_args.args[0], '已更新遊戲模式。')

    async def test_custom_opens_without_lock_or_mutation_and_rechecks_on_submit(self):
        for change in (None, 'left', 'removed', 'replaced', 'ended', 'channel'):
            with self.subTest(change=change):
                self.setUp()
                interaction = self.interaction()
                async with self.cog.lock:
                    await asyncio.wait_for(self.picker('__custom__').callback(interaction), timeout=1)
                    interaction.response.send_modal.assert_awaited_once()
                    interaction.response.defer.assert_not_awaited()
                    interaction.response.send_message.assert_not_awaited()
                    interaction.followup.send.assert_not_awaited()
                    self.cog.save.assert_not_called()
                    self.cog.render.assert_not_awaited()
                modal = interaction.response.send_modal.call_args.args[0]
                self.assertEqual(modal.game.default, 'EA SPORTS FC')
                self.assertEqual(modal.mode.default, 'Clubs 球會')
                modal.game._value = 'Custom game'
                modal.mode._value = 'Custom mode'
                modal.missing._value = '3'
                submission = self.interaction()
                await self.run_while_locked(modal.on_submit, submission, change)
                submission.response.defer.assert_awaited_once_with(ephemeral=True)
                submission.response.send_message.assert_not_awaited()
                submission.followup.send.assert_awaited_once()
                self.assertTrue(submission.followup.send.call_args.kwargs['ephemeral'])
                self.assertEqual(self.cog.save.call_count, int(change is None))
                self.assertEqual(self.cog.render.await_count, int(change is None))
                self.assertEqual(self.session['mode'], 'Custom mode' if change is None else 'Clubs 球會')
                self.assertEqual(self.session['missing'], 3 if change is None else 2)

    async def test_custom_rejects_invalid_context_without_waiting_for_lock(self):
        for change in ('left', 'removed', 'replaced', 'ended', 'profile', 'channel'):
            with self.subTest(change=change):
                self.setUp()
                picker = self.picker('__custom__')
                self.change_context(change)
                interaction = self.interaction()
                async with self.cog.lock:
                    await asyncio.wait_for(picker.callback(interaction), timeout=1)
                interaction.response.send_message.assert_awaited_once()
                self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
                interaction.response.send_modal.assert_not_awaited()
                interaction.response.defer.assert_not_awaited()
                interaction.followup.send.assert_not_awaited()
                self.cog.save.assert_not_called()
                self.cog.render.assert_not_awaited()
