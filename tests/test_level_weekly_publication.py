"""A cancelled weekly send must not be reported as successfully delivered."""
import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
from cogs.community_levels import CommunityLevels
from features.community_levels import Ledger


class WeeklyPublicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cog=CommunityLevels.__new__(CommunityLevels)
        self.cog.ledger=Ledger(Path(self.tmp.name)/'levels.db')
        self.cog.cfg=self.cog.ledger.configure(1,mode='active',announcement_channel=30)
        self.cog.role_lock=asyncio.Lock();self.cog.guard=AsyncMock(return_value=True)
        self.channel=MagicMock(spec=discord.TextChannel)
        self.channel.send=AsyncMock(return_value=types.SimpleNamespace(id=123))
        self.inter=types.SimpleNamespace(guild_id=1,
            guild=types.SimpleNamespace(get_channel=lambda _:self.channel),
            followup=types.SimpleNamespace(send=AsyncMock()))

    def tearDown(self):self.tmp.cleanup()

    async def publish(self):
        await CommunityLevels.winners.callback(self.cog,self.inter,'2026-W45',publish=True)

    def state(self):
        return self.cog.ledger.settings(1)['weekly_publications']['2026-W45']['state']

    async def test_cancelled_send_is_uncertain_and_never_claims_already_sent(self):
        self.channel.send.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await self.publish()
        self.assertEqual(self.state(),'uncertain')
        self.channel.send.reset_mock();self.channel.send.side_effect=None
        await self.publish()
        self.channel.send.assert_not_awaited()
        self.assertNotIn('已發佈過',self.inter.followup.send.call_args.args[0])

    async def test_pending_after_restart_is_uncertain_not_blindly_retried(self):
        self.cog.ledger.begin_weekly_publication(1,'2026-W45')
        self.cog.ledger=Ledger(self.cog.ledger.path)
        await self.publish()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.state(),'uncertain')

    async def test_definite_forbidden_can_retry_then_sent_is_deduplicated(self):
        self.channel.send.side_effect=discord.Forbidden(MagicMock(status=403,reason='denied'),'denied')
        await self.publish();self.assertEqual(self.state(),'failed')
        self.channel.send.side_effect=None
        await self.publish();self.assertEqual(self.state(),'sent')
        self.channel.send.reset_mock()
        await self.publish();self.channel.send.assert_not_awaited()

    async def test_server_failure_is_uncertain_and_stale_ack_cannot_overwrite_new_attempt(self):
        self.channel.send.side_effect=discord.HTTPException(MagicMock(status=500,reason='error'),'error')
        await self.publish();self.assertEqual(self.state(),'uncertain')
        old=self.cog.ledger.begin_weekly_publication(1,'2026-W46')
        self.cog.ledger.finish_weekly_publication(1,'2026-W46',old['attempt'],'failed')
        new=self.cog.ledger.begin_weekly_publication(1,'2026-W46')
        self.cog.ledger.finish_weekly_publication(1,'2026-W46',old['attempt'],'sent',222)
        self.assertNotEqual(old['attempt'],new['attempt'])
        self.assertEqual(self.cog.ledger.settings(1)['weekly_publications']['2026-W46']['state'],'pending')
