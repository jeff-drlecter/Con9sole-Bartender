"""Synthetic room ownership, persistent naming and real recruitment callback tests."""
import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord

from cogs.squad_cards import RecruitmentChoices, SquadCards, sync_mode_name
from cogs.tempvc import TempVC
from core.action_guard import shared_async_lock
from features import tempvc_storage


class _RoomFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in [('features.tempvc_storage.STATS_DB', Path(self.temp.name) / 'stats.sqlite3'),
                              ('config.GUILD_ID', 1), ('cogs.tempvc.MODE_NAME_DEBOUNCE_SECONDS', 0),
                              ('cogs.tempvc.VC_LIMIT_CHANNEL_COOLDOWNS', {})]:
            self.enterContext(patch(target, value))
        self.enterContext(patch('cogs.tempvc.get_vc_limit_channel_cooldown_seconds', return_value=0))
        self.enterContext(patch('cogs.tempvc.is_temp_vc_id', return_value=True))
        self.enterContext(patch('utils.is_temp_vc_id', return_value=True))
        tempvc_storage.init_tempvc_db()
        tempvc_storage.remember(42, 1, 5)
        self.channel = MagicMock(spec=discord.VoiceChannel)
        self.channel.id, self.channel.name = 42, '原有完整房名'
        self.channel.guild.id = 1
        self.channel.guild.voice_channels = [self.channel]
        self.channel.guild.get_channel.return_value = self.channel
        self.channel.guild.fetch_channel = AsyncMock(return_value=self.channel)
        async def edit(**kwargs):
            self.channel.name = kwargs['name']
            return self.channel
        self.channel.edit = AsyncMock(side_effect=edit)
        self.bot = MagicMock()
        self.bot.guilds = [self.channel.guild]
        self.bot.wait_until_ready = AsyncMock()
        self.cog = TempVC(self.bot)

    async def asyncTearDown(self):
        await self.cog.cog_unload()

    async def drain(self):
        await asyncio.wait_for(asyncio.gather(*self.cog._mode_tasks.values()), timeout=2)

    async def select(self, name, *, source='session:s', owner=5):
        return await self.cog.set_community_name(self.channel, name, owner_id=owner, source=source)


