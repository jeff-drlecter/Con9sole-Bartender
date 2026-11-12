import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
import config
from cogs.stream_alerts import STREAM_SANDBOX_CHANNEL, StreamDemoSession


class StreamDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_repeat_and_offline_use_two_original_cards_without_pings(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = STREAM_SANDBOX_CHANNEL
        channel.guild = SimpleNamespace(id=config.GUILD_ID, get_role=lambda _: SimpleNamespace(mention='ROLE'))
        channel.send = AsyncMock(side_effect=[SimpleNamespace(id=101), SimpleNamespace(id=102)])
        messages = {mid: SimpleNamespace(edit=AsyncMock()) for mid in (101, 102)}
        channel.fetch_message = AsyncMock(side_effect=lambda mid: messages[mid])
        bot = SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == channel.id else None)
        demo = StreamDemoSession(bot, channel, 42)
        self.assertEqual(await demo.check(), ['live', 'live'])
        self.assertEqual(await demo.check(), ['unchanged', 'unchanged'])
        self.assertEqual(channel.send.await_count, 2)
        for call in channel.send.await_args_list:
            self.assertEqual(call.kwargs['content'], '')
            self.assertEqual(call.kwargs['allowed_mentions'].to_dict()['parse'], [])
            self.assertTrue(call.kwargs['silent'])
            self.assertIn('沙盤模擬', call.kwargs['embed'].title)
            self.assertFalse(call.kwargs['embed'].image.url)
        self.assertEqual(await demo.check(close=True), ['offline', 'offline'])
        self.assertEqual(await demo.check(), ['unchanged', 'unchanged'])
        self.assertEqual(channel.send.await_count, 2)
        self.assertEqual(demo.sent_ids, [101, 102])
        for message in messages.values():
            message.edit.assert_awaited_once()
            self.assertIn('直播已結束', message.edit.await_args.kwargs['embed'].title)
        self.assertIn('直播卡 2 張', demo.summary())

    async def test_demo_rejects_real_notification_channels(self):
        with self.assertRaises(ValueError):
            StreamDemoSession(None, SimpleNamespace(id=1299646760582381680, guild=SimpleNamespace(id=config.GUILD_ID)), 42)

    async def test_demo_stores_are_independent(self):
        channel = SimpleNamespace(id=STREAM_SANDBOX_CHANNEL, guild=SimpleNamespace(id=config.GUILD_ID))
        one, two = StreamDemoSession(None, channel, 1), StreamDemoSession(None, channel, 2)
        one.store.state['entries']['jeff_con9sole']['enabled'] = False
        self.assertTrue(two.store.state['entries']['jeff_con9sole']['enabled'])
        self.assertFalse(one.store.state['member_ping'])
        self.assertNotEqual(one.streams['jeff_con9sole']['id'], two.streams['jeff_con9sole']['id'])
