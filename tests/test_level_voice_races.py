"""Independent voice timer interleaving regressions; no Discord connection."""
import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cogs.community_levels as levels
from features.community_levels import Ledger


class VoiceRaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.guild_patch = patch.object(levels.config, 'GUILD_ID', 1)
        self.guild_patch.start()
        self.bot = MagicMock()
        self.bot.is_ready.return_value = True
        self.cog = levels.CommunityLevels(self.bot)
        self.cog.ledger = Ledger(Path(self.tmp.name) / 'voice.sqlite3')
        self.cog.cfg = self.cog.ledger.configure(1, mode='preview')
        self.cog.gateway_confirmed = True
        self.guild = types.SimpleNamespace(id=1, afk_channel=None,
            voice_channels=[], stage_channels=[])
        self.channel = self.make_channel(30)
        self.guild.voice_channels = [self.channel]
        self.a, self.b = self.make_member(10), self.make_member(11)
        self.channel.members = [self.a, self.b]
        self.bot.get_guild.return_value = self.guild
        self.cog.voice_clock = {(30, 10): 0, (30, 11): 0}

    async def asyncTearDown(self):
        self.guild_patch.stop()
        self.tmp.cleanup()

    def make_channel(self, uid):
        return types.SimpleNamespace(id=uid, guild=self.guild, members=[],
            parent_id=None, category_id=None)

    def make_member(self, uid, channel=None):
        channel = channel or self.channel
        voice = types.SimpleNamespace(channel=channel, self_deaf=False,
            deaf=False, afk=False, suppress=False, self_mute=False, mute=False)
        return types.SimpleNamespace(id=uid, guild=self.guild, bot=False,
            roles=[], voice=voice, premium_since=None)

    def voice_xp(self, uid):
        return self.cog.ledger.profile(1, uid)['voice']

    async def run_interleaving(self, transition):
        original = self.cog.credit
        triggered = False
        async def wrapped(member, channel, source, event, now=None):
            nonlocal triggered
            result = await original(member, channel, source, event, now)
            if not triggered:
                triggered = True
                await transition()
            return result
        self.cog.credit = wrapped
        with patch.object(levels.time, 'monotonic', return_value=1000):
            await levels.CommunityLevels.voice_tick.coro(self.cog)
        self.assertTrue(triggered)
        self.cog.credit = original

    async def test_peer_leaves_during_first_award_no_invalid_second_or_resurrection(self):
        async def leave():
            before = self.b.voice
            self.channel.members.remove(self.b)
            self.b.voice = None
            await self.cog.on_voice_state_update(self.b, before,
                types.SimpleNamespace(channel=None))
        await self.run_interleaving(leave)
        self.assertEqual(self.voice_xp(10), 25)
        self.assertEqual(self.voice_xp(11), 0)
        self.assertEqual(self.cog.voice_clock, {})
        # A subsequent healthy interval is still processed; the loop has not died.
        self.b = self.make_member(11)
        self.channel.members.append(self.b)
        with patch.object(levels.time, 'monotonic', return_value=1100):
            await levels.CommunityLevels.voice_tick.coro(self.cog)
        with patch.object(levels.time, 'monotonic', return_value=1401), patch.object(levels.time, 'time', return_value=2000000000):
            await levels.CommunityLevels.voice_tick.coro(self.cog)
        self.assertEqual(self.voice_xp(10), 50)
        self.assertEqual(self.voice_xp(11), 25)

    async def test_peer_deafens_during_first_award_no_invalid_second(self):
        async def deafen():
            before = types.SimpleNamespace(channel=self.channel)
            self.b.voice.self_deaf = True
            await self.cog.on_voice_state_update(self.b, before, self.b.voice)
        await self.run_interleaving(deafen)
        self.assertEqual(self.voice_xp(10), 25)
        self.assertEqual(self.voice_xp(11), 0)
        self.assertEqual(self.cog.voice_clock, {})

    async def test_disconnect_during_first_award_keeps_clocks_empty(self):
        async def disconnect():
            await self.cog.on_disconnect()
            self.bot.is_ready.return_value = False
        await self.run_interleaving(disconnect)
        self.assertEqual(self.voice_xp(10), 25)
        self.assertEqual(self.voice_xp(11), 0)
        self.assertEqual(self.cog.voice_clock, {})
        with patch.object(levels.time, 'monotonic', return_value=5000):
            await levels.CommunityLevels.voice_tick.coro(self.cog)
        self.assertEqual(self.voice_xp(11), 0)

    async def test_disconnect_while_waiting_for_ledger_lock_cannot_award(self):
        await self.cog.lock.acquire()
        pending = asyncio.create_task(self.cog.credit(self.a, self.channel,
            'voice', 'waiting-at-disconnect', 2000000000))
        await asyncio.sleep(0)
        await self.cog.on_disconnect()
        self.bot.is_ready.return_value = False
        self.cog.lock.release()
        await pending
        self.assertEqual(self.voice_xp(10), 0)
        self.assertIsNone(self.cog.ledger.event_proof(1, 'waiting-at-disconnect'))

    async def test_new_listener_clock_in_previously_scanned_channel_is_preserved(self):
        earlier = self.make_channel(20)
        self.guild.voice_channels.insert(0, earlier)
        c, d = self.make_member(12, earlier), self.make_member(13, earlier)
        async def join():
            earlier.members = [c, d]
            await self.cog.on_voice_state_update(c,
                types.SimpleNamespace(channel=None), c.voice)
        await self.run_interleaving(join)
        self.assertEqual(self.cog.voice_clock.get((20, 12)), 1000)
        self.assertEqual(self.cog.voice_clock.get((20, 13)), 1000)
        self.assertEqual(self.voice_xp(12), 0)
        self.assertEqual(self.voice_xp(13), 0)
