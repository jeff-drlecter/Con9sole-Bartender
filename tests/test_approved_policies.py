import tempfile
from pathlib import Path
from types import SimpleNamespace as N
import unittest
from unittest.mock import AsyncMock
from features.co_participation import CoParticipation
from features.community_outcomes import Outcomes
from features.community_levels import Ledger

KEY=(1,'s',10)

class CoplayTests(unittest.TestCase):
    def setUp(self): self.tracker=CoParticipation()
    def sample(self, t, members=(1,2), locations=None, key=KEY):
        return self.tracker.sample({key:set(members)}, locations or {m:key[2] for m in members}, t)
    def test_requires_same_pair_and_full_120_seconds(self):
        for t in range(0,120,5): self.assertEqual(self.sample(t),[])
        self.assertEqual(self.sample(120),[(KEY,120)])
        self.assertEqual(self.sample(125),[(KEY,120)])
    def test_sequential_people_and_replacement_pair_do_not_qualify(self):
        for t in range(0,125,5): self.assertEqual(self.sample(t,(1,)),[])
        for t in range(125,250,5): self.assertEqual(self.sample(t,(2,)),[])
        for t in range(250,315,5): self.assertEqual(self.sample(t,(1,2)),[])
        for t in range(315,380,5): self.assertEqual(self.sample(t,(2,3)),[])
    def test_short_disconnect_pauses_without_crediting_gap(self):
        for t in range(0,65,5): self.sample(t)
        for t in range(65,90,5): self.sample(t,(1,))
        self.assertEqual(self.sample(90),[])
        for t in range(95,150,5): self.assertEqual(self.sample(t),[])
        self.assertEqual(self.sample(150),[(KEY,150)])
    def test_long_disconnect_cross_room_and_missing_sample_reset(self):
        for scenario in ('long','moved','gap','restart','both_gone'):
            self.tracker=CoParticipation()
            for t in range(0,100,5): self.sample(t)
            if scenario=='long':
                for t in range(100,140,5):self.sample(t,(1,))
                start=140
            elif scenario=='moved':self.sample(100,(1,),{1:10,2:20});start=105
            elif scenario=='gap':start=110
            elif scenario=='restart':self.tracker.reset();start=100
            else:self.sample(100,());start=105
            for t in range(start,start+120,5): self.assertEqual(self.sample(t),[],scenario)
            self.assertEqual(self.sample(start+120),[(KEY,start+120)],scenario)
    def test_no_transfer_between_room_or_session_and_clock_reversal(self):
        for t in range(0,100,5):self.sample(t)
        self.assertEqual(self.sample(100,key=(1,'s',20)),[])
        self.assertEqual(self.sample(105,key=(1,'new',20)),[])
        self.assertEqual(self.sample(90,key=(1,'new',20)),[])
    def test_persist_only_confirmed_milestone_exclude_tests_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'o.sqlite3';store=Outcomes(path,clock=lambda:1000)
            store.observe(1,'s','p',[N(id=1,bot=False),N(id=2,bot=False)])
            for _ in range(2):store.mark_coplay(1,'s',10,1200)
            store.observe(1,'another-session','p',[N(id=1,bot=False),N(id=2,bot=False)])
            store.mark_coplay(1,'another-session',11,1200)
            store.observe(1,'test',None,[N(id=3,bot=False)],test=True)
            store.mark_coplay(1,'test',20,1200)
            store=Outcomes(path,clock=lambda:2000)
            p=dict(id='p',guild=1,channel=9,created_at=100,start=200,status='live',session='s')
            r=store.report(1,[p],0,2100)
            self.assertEqual((r['coplay'],r['natural_coplay']), (1,0))
            self.assertEqual(store.report(1,[p],0,2100,as_of=1199)['coplay'],0)

class ObserverResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_and_failed_observation_discard_partial_time(self):
        import asyncio
        from cogs.community_outcomes import CommunityOutcomes
        cog=object.__new__(CommunityOutcomes)
        cog.observation_lock=asyncio.Lock();cog.coplay=CoParticipation()
        cog.coplay.sample({KEY:{1,2}},{1:10,2:10},100)
        await cog.on_disconnect()
        self.assertEqual(cog.coplay.rooms,{})
        cog.coplay.sample({KEY:{1,2}},{1:10,2:10},105)
        cog._observe=AsyncMock(side_effect=RuntimeError('observation failed'))
        with self.assertRaises(RuntimeError):await cog.observe()
        self.assertEqual(cog.coplay.rooms,{})

class PreferenceXPTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_listener_rejects_preferences_only(self):
        from cogs.community_levels import CommunityLevels
        cog=N(credit=AsyncMock())
        await CommunityLevels.on_community_activity(cog,None,None,'interest:game:user:click')
        cog.credit.assert_not_awaited()
        await CommunityLevels.on_community_activity(cog,None,None,'drink:click')
        cog.credit.assert_awaited_once_with(None,None,'activity','i:drink:click')
    async def test_ledger_preserves_history_and_other_rewards(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'l.sqlite3');ledger.configure(1,mode='active')
            ledger.award(1,2,'activity','i:drink:old',100)
            before=ledger.profile(1,2)
            for stamp in (200,500,900):
                for event in ('interest:game:once','i:interest:game:always'):
                    self.assertIsNone(ledger.award(1,2,'activity',event,stamp))
            self.assertEqual(ledger.profile(1,2),before)
            self.assertIsNotNone(ledger.award(1,2,'activity','i:drink:new',901))
