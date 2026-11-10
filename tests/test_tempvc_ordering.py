from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.tempvc import _order_temp_channels, _try_order_temp_channels


def voice(cid, name, position, category=10):
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id, channel.name = cid, name
    channel.position, channel.category_id = position, category
    return channel


class TempVCOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def order(self, channels, tracked):
        guild = MagicMock()
        guild.id = 123
        guild.fetch_channels = AsyncMock(return_value=channels)
        guild._state.http.bulk_channel_update = AsyncMock()
        with patch('cogs.tempvc.is_temp_vc_id', side_effect=lambda cid: cid in tracked), \
             patch('cogs.tempvc.get_hub_channel_name', return_value='開一個小隊 call'), \
             patch('cogs.tempvc.get_temp_channel_base_name', return_value='小隊call •'):
            await _order_temp_channels(guild, 10)
        return guild._state.http.bulk_channel_update

    async def test_numeric_order_before_hub_preserves_other_channels(self):
        channels = [voice(1, 'music', 1), voice(2, '開一個小隊 call', 2),
                    voice(3, '小隊call • 10', 3), voice(4, '小隊call • 2', 4),
                    voice(5, '小隊call • 1', 5), voice(6, 'other', 6),
                    voice(7, '小隊call • 1', 7, category=20)]
        update = await self.order(channels, {3, 4, 5, 7})
        self.assertEqual(update.await_args.args[1], [
            {'id': cid, 'position': pos}
            for cid, pos in zip([1, 6, 5, 4, 3, 2], range(1, 7))])

    async def test_gap_filling_room_goes_between_one_and_three(self):
        update = await self.order([voice(1, '小隊call • 1', 1),
            voice(3, '小隊call • 3', 2), voice(4, '開一個小隊 call', 3),
            voice(2, '小隊call • 2', 4)], {1, 2, 3})
        self.assertEqual([x['id'] for x in update.await_args.args[1]], [1, 2, 3, 4])

    async def test_correct_order_is_noop(self):
        update = await self.order([voice(1, '小隊call • 1', 1),
                                  voice(2, '開一個小隊 call', 2)], {1})
        update.assert_not_awaited()

    async def test_no_hub_is_noop(self):
        update = await self.order([voice(1, '小隊call • 1', 1)], {1})
        update.assert_not_awaited()

    async def test_untracked_similar_name_is_not_moved(self):
        update = await self.order([voice(1, '小隊call • 1', 1),
            voice(2, '開一個小隊 call', 2), voice(3, '小隊call • 2', 3)], {1})
        self.assertEqual([x["id"] for x in update.await_args.args[1]], [3, 1, 2])

    async def test_renamed_rooms_keep_numeric_order(self):
        update = await self.order([voice(1, "開一個小隊 call", 1),
            voice(2, "小隊call • 10 · Park", 2),
            voice(3, "小隊call • 2 · REC", 3)], {2, 3})
        self.assertEqual([x["id"] for x in update.await_args.args[1]], [3, 2, 1])

    async def test_permission_failure_does_not_break_creation(self):
        response = MagicMock(status=403, reason='Forbidden')
        with patch('cogs.tempvc._order_temp_channels',
                   side_effect=discord.Forbidden(response, 'missing permissions')):
            await _try_order_temp_channels(MagicMock(id=123), 10)