class CommunityRoomTests(_RoomFixture):
    async def test_full_name_replacement_modes_and_clear_preserve_original(self):
        self.assertTrue(await self.select('一個完整公會名稱'))
        self.cog.queue_mode_name(self.channel, 'REC')
        await self.drain()
        self.assertEqual(self.channel.name, '一個完整公會名稱')
        self.assertTrue(await self.select('第二個公會'))
        await self.drain()
        self.cog.queue_mode_name(self.channel, 'Park')
        self.assertFalse(self.cog._mode_tasks)
        self.assertTrue(await self.select(None))
        await self.drain()
        self.assertEqual(self.channel.name, '原有完整房名')
        self.assertEqual(tempvc_storage.community_names(1), {})

    async def test_source_handover_and_stale_clear_cannot_replace_new_round(self):
        await self.select('第一個公會')
        await self.select('下一局公會', source='plan:next')
        self.assertTrue(await self.select(None))
        await self.drain()
        self.assertEqual(self.channel.name, '下一局公會')
        self.assertEqual(tempvc_storage.community_names(1)[42]['source'], 'plan:next')
        await self.select(None, source='plan:next')
        await self.drain()
        self.assertEqual(self.channel.name, '原有完整房名')

    async def test_pending_mode_cannot_overwrite_selected_community(self):
        self.channel.name = '小隊call • 1'
        self.cog.queue_mode_name(self.channel, 'REC')
        await self.select('完整公會名')
        await self.drain()
        self.assertEqual(self.channel.name, '完整公會名')
        self.assertEqual(self.channel.edit.await_count, 1)

    async def test_current_owner_tracking_guild_and_pending_owner_change(self):
        self.assertFalse(await self.select('不能改', owner=6))
        with patch('cogs.tempvc.is_temp_vc_id', return_value=False):
            self.assertFalse(await self.select('不能改'))
        self.channel.guild.id = 2
        self.assertFalse(await self.select('不能改'))
        self.channel.guild.id = 1
        await self.select('稍後不能改')
        tempvc_storage.remember(42, 1, 6)
        await self.drain()
        self.channel.edit.assert_not_awaited()

    async def test_busy_worker_does_not_wait_with_stale_caller_authorization(self):
        async with shared_async_lock('tempvc-name', 42):
            self.assertFalse(await asyncio.wait_for(self.select('不能排隊'), timeout=0.1))
        self.assertEqual(tempvc_storage.community_names(1), {})

    async def test_restart_resumes_intent_and_clear(self):
        await self.select('重啟後公會名稱')
        await self.cog.cog_unload()
        self.cog = TempVC(self.bot)
        with patch('cogs.tempvc.bootstrap_track_temp_vcs', AsyncMock(return_value=[42])), \
                patch('cogs.tempvc.schedule_delete_if_empty', AsyncMock()), \
                patch('cogs.tempvc.get_sweep_interval_seconds', return_value=0):
            await self.cog.cog_load()
            await self.cog._startup_task
            await self.drain()
        self.assertEqual(self.channel.name, '重啟後公會名稱')
        await self.select(None)
        await self.drain()
        self.assertEqual(self.channel.name, '原有完整房名')

    async def test_http_failure_retries_latest_intent_without_new_room(self):
        response = types.SimpleNamespace(status=503, reason='synthetic')
        original = self.channel.edit.side_effect
        async def edit(**kwargs):
            self.channel.edit.side_effect = original
            raise discord.HTTPException(response, 'synthetic')
        self.channel.edit.side_effect = edit
        await self.select('重試公會')
        await self.drain()
        self.assertEqual(self.channel.name, '重試公會')
        self.assertEqual(self.channel.edit.await_count, 2)

    async def test_reserved_hub_name_is_disambiguated(self):
        with patch('cogs.tempvc.get_hub_channel_name', return_value='開房入口'):
            await self.select('開房入口')
            await self.drain()
        self.assertEqual(self.channel.name, '公會 · 開房入口')

    async def test_forget_removes_naming_state_and_unselected_mode_uses_no_db(self):
        await self.select('公會')
        await self.drain()
        tempvc_storage.forget(42)
        self.assertEqual(tempvc_storage.community_names(1), {})
        self.cog._community_names.clear()
        self.channel.name = '小隊call • 1'
        with patch('features.tempvc_storage.creator_id', side_effect=AssertionError('unexpected DB lookup')):
            self.cog.queue_mode_name(self.channel, 'REC')
            await self.drain()
        self.assertEqual(self.channel.name, 'REC • 1')


