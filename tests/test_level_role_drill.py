import tempfile
import types
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock
from features.community_levels import Ledger,REWARD_NAMES
from features.level_role_drill import restore

class RoleDrillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.temp.name)/'live')
        self.roles=[types.SimpleNamespace(id=level*10,name=f'Lv {level} {name}') for level,name in REWARD_NAMES.items()]
        self.member=types.SimpleNamespace(id=10,roles=[],joined_at=datetime.fromtimestamp(1000,timezone.utc),add_roles=AsyncMock())
        async def add(*roles,**kwargs):self.member.roles.extend(r for r in roles if r not in self.member.roles)
        self.member.add_roles.side_effect=add
        self.guild=types.SimpleNamespace(id=1,roles=self.roles,me=object(),get_role=lambda rid:next((r for r in self.roles if r.id==rid),None),fetch_member=AsyncMock(return_value=self.member))
        self.marker=dict(id='batch',user=10,joined_at=1000,roles=[50],state='pending',remove_succeeded=True,mapping={str(level):level*10 for level in REWARD_NAMES})
        self.ledger.configure(1,mode='off',role_drill=self.marker)
    async def asyncTearDown(self):self.temp.cleanup()
    async def test_restart_restores_only_original_role_and_keeps_xp(self):
        restarted=Ledger(self.ledger.path)
        result=await restore(self.guild,restarted,restarted.settings(1)['role_drill'],lambda r,m:True)
        self.assertEqual(result['state'],'restored');self.assertEqual([r.id for r in self.member.roles],[50])
        self.assertEqual(self.ledger.profile(1,10)['total'],0)
        self.assertEqual(self.ledger.settings(1)['mode'],'off')
        self.member.add_roles.reset_mock()
        await restore(self.guild,self.ledger,result,lambda r,m:True)
        self.member.add_roles.assert_not_awaited()
    async def test_failed_restore_remains_pending_for_retry(self):
        self.member.add_roles.side_effect=ValueError('simulated REST failure')
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.assertEqual(self.ledger.settings(1)['role_drill']['state'],'pending')
        self.assertEqual(self.member.roles,[])
    async def test_new_level_role_is_never_removed_or_overwritten(self):
        self.member.roles=[r for r in self.roles if r.id==150]
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.member.add_roles.assert_not_awaited();self.assertEqual([r.id for r in self.member.roles],[150])
    async def test_rejoined_member_and_unsafe_role_never_granted_old_role(self):
        self.member.joined_at=datetime.fromtimestamp(2000,timezone.utc)
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.member.joined_at=datetime.fromtimestamp(1000,timezone.utc)
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:False)
        self.member.add_roles.assert_not_awaited()

    async def test_same_ids_remapped_to_other_levels_are_rejected(self):
        self.roles[0].id,self.roles[1].id=self.roles[1].id,self.roles[0].id
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.member.add_roles.assert_not_awaited()
    async def test_rejoin_during_add_rolls_back_only_stale_grant(self):
        async def add(*roles,**kwargs):
            self.member.roles.extend(roles)
            self.member.joined_at=datetime.fromtimestamp(2000,timezone.utc)
        async def remove(*roles,**kwargs):self.member.roles=[r for r in self.member.roles if r not in roles]
        self.member.add_roles.side_effect=add;self.member.remove_roles=AsyncMock(side_effect=remove)
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.assertEqual(self.member.roles,[])
        self.assertEqual(self.ledger.settings(1)['role_drill']['state'],'aborted_rejoined')

    async def test_failed_rollback_retries_durable_phase_not_stale_memory(self):
        from unittest.mock import MagicMock,patch
        from cogs.community_levels import CommunityLevels
        async def add(*roles,**kwargs):
            self.member.roles.extend(roles);self.member.joined_at=datetime.fromtimestamp(2000,timezone.utc)
        async def remove(*roles,**kwargs):self.member.roles=[r for r in self.member.roles if r not in roles]
        self.member.add_roles.side_effect=add;self.member.remove_roles=AsyncMock(side_effect=ValueError('REST failed'))
        with self.assertRaises(ValueError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        self.assertEqual(self.ledger.settings(1)['role_drill']['state'],'rollback')
        cog=CommunityLevels(MagicMock());cog.ledger=self.ledger;cog.cfg={'role_drill':self.marker}
        self.member.remove_roles.side_effect=remove
        with patch('cogs.community_levels.reward_role_safe',return_value=True):await cog.retry_role_drill(self.guild)
        self.assertEqual(self.member.roles,[])
        self.assertEqual(cog.cfg['role_drill']['state'],'aborted_rejoined')
    async def test_restart_after_grant_intent_detects_rejoined_stale_grant(self):
        async def add(*roles,**kwargs):
            self.member.roles.extend(roles);self.member.joined_at=datetime.fromtimestamp(2000,timezone.utc)
        async def remove(*roles,**kwargs):self.member.roles=[r for r in self.member.roles if r not in roles]
        self.member.add_roles.side_effect=add;self.member.remove_roles=AsyncMock(side_effect=remove)
        self.guild.fetch_member.side_effect=[self.member,RuntimeError('process stopped')]
        with self.assertRaises(RuntimeError):await restore(self.guild,self.ledger,self.marker,lambda r,m:True)
        restarted=Ledger(self.ledger.path);marker=restarted.settings(1)['role_drill']
        self.assertEqual(marker['grant_intent'],[50])
        self.guild.fetch_member.side_effect=None
        with self.assertRaises(ValueError):await restore(self.guild,restarted,marker,lambda r,m:True)
        self.assertEqual(self.member.roles,[])
        self.assertEqual(restarted.settings(1)['role_drill']['state'],'aborted_rejoined')
