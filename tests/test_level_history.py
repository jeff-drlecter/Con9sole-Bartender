import tempfile
import unittest
import types
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
import discord
from pathlib import Path

from features.level_history import HistoryAudit
from features.community_levels import Ledger
from cogs.community_levels import CommunityLevels


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'history.db'
        self.audit=HistoryAudit(self.path)
        self.job=self.audit.start(1,100,1000,[{'bot':20,'channel':30}])

    def tearDown(self):self.tmp.cleanup()

    def record(self,message,stamp,*,user=10,preview=0,reason='candidate'):
        self.audit.record(self.job,message=message,channel=30,bot=20,stamp=stamp,edited=None,
            user=user,name='private-account',kind='normal',reason=reason,payload={'description':'private body'},preview_xp=preview)

    def test_overlap_restart_and_resume_keep_one_immutable_observation(self):
        self.record(1,100)
        self.audit.checkpoint(self.job,30,1)
        self.audit.state(self.job,'paused')
        again=HistoryAudit(self.path)
        self.assertEqual(again.start(1,100,2000,[{'bot':20,'channel':99}]),self.job)
        self.assertEqual(again.job(self.job,1)['cutoff'],1000)
        self.assertEqual(again.job(self.job,1)['cursors'],[(30,1,0)])
        self.record(1,200,user=11)
        self.assertEqual(again.summary(self.job,1)['potential'],{10:1})

    def test_shared_game_boundary_is_59_rejected_60_accepted(self):
        self.record(1,100);self.record(2,159);self.record(3,160)
        summary=self.audit.summary(self.job,1)
        self.assertEqual(summary['potential'],{10:2})
        self.assertEqual(summary['cooldown'],1)

    def test_preview_excludes_nearby_candidates_in_both_directions(self):
        self.record(1,100);self.record(2,104,preview=1);self.record(3,127)
        self.record(4,164)
        summary=self.audit.summary(self.job,1)
        self.assertEqual(summary['preview'],1)
        self.assertEqual(summary['potential'],{10:1})
        self.assertEqual(summary['cooldown'],2)

    def test_unresolved_departed_and_edited_are_never_potential_awards(self):
        self.record(1,100,user=None,reason='identity_unresolved')
        self.record(2,200,reason='departed_or_not_cached')
        self.record(3,300,reason='edited_card_history_unavailable')
        self.assertEqual(self.audit.summary(self.job,1)['potential'],{})
        with self.assertRaises(ValueError):self.audit.summary(self.job,2)

    def test_ambiguous_owner_is_not_guessed_and_identity_is_hashed(self):
        self.audit.remember_owner(self.job,20,'private-account',10)
        self.assertEqual(self.audit.resolve_owner(self.job,20,'private-account'),10)
        self.audit.remember_owner(self.job,20,'private-account',11)
        self.assertIsNone(self.audit.resolve_owner(self.job,20,'private-account'))
        self.record(1,100)
        for file in Path(self.tmp.name).glob('*'):
            self.assertNotIn(b'private-account',file.read_bytes())
            self.assertNotIn(b'private body',file.read_bytes())

    def test_audit_never_changes_live_xp_periods_or_cooldowns(self):
        live=Ledger(Path(self.tmp.name)/'live.db')
        live.configure(1,mode='preview')
        live.award(1,10,'activity','m:1',100)
        before=live.profile(1,10)
        self.record(1,100,preview=1);self.record(2,200)
        self.audit.checkpoint(self.job,30,2,done=True);self.audit.state(self.job,'complete')
        self.assertEqual(live.profile(1,10),before)
        self.assertEqual(live.event_proof(1,'m:1'),(10,1,100))
        self.assertIsNone(live.award(1,10,'text','still-cooldown',159))
        self.assertEqual(self.audit.summary(self.job,1)['complete_channels'],1)

    def test_final_pet_mapping_is_order_independent_and_rejects_later_conflict(self):
        self.audit.record(self.job,message=1,channel=30,bot=20,stamp=200,edited=None,user=None,
            name='player',kind='pet',reason='identity_unresolved',payload={})
        self.audit.remember_owner(self.job,20,'player',10)
        names={10:self.audit.owner_hash('player')}
        self.audit.finalize_pets(self.job,names)
        self.assertEqual(self.audit.summary(self.job,1)['potential'],{10:1})
        self.audit.remember_owner(self.job,20,'player',11) # historical renamed/departed collision
        self.audit.finalize_pets(self.job,names)
        self.assertEqual(self.audit.summary(self.job,1)['potential'],{})
        self.assertEqual(self.audit.summary(self.job,1)['reasons'],{'owner_ambiguous':1})

    def test_other_preview_engagement_excludes_nearby_game_candidate(self):
        self.record(1,100)
        self.audit.preview_events(self.job,[('text:earlier',10,90),('text:other-guild-member',11,200)])
        self.assertEqual(self.audit.summary(self.job,1)['potential'],{})


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_edited_normal_never_supplies_pet_identity(self):
        with tempfile.TemporaryDirectory() as temp,patch('config.GUILD_ID',1):
            member=types.SimpleNamespace(id=10,name='player',bot=False)
            guild=types.SimpleNamespace(id=1,members=[member],get_member=lambda uid:member if uid==10 else None)
            channel=MagicMock(spec=discord.Thread);channel.guild=guild
            result=discord.Embed(title='Boss attack!',description='Damage Taken: 1')
            def msg(mid,stamp,description,title,edited=None):
                return types.SimpleNamespace(id=mid,author=types.SimpleNamespace(id=20,bot=True),webhook_id=None,
                    guild=guild,created_at=datetime.fromtimestamp(stamp,timezone.utc),edited_at=edited,
                    embeds=[discord.Embed(title=title,description=description),result])
            normal=msg(1,100,'<@10>','player',datetime.fromtimestamp(300,timezone.utc))
            pet=msg(2,400,"*player's pet attacking*\nLevel: 1",'Pet')
            async def history(**kwargs):
                for message in [pet,normal]:yield message
            channel.history=history
            bot=MagicMock();bot.get_channel.return_value=channel;bot.get_guild.return_value=guild
            cog=CommunityLevels(bot);cog.ledger=Ledger(Path(temp)/'live')
            cog.history_audit=HistoryAudit(Path(temp)/'audit')
            job=cog.history_audit.start(1,90,1000,[{'bot':20,'channel':30}])
            await cog.collect_history(job)
            summary=cog.history_audit.summary(job,1)
            self.assertEqual(summary['state'],'complete')
            self.assertEqual(summary['potential'],{})
            self.assertIsNone(cog.history_audit.resolve_owner(job,20,'player'))


if __name__=='__main__':unittest.main()
