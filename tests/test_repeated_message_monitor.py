import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from features.repeated_message_monitor import RepeatedMessages
from cogs.repeated_message_monitor import RepeatedMessageMonitor
from features.anti_scam_rules import ALERT_CHANNEL
import config


class DetectorTests(unittest.TestCase):
    def test_threshold_dedup_and_cooldown(self):
        d=RepeatedMessages()
        for i in range(4):self.assertIsNone(d.observe(1,i,'HELLO',i))
        self.assertIsNone(d.observe(1,3,'HELLO',4))
        self.assertEqual(d.observe(1,4,' hello ',4),5)
        self.assertIsNone(d.observe(1,5,'hello',5))

    def test_window_users_and_different_text(self):
        d=RepeatedMessages()
        for i in range(4):d.observe(1,i,'a',i)
        self.assertIsNone(d.observe(2,4,'a',4))
        self.assertIsNone(d.observe(1,5,'b',5))
        self.assertIsNone(d.observe(1,6,'a',20))

    def test_capacity_and_empty(self):
        d=RepeatedMessages();d.capacity=2
        self.assertIsNone(d.observe(1,1,' ',0))
        for i in range(3):d.observe(i,i,'test',i)
        self.assertEqual(len(d.members),2)
        self.assertNotIn(0,d.members)


class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_included_private_alert_no_enforcement(self):
        channel=NS(send=AsyncMock())
        guild=NS(id=config.GUILD_ID,fetch_roles=AsyncMock(return_value=[]),fetch_channel=AsyncMock(return_value=channel))
        cog=RepeatedMessageMonitor(None)
        message=NS(guild=guild,author=NS(id=123,bot=False,roles=[NS(id=config.VERIFIED_ROLE_ID)]),webhook_id=None,
                   channel=NS(id=456),content='same',jump_url='https://discord.com/channels/1/2/3',delete=AsyncMock())
        with patch('cogs.repeated_message_monitor.private_alert') as privacy:
            for i in range(5):
                message.id=i
                await cog.on_message(message)
        privacy.assert_called_once()
        channel.send.assert_awaited_once()
        message.delete.assert_not_awaited()
        self.assertEqual(channel.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'],[])

    async def test_privacy_failure_never_sends(self):
        channel=NS(send=AsyncMock())
        guild=NS(id=config.GUILD_ID,fetch_roles=AsyncMock(return_value=[]),fetch_channel=AsyncMock(return_value=channel))
        cog=RepeatedMessageMonitor(None)
        message=NS(guild=guild,author=NS(id=123,bot=False),webhook_id=None,channel=NS(id=456),content='same')
        with patch('cogs.repeated_message_monitor.private_alert',side_effect=ValueError('public')):
            for i in range(5):
                message.id=i
                await cog.on_message(message)
        channel.send.assert_not_awaited()

    async def test_alert_channel_bots_and_other_guild_ignored(self):
        cog=RepeatedMessageMonitor(None)
        for gid,bot,cid in [(0,False,3),(config.GUILD_ID,True,3),(config.GUILD_ID,False,ALERT_CHANNEL)]:
            await cog.on_message(NS(guild=NS(id=gid),author=NS(bot=bot),webhook_id=None,channel=NS(id=cid)))
        self.assertFalse(cog.detector.members)
