import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs.tempvc import TempVC
from cogs.squad_cards import sync_mode_name


class ModeNameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cog = TempVC(MagicMock())
        self.channel = MagicMock(spec=discord.VoiceChannel)
        self.channel.id = 42
        self.channel.name = '小隊call • 1'
        self.channel.guild.get_channel.return_value = self.channel
        self.channel.edit = AsyncMock(return_value=self.channel)
        self.tracked = patch('cogs.tempvc.is_temp_vc_id', return_value=True)
        self.tracked.start()

    async def asyncTearDown(self):
        await self.cog.cog_unload()
        self.tracked.stop()

    async def drain(self):
        # The real one-second debounce is exercised, including task cleanup.
        await asyncio.gather(*self.cog._mode_tasks.values())

    async def test_latest_selection_wins_and_clear_restores_number(self):
        self.cog.queue_mode_name(self.channel, 'Park')
        self.cog.queue_mode_name(self.channel, 'REC')
        self.assertEqual(len(self.cog._mode_tasks), 1)
        await self.drain()
        self.channel.edit.assert_awaited_once_with(name='小隊call • 1 · REC', reason='Sync small-team call game mode')
        self.channel.name = '小隊call • 1 · REC'
        self.channel.edit.reset_mock()
        self.cog.queue_mode_name(self.channel, '')
        await self.drain()
        self.assertEqual(self.channel.edit.await_args.kwargs['name'], '小隊call • 1')

    async def test_custom_room_and_untracked_room_are_preserved(self):
        self.channel.name = 'Friends room'
        self.cog.queue_mode_name(self.channel, 'REC')
        self.assertFalse(self.cog._mode_tasks)
        self.channel.name = '小隊call • 1'
        with patch('cogs.tempvc.is_temp_vc_id', return_value=False):
            self.cog.queue_mode_name(self.channel, 'REC')
        self.assertFalse(self.cog._mode_tasks)

    async def test_deleted_room_and_noop_do_not_edit(self):
        self.channel.guild.get_channel.return_value = None
        self.cog.queue_mode_name(self.channel, 'REC')
        await self.drain()
        self.channel.edit.assert_not_awaited()
        self.channel.guild.get_channel.return_value = self.channel
        self.cog.queue_mode_name(self.channel, '')
        await self.drain()
        self.channel.edit.assert_not_awaited()

    async def test_unload_cancels_pending_rename(self):
        self.cog.queue_mode_name(self.channel, 'REC')
        tasks = list(self.cog._mode_tasks.values())
        await self.cog.cog_unload()
        self.assertTrue(all(t.cancelled() for t in tasks))
        self.channel.edit.assert_not_awaited()

    async def test_squad_bridge_queues_mode(self):
        cog = MagicMock()
        cog.bot.get_cog.return_value = self.cog
        sync_mode_name(cog, self.channel, {'mode': 'REC'})
        await self.drain()
        self.assertEqual(self.channel.edit.await_args.kwargs['name'], '小隊call • 1 · REC')
