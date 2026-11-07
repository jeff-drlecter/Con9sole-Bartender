"""Role disappearance and retained-vs-archived migration regressions."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock
import discord
from cogs.community_levels import CommunityLevels,replacement_preflight
from features.community_levels import Ledger,REWARD_NAMES,threshold
from features.level_history import HistoryAudit
from core.sqlite_storage import connect_sqlite

class Role:
    def __init__(self,rid,level):
        self.id=rid;self.name=f'Lv {level} {REWARD_NAMES[level]}'
        self.permissions=discord.Permissions.none();self.managed=False
    def is_default(self):return False
    def __ge__(self,other):return False

class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_any_role_performs_no_external_mutation(self):
        for missing in (5,15):
            with tempfile.TemporaryDirectory() as temp:
                cog=CommunityLevels(MagicMock());cog.ledger=Ledger(Path(temp)/'live')
                cog.cfg=cog.ledger.configure(1,mode='active',rewards={'5':50,'15':150})
                guild=types.SimpleNamespace(id=1,get_role=lambda rid: None if rid==missing*10 else object())
                member=types.SimpleNamespace(id=2,guild=guild,roles=[],add_roles=AsyncMock(),remove_roles=AsyncMock())
                self.assertFalse(await cog._apply_rewards_locked(member,(0,threshold(15))))
                member.add_roles.assert_not_awaited();member.remove_roles.assert_not_awaited()
                with connect_sqlite(cog.ledger.path) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM notice_state').fetchone()[0],0)

    async def test_preflight_requires_all_roles_permission_and_announcement(self):
        roles=[Role(level*10,level) for level in REWARD_NAMES]
        me=types.SimpleNamespace(top_role=object(),guild_permissions=discord.Permissions(manage_roles=True))
        guild=types.SimpleNamespace(roles=roles,me=me,get_role=lambda rid:next((r for r in roles if r.id==rid),None))
        mapping={str(level):level*10 for level in REWARD_NAMES}
        self.assertEqual(len(replacement_preflight(guild,mapping)),10)
        with self.assertRaises(ValueError):replacement_preflight(guild,{'5':50})
        channel=types.SimpleNamespace(permissions_for=lambda m:discord.Permissions(view_channel=True))
        with self.assertRaises(ValueError):replacement_preflight(guild,mapping,channel)
        me.guild_permissions.manage_roles=False
        with self.assertRaises(ValueError):replacement_preflight(guild,mapping)

class HistoryReconcileTests(unittest.TestCase):
    def test_archived_award_is_candidate_again_live_award_still_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger=Ledger(Path(temp)/'live');audit=HistoryAudit(Path(temp)/'audit')
            ledger.configure(1,mode='preview');ledger.award(1,2,'activity','m:20',200)
            with connect_sqlite(ledger.path) as db:
                db.execute('INSERT INTO hybrid_plans VALUES(?,?,?,?,?,?,?,?,?)',(1,'plan',99,100,'{}','digest','applied','path','sha'))
                db.execute('INSERT INTO hybrid_shadow VALUES(?,?,?,?,?,?)',(1,'plan',2,'null',json.dumps([['m:10',2,'activity',1,100]]),'[]'))
            job=audit.start(1,90,300,[{'bot':4,'channel':5}])
            for mid,stamp in [(10,100),(20,200)]:
                audit.record(job,message=mid,channel=5,bot=4,stamp=stamp,edited=None,user=2,name='name',kind='normal',reason='candidate',payload={},preview_xp=1)
            audit.preview_events(job,[('m:10',2,100),('m:20',2,200)])
            inventory=ledger.engagement_inventory(1,90,300)
            result=audit.summary(job,1,inventory)
            self.assertEqual(result['potential'],{2:1});self.assertEqual(result['preview'],1)
            self.assertEqual(result['archived_candidates'],1)
            self.assertEqual(ledger.profile(1,2)['total'],1)