class RecruitmentCommunityTests(_RoomFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.member = MagicMock(spec=discord.Member)
        self.member.id, self.member.bot = 5, False
        self.member.voice.channel = self.channel
        self.channel.members = [self.member]
        self.channel.permissions_for.return_value = types.SimpleNamespace(view_channel=True, connect=True)
        self.channel.guild.fetch_member = AsyncMock(return_value=self.member)
        self.channel.category = None
        self.directory = types.SimpleNamespace(directory=types.SimpleNamespace(get=Mock(return_value={
            'key': 'team', 'name': '合成公會', 'game': '其他遊戲', 'archived': False,
            'pic_id': 99, 'notes': '不可在召集卡顯示', 'status': 'open'})))
        self.bot.get_cog.side_effect = lambda name: {'TempVC': self.cog, 'CommunityDirectory': self.directory}.get(name)
        self.bot.get_channel.side_effect = lambda cid: self.channel if cid == 42 else self.destination
        self.destination = MagicMock(spec=discord.TextChannel)
        self.destination.id, self.destination.guild = 30, self.channel.guild
        self.destination.permissions_for.return_value = types.SimpleNamespace(view_channel=True, read_message_history=True)
        self.destination.fetch_message = AsyncMock(return_value=types.SimpleNamespace(id=99, author=self.bot.user))
        self.channel.guild.fetch_channel.side_effect = lambda cid: self.channel if cid == 42 else self.destination
        self.session = dict(id='s', started=1, game='', mode='', destination=30, message=99, participants={})
        self.squad = SquadCards.__new__(SquadCards)
        self.squad.bot, self.squad.state, self.squad.lock = self.bot, {'sessions': {'42': self.session}}, asyncio.Lock()
        self.squad.save, self.squad.render = Mock(), AsyncMock()
        self.squad.notify_interested = AsyncMock()
        self.enterContext(patch('cogs.tempvc.user_can_admin_teardown', return_value=False))

    def interaction(self):
        return types.SimpleNamespace(guild_id=1, channel_id=30, guild=self.channel.guild, user=self.member,
            response=types.SimpleNamespace(is_done=lambda: False, defer=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def callback(self):
        interaction = self.interaction()
        with patch('features.squad_community.choose_community', AsyncMock()) as chooser:
            choices = RecruitmentChoices(self.squad, '42', self.session)
            button = next(child for child in choices.children if getattr(child, 'label', None) == '公會（選填／清除）')
            await button.callback(interaction)
            chooser.assert_awaited_once()
            interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
            return chooser.call_args.args[2]

    async def test_normal_entry_select_replace_clear_and_mode_bridge(self):
        callback = await self.callback()
        await callback(self.interaction(), 'team')
        self.assertEqual(self.session['community_key'], 'team')
        self.assertEqual(self.session['community_owner'], 5)
        self.squad.render.assert_awaited_once()
        sync_mode_name(self.squad, self.channel, dict(self.session, mode='REC'))
        await self.drain()
        self.assertEqual(self.channel.name, '合成公會')
        callback = await self.callback()
        await callback(self.interaction(), None)
        await self.drain()
        self.assertIsNone(self.session['community_key'])
        self.assertEqual(self.channel.name, '原有完整房名')

    async def test_selection_rechecks_old_session_source_room_owner_and_archived(self):
        callback = await self.callback()
        for change in ('session', 'ended', 'channel', 'room', 'owner', 'plan', 'archived'):
            with self.subTest(change=change):
                self.squad.state['sessions']['42'] = self.session
                self.session.pop('ended', None)
                self.session.pop('plan_id', None)
                self.member.voice.channel = self.channel
                tempvc_storage.remember(42, 1, 5)
                self.directory.directory.get.return_value['archived'] = False
                i = self.interaction()
                if change == 'session': self.squad.state['sessions']['42'] = dict(self.session)
                if change == 'ended': self.session['ended'] = 10
                if change == 'channel': i.channel_id = 31
                if change == 'room': self.member.voice.channel = types.SimpleNamespace(id=43)
                if change == 'owner': tempvc_storage.remember(42, 1, 6)
                if change == 'plan': self.session['plan_id'] = 'plan'
                if change == 'archived': self.directory.directory.get.return_value['archived'] = True
                await callback(i, 'team')
                i.followup.send.assert_awaited_once()
                self.assertNotIn('community_key', self.session)
                self.squad.save.assert_not_called()
                self.assertEqual(tempvc_storage.community_names(1), {})

    async def test_public_card_only_name_private_button_and_no_footprint_metadata(self):
        callback = await self.callback()
        await callback(self.interaction(), 'team')
        await self.drain()
        message = types.SimpleNamespace(id=99, author=self.bot.user, content='', edit=AsyncMock())
        self.destination.fetch_message.return_value = message
        with patch('cogs.squad_cards.interest_topic', return_value=None), \
                patch('cogs.squad_cards.run_stats', AsyncMock(return_value=None)):
            await SquadCards.render(self.squad, self.channel, self.session)
            kwargs = message.edit.call_args.kwargs
            self.assertEqual([(f.name, f.value) for f in kwargs['embed'].fields], [('公會', '合成公會')])
            self.assertIn('squad-community:s', [c.custom_id for c in kwargs['view'].children])
            self.assertEqual(kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
            self.squad.finish_footprint = AsyncMock()
            self.session['ended'] = 100
            await SquadCards.render(self.squad, self.channel, self.session, ended=True)
            args = self.squad.finish_footprint.call_args.args
            self.assertNotIn('公會', [f.name for f in args[3].fields])
            self.assertNotIn('squad-community:s', [c.custom_id for c in args[4].children])
        await self.drain()
        self.assertEqual(self.channel.name, '原有完整房名')

    async def test_older_picker_cannot_undo_new_selection_or_updated_public_source(self):
        old = await self.callback()
        current = await self.callback()
        await current(self.interaction(), 'team')
        await old(self.interaction(), None)
        self.assertEqual(self.session['community_key'], 'team')
        newer = await self.callback()
        self.session['message'] = 100
        await newer(self.interaction(), None)
        self.assertEqual(self.session['community_key'], 'team')
        await self.drain()

    async def test_missing_or_inaccessible_source_never_changes_room(self):
        callback = await self.callback()
        self.destination.fetch_message.side_effect = discord.NotFound(types.SimpleNamespace(status=404, reason='synthetic'), 'gone')
        await callback(self.interaction(), 'team')
        self.destination.fetch_message.side_effect = None
        self.destination.permissions_for.return_value.view_channel = False
        await callback(self.interaction(), 'team')
        self.squad.save.assert_not_called()
        self.assertEqual(tempvc_storage.community_names(1), {})

    async def test_persist_before_queue_failure_and_retry_without_unauthorized_rename(self):
        callback = await self.callback()
        self.squad.save.side_effect = OSError('synthetic')
        with patch.object(self.cog, 'set_community_name', AsyncMock()) as rename:
            await callback(self.interaction(), 'team')
            rename.assert_not_awaited()
        self.assertNotIn('community_key', self.session)
        self.squad.save.side_effect = None
        with patch.object(self.cog, 'set_community_name', AsyncMock(return_value=False)):
            await callback(self.interaction(), 'team')
        self.assertEqual(self.session['community_key'], 'team')
        self.assertTrue(self.session['dirty'])
        self.assertEqual(tempvc_storage.community_names(1), {})
        self.assertTrue(await self.squad.sync_community_room(self.channel, self.session))
        await self.drain()
        self.assertEqual(self.channel.name, '合成公會')

    async def test_unreadable_directory_keeps_existing_name_and_intent(self):
        from features.community_directory import DirectoryUnavailable
        callback = await self.callback()
        await callback(self.interaction(), 'team')
        await self.drain()
        self.directory.directory.get.side_effect = DirectoryUnavailable()
        with self.assertRaises(DirectoryUnavailable):
            await self.squad.sync_community_room(self.channel, self.session)
        self.assertEqual(self.channel.name, '合成公會')
        self.assertEqual(tempvc_storage.community_names(1)[42]['community_name'], '合成公會')

    async def test_room_controller_uses_real_owner_and_rechecks_revoked_control(self):
        self.member.id = 6
        with patch('cogs.tempvc.user_can_admin_teardown', return_value=True):
            callback = await self.callback()
            await callback(self.interaction(), 'team')
        self.assertEqual(self.session['community_owner'], 5)
        with patch('cogs.tempvc.user_can_admin_teardown', return_value=True):
            stale = await self.callback()
        await stale(self.interaction(), None)
        self.assertEqual(self.session['community_key'], 'team')
        await self.drain()

    async def test_new_plan_binding_rejects_picker_before_session_render(self):
        from features.squad_plans import PlanBook
        callback = await self.callback()
        book = PlanBook(Path(self.temp.name) / 'plans.json', clock=lambda: 1000)
        plan = book.create(guild=1, channel=30, owner=5, game='合成遊戲', mode='', start=1100, party=1, capacity=3)
        book.publish(plan['id'], 99)
        book.link_voice(plan['id'], 5, 42)
        previous = self.bot.get_cog.side_effect
        self.bot.get_cog.side_effect = lambda name: types.SimpleNamespace(book=book) if name == 'SquadPlans' else previous(name)
        await callback(self.interaction(), 'team')
        self.squad.save.assert_not_called()
        self.assertNotIn('community_key', self.session)
        self.assertEqual(tempvc_storage.community_names(1), {})
