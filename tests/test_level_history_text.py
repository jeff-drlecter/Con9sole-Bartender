import tempfile
import unittest
from pathlib import Path
from features.level_history import HistoryAudit

class TextReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.audit=HistoryAudit(Path(self.temp.name)/'audit')
        self.job=self.audit.start(1,100,1000,[{'bot':2,'channel':3}])
    def tearDown(self):self.temp.cleanup()
    def game(self,mid,stamp):
        self.audit.record(self.job,message=mid,channel=3,bot=2,stamp=stamp,edited=None,user=10,name='name',kind='normal',reason='candidate',payload={})
    def finish(self,texts,cutoff=900):
        self.audit.state(self.job,'complete')
        self.audit.start_text(self.job,1,[3],dict(cutoff=cutoff,cooldown=60,baseline='plan',users=[10]))
        self.audit.text_checkpoint(self.job,3,100,texts,True);self.audit.text_state(self.job,'complete')
        return self.audit.text_replay(self.job,1)
    def test_game_replaces_later_text_not_additive(self):
        self.game(1,100);self.game(2,160)
        result=self.finish([(3,10,110),(4,10,170)])
        self.assertEqual(result['users'][10]['base_xp'],0)
        self.assertEqual(result['users'][10]['game_accepted'],2)
    def test_shared_cd_with_text_and_60_boundary(self):
        self.game(1,159);self.game(2,160);self.game(3,220)
        result=self.finish([(4,10,100)])
        self.assertEqual(result['users'][10]['base_xp'],2)
    def test_after_baseline_games_are_not_historical_compensation(self):
        self.game(1,800);self.game(2,900)
        self.assertEqual(self.finish([])['users'][10]['base_xp'],1)
    def test_incomplete_scope_refuses_replay_and_policy_cannot_change(self):
        self.game(1,200)
        policy=dict(cutoff=900,cooldown=60,baseline='plan',users=[10])
        self.audit.start_text(self.job,1,[3],policy)
        with self.assertRaises(ValueError):self.audit.text_replay(self.job,1)
        with self.assertRaises(ValueError):self.audit.start_text(self.job,1,[3,4],policy)
        with self.assertRaises(ValueError):self.audit.start_text(self.job,1,[3],dict(policy,cooldown=120))
    def test_ambiguous_initial_cooldown_held_until_gap(self):
        self.game(1,110)
        with self.assertRaises(ValueError):self.finish([(2,10,50),(3,10,90)])
    def test_checkpoints_are_idempotent(self):
        self.game(1,200)
        result=self.finish([(2,10,100)])
        self.audit.text_checkpoint(self.job,3,100,[(2,10,100)],True)
        self.assertEqual(result,self.audit.text_replay(self.job,1))

    def test_unscanned_users_never_get_game_only_estimates(self):
        self.game(1,200)
        self.audit.record(self.job,message=2,channel=3,bot=2,stamp=300,edited=None,user=11,name='other',kind='normal',reason='candidate',payload={})
        result=self.finish([])
        self.assertEqual(set(result['users']),{10})

class TextScopeAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_admin_cannot_read_private_scope_summary(self):
        from unittest.mock import AsyncMock,MagicMock
        import types
        import discord
        from cogs.community_levels import CommunityLevels
        with tempfile.TemporaryDirectory() as temp:
            audit=HistoryAudit(Path(temp)/'audit')
            job=audit.start(1,100,1000,[{'bot':2,'channel':3}]);audit.state(job,'complete')
            audit.start_text(job,1,[3],dict(cutoff=900,cooldown=60,baseline='plan',users=[10]))
            audit.text_checkpoint(job,3,1,[],True);audit.text_state(job,'complete')
            bot=MagicMock();cog=CommunityLevels(bot);cog.history_audit=audit;cog.guard=AsyncMock(return_value=True)
            requester=object();guild=types.SimpleNamespace(id=1,me=object())
            channel=types.SimpleNamespace(guild=guild,permissions_for=lambda member:discord.Permissions(view_channel=member is not requester,read_message_history=True))
            bot.get_channel.return_value=channel
            inter=types.SimpleNamespace(guild_id=1,guild=guild,user=requester,followup=types.SimpleNamespace(send=AsyncMock()))
            await cog.history_text_command.callback(cog,inter,status_only=True)
            kwargs=inter.followup.send.call_args.kwargs
            self.assertNotIn('file',kwargs)
            self.assertIn('權限',inter.followup.send.call_args.args[0])
            self.assertNotIn('合併後',inter.followup.send.call_args.args[0])

    async def test_completed_text_attachment_is_explicitly_private(self):
        from unittest.mock import AsyncMock,MagicMock
        import types
        import discord
        from cogs.community_levels import CommunityLevels
        with tempfile.TemporaryDirectory() as temp:
            audit=HistoryAudit(Path(temp)/'audit');job=audit.start(1,100,1000,[{'bot':2,'channel':3}])
            audit.state(job,'complete');audit.start_text(job,1,[3],dict(cutoff=900,cooldown=60,baseline='plan',users=[10]))
            audit.text_checkpoint(job,3,1,[],True);audit.text_state(job,'complete')
            guild=types.SimpleNamespace(id=1,me=object())
            channel=types.SimpleNamespace(guild=guild,permissions_for=lambda member:discord.Permissions(view_channel=True,read_message_history=True))
            bot=MagicMock();bot.get_channel.return_value=channel
            cog=CommunityLevels(bot);cog.history_audit=audit;cog.guard=AsyncMock(return_value=True)
            inter=types.SimpleNamespace(guild_id=1,guild=guild,user=object(),followup=types.SimpleNamespace(send=AsyncMock()))
            await cog.history_text_command.callback(cog,inter,status_only=True)
            self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])
            self.assertIn('file',inter.followup.send.call_args.kwargs)
