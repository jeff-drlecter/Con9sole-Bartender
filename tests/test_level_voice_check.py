import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock,patch
from cogs.community_levels import CommunityLevels
from features.community_levels import Ledger

class VoiceCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostic_reports_stopped_loop_and_preserves_clock_and_xp(self):
        with tempfile.TemporaryDirectory() as temp:
            cog=CommunityLevels(MagicMock());cog.ledger=Ledger(Path(temp)/'live');cog.cfg=cog.ledger.configure(1,mode='preview')
            cog.guard=AsyncMock(return_value=True);cog.gateway_confirmed=True;cog.bot.is_ready.return_value=True
            task=MagicMock();task.done.return_value=True;task.cancelled.return_value=False;task.exception.return_value=TypeError('test failure')
            cog.voice_tick=MagicMock();cog.voice_tick.get_task.return_value=task;cog.voice_tick.is_running.return_value=False;cog.voice_tick.failed.return_value=True
            state=types.SimpleNamespace(self_deaf=False,deaf=False,afk=False,suppress=False)
            members=[types.SimpleNamespace(id=uid,bot=False,roles=[],voice=state) for uid in (10,11)]
            channel=types.SimpleNamespace(id=3,name='call',parent_id=None,category_id=None,members=members,permissions_for=lambda u:types.SimpleNamespace(view_channel=True))
            guild=types.SimpleNamespace(id=1,voice_channels=[channel],stage_channels=[],afk_channel=None)
            inter=types.SimpleNamespace(guild=guild,guild_id=1,followup=types.SimpleNamespace(send=AsyncMock()),user=object())
            cog.voice_clock={(3,10):300,(3,11):300};before=dict(cog.voice_clock)
            with patch('cogs.community_levels.time.monotonic',return_value=350):await cog.voice_check.callback(cog,inter)
            text=inter.followup.send.call_args.args[0]
            self.assertIn('TypeError: test failure',text);self.assertIn('有效 2',text);self.assertIn('50秒',text)
            self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])
            self.assertEqual(cog.voice_clock,before);self.assertEqual(cog.ledger.profile(1,10)['voice'],0)

    async def test_actual_discord_guild_public_afk_property_supports_timer(self):
        import discord
        guild=object.__new__(discord.Guild);guild._channels={};guild._afk_channel_id=None
        self.assertFalse(hasattr(guild,'afk_channel_id'))
        cog=CommunityLevels(MagicMock());cog.cfg=dict(excluded_roles=[],excluded_channels=[])
        state=types.SimpleNamespace(self_deaf=False,deaf=False,afk=False,suppress=False)
        members=[types.SimpleNamespace(id=uid,bot=False,roles=[],voice=state) for uid in (10,11)]
        channel=types.SimpleNamespace(id=3,guild=guild,parent_id=None,category_id=None,members=members)
        self.assertEqual(cog.reconcile_voice_members(channel,100),members)
        self.assertEqual(cog.voice_clock,{(3,10):100,(3,11):100})
        guild._channels={3:channel};guild._afk_channel_id=3
        self.assertEqual(cog.reconcile_voice_members(channel,200),[])
        self.assertEqual(cog.voice_clock,{})
