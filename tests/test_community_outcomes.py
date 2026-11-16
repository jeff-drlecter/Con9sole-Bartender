import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from features.community_outcomes import Outcomes, window, HK, display, test_channel
from features.squad_plans import PlanBook


def human(uid, bot=False):
    return NS(id=uid, bot=bot)


class OutcomesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 200000
        self.path = Path(self.tmp.name) / 'stats.sqlite3'
        self.store = Outcomes(self.path, clock=lambda: self.now)

    def plan(self, key='a', **changes):
        return dict(dict(id=key, guild=1, channel=10, created_at=1000, start=2000,
                         status='ended', session='s1'), **changes)

    def report(self, plans, **kwargs):
        return self.store.report(1, plans, 0, self.now, **kwargs)

    def test_restart_rejoin_duplicate_and_cross_session_uniques(self):
        self.store.observe(1, 's1', 'a', [human(1), human(2), human(99, True)], source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        self.store = Outcomes(self.path, clock=lambda: self.now)
        self.store.observe(1, 's1', 'a', [human(1), human(2)], source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        self.store.observe(1, 's2', 'b', [human(1)], source=dict(channel=10,voice=10,origin='natural' if 'b' is None else 'linked'))
        r = self.report([self.plan(), self.plan('b', session='s2')])
        self.assertEqual((r['attendance'], r['unique'], r['repeat']), (3, 2, 1))
        self.assertEqual(r['rate'], 1)

    def test_cohort_future_cancelled_unopened_unknown(self):
        plans = [self.plan(), self.plan('cancel', status='cancelled'),
                 self.plan('expired', status='expired'), self.plan('unknown', status='history'),
                 self.plan('future', start=self.now+1), self.plan('future_cancel', start=self.now+1, status='cancelled')]
        r = self.report(plans)
        self.assertEqual((r['new'], r['matured'], r['pending']), (6, 4, 2))
        self.assertEqual((r['opened'], r['cancelled'], r['unopened'], r['unknown']), (1, 1, 1, 1))
        self.assertIsNone(r['rate'])
        r = self.report(plans[:3])
        self.assertAlmostEqual(r['rate'], 1/3)

    def test_test_markers_guild_and_duplicate_plans_excluded(self):
        self.store.observe(1, 's1', 'a', [human(1)], test=True, source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        self.store.observe(1, 's1', 'a', [human(2)], test=False, source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        r = self.report([self.plan(), self.plan(), self.plan('b', analytics_test=True),
                         self.plan('c', is_test=True), self.plan('d', channel=11),
                         self.plan('other', guild=2)], excluded_channels=[11])
        self.assertEqual((r['new'], r['excluded'], r['attendance']), (0, 4, 0))
        self.assertTrue(test_channel(NS(name='體驗交流', category=NS(name='社群測試區'))))

    def test_unknown_historical_created_and_attendance_not_invented(self):
        legacy = self.plan()
        legacy.pop('created_at')
        legacy.update(members=[1,2], late=[2], party=9)
        r = self.report([legacy, self.plan('new', session='s2')])
        self.assertEqual((r['undated'],r['new'],r['attendance'],r['attendance_sessions']), (1,1,0,0))
        self.assertIn('出席未知', display(r))
        self.assertIn('資料不足', display(self.report([])))

    def test_hk_day_week_and_year_boundary(self):
        now = datetime(2027,1,4,0,0,1,tzinfo=HK).timestamp() # Monday
        day, end = window('day', now)
        week, _ = window('week', now)
        prev, prev_end = window('previous_week', now)
        self.assertEqual(day, week)
        self.assertEqual(end-day, 1)
        self.assertEqual(prev_end, week)
        self.assertEqual(datetime.fromtimestamp(prev,HK).strftime('%Y-%m-%d'), '2026-12-28')
        self.assertEqual(window('day', now-2)[0], day-86400)

    def test_retrospective_same_creation_cohort_as_of_now(self):
        p = self.plan(start=10000)
        r = self.store.report(1,[p],0,5000,as_of=self.now)
        self.assertEqual((r['matured'],r['opened']), (1,1))
        r = self.store.report(1,[p],1001,self.now)
        self.assertEqual(r['new'], 0)

    def test_plan_creation_metadata_persisted_and_legacy_unmodified(self):
        path = Path(self.tmp.name)/'plans.json'
        book = PlanBook(path, clock=lambda: 1000)
        p = book.create(guild=1,channel=10,owner=1,game='FC',mode='',start=2000,
                        party=1,capacity=3,analytics_test=True)
        reopened = PlanBook(path, clock=lambda: 3000)
        self.assertEqual(reopened.get(p['id'])['created_at'],1000)
        self.assertTrue(reopened.get(p['id'])['analytics_test'])


class PrivateTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_authority_denial_and_revocation(self):
        from cogs.community_outcomes import CommunityOutcomes
        from core.storage_paths import DATA_DIR
        cog = object.__new__(CommunityOutcomes)
        inter = NS(guild_id=1, guild=NS(fetch_member=AsyncMock(return_value=human(1)),fetch_roles=AsyncMock(return_value=[])), user=human(1),
                   response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        with patch('cogs.community_outcomes.config.GUILD_ID',1), patch('cogs.community_outcomes.is_server_admin',return_value=False):
            self.assertFalse(await cog.authorized(inter))
        cog.authorized = AsyncMock(return_value=False)
        await CommunityOutcomes.report.callback(cog,inter)
        self.assertTrue(inter.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn('管理員', inter.followup.send.call_args.args[0])
        cog.authorized = AsyncMock(side_effect=[True,False])
        cog.bot = NS(get_cog=lambda _: NS(book=NS(all=lambda: [])))
        cog.excluded = set()
        cog.store = NS(report=lambda *a,**k: {})
        await CommunityOutcomes.report.callback(cog,inter)
        self.assertIn('權限已改變',inter.followup.send.call_args.args[0])

    async def test_sampler_current_members_only_live_matching_session(self):
        from cogs.community_outcomes import CommunityOutcomes
        cog = object.__new__(CommunityOutcomes)
        channel = NS(id=10, name='FC', category=None, members=[human(1),human(99,True)])
        plan = dict(id='a',guild=1,channel=20,status='live',session='s1')
        sessions = {'10':dict(id='s1',plan_id='a',participants={'555':'old history'})}
        cards = NS(state={'sessions':sessions})
        plans = NS(book=NS(get=lambda _: plan))
        guild = NS(id=1,afk_channel=None,get_channel=lambda uid: channel if uid==10 else None)
        cog.bot = NS(is_ready=lambda:True,get_guild=lambda _:guild,
                     get_cog=lambda name: cards if name=='SquadCards' else plans)
        cog.excluded = set()
        with tempfile.TemporaryDirectory() as tmp:
            cog.store=Outcomes(Path(tmp)/'stats.sqlite3',clock=lambda:200000)
            await cog.observe()
            r=cog.store.report(1,[dict(plan,created_at=1000,start=2000)],0,200001)
            self.assertEqual(r['attendance'],1)
            plan['status']='gathering'
            channel.members=[human(2)]
            await cog.observe()
            plan['status']='live'; plan['session']='different'
            await cog.observe()
            r=cog.store.report(1,[dict(plan,created_at=1000,start=2000)],0,200001)
            self.assertEqual(r['attendance'],1)


class RewardEvidenceTests(unittest.TestCase):
    def test_subscription_actions_no_longer_award_even_after_shared_cd(self):
        from features.community_levels import Ledger
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp)/'levels.sqlite3')
            ledger.configure(1, mode='active')
            self.assertIsNone(ledger.award(1, 2, 'activity', 'interest:g:2:100', 100))
            self.assertIsNone(ledger.award(1, 2, 'activity', 'interest:g:2:101', 110))
            self.assertIsNone(ledger.award(1, 2, 'activity', 'interest:g:2:102', 161))
            self.assertEqual(ledger.profile(1,2)['activity'], 0)


class InventoryTests(unittest.TestCase):
    def test_missing_sources_do_not_initialize_databases(self):
        from scripts.inventory_outcomes import inventory
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            r=inventory(root)
            self.assertEqual(r['plans'],'unavailable')
            self.assertEqual(list(root.iterdir()),[])

    def test_unpublished_is_not_a_new_squad(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Outcomes(Path(tmp)/'stats.sqlite3')
            r=store.report(1,[dict(id='p',guild=1,channel=1,created_at=1,start=2,status='posting')],0,10000)
            self.assertEqual((r['new'],r['unpublished'],r['excluded']),(0,1,0))


class RoundTwoEvidenceTests(unittest.TestCase):
    setUp = OutcomesTests.setUp
    plan = OutcomesTests.plan
    report = OutcomesTests.report

    def test_state_contract_never_turns_intent_or_legacy_into_attendance(self):
        from features.squad_outcome_state import evidence, session_origin
        for state in ('open','due','gathering','history','started'):
            result=evidence(self.plan(status=state, members=[1,2], party=8), as_of=self.now)
            self.assertEqual(result['outcome'], 'unknown')
            self.assertIsNone(result['attendance'])
            self.assertIsNone(result['co_participation'])
        self.assertEqual(session_origin(dict(id='s',message=123),None,1), 'natural')
        self.assertEqual(session_origin(dict(id='s',message=123,plan_id='missing'),None,1), 'unknown')
        self.assertEqual(session_origin(dict(id='s'),None,1), 'waiting')

    def test_natural_is_separate_and_sequential_people_do_not_imply_coplay(self):
        self.store.observe(1,'natural',None,[human(1)], source=dict(channel=10,voice=10,origin='natural' if None is None else 'linked'))
        self.now += 60
        self.store.observe(1,'natural',None,[human(2)], source=dict(channel=10,voice=10,origin='natural' if None is None else 'linked'))
        r=self.report([self.plan()])
        self.assertEqual((r['attendance'],r['natural_sessions'],r['natural_attendance']), (0,1,2))
        self.assertEqual(r['opened'],1)
        self.assertIn('共同參與已觀察達標：約局 0 局', display(r))
        self.assertIn('出席未知（沒有可用觀測）', display(r))
        self.assertNotIn('成局率',display(r))
        self.assertIn('暫時冇可用觀測',display(r,'hk'))
        self.assertLess(len(display(r)), 2000)

    def test_observation_clock_coverage_and_test_natural_exclusion(self):
        self.store.heartbeat('run-a',success=True)
        self.now += 100
        self.store=Outcomes(self.path,clock=lambda:self.now)
        self.store.heartbeat('run-b',success=False)
        self.store.observe(1,'test-natural',None,[human(2)],test=True, source=dict(channel=10,voice=10,origin='natural' if None is None else 'linked'))
        r=self.report([])
        self.assertEqual((r['last_success'],r['observation_failures'],r['natural_sessions']), (200000,1,0))
        self.assertEqual(r['natural_since'], 200000)
        # Restart failures cannot establish any observation during the gap.
        self.assertIn('重啟／漏接未知', display(r))

    def test_session_uniques_are_not_concurrent_and_period_is_half_open(self):
        self.store.observe(1,'s1','a',[human(1)], source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        self.now+=1
        self.store.observe(1,'s1','a',[human(2)], source=dict(channel=10,voice=10,origin='natural' if 'a' is None else 'linked'))
        r=self.report([self.plan(),self.plan('at-end',created_at=self.now)])
        self.assertEqual((r['new'],r['per_session'],r['attendance']), (1,[2],2))
        self.assertIsNone(__import__('features.squad_outcome_state',fromlist=['evidence']).evidence(self.plan(),as_of=self.now)['co_participation'])


class RoundTwoPrivateTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_report_is_private_unknown_not_zero(self):
        from cogs.community_outcomes import CommunityOutcomes
        cog=object.__new__(CommunityOutcomes)
        cog.authorized=AsyncMock(return_value=True)
        cog.bot=NS(get_cog=lambda _: NS(book=NS(all=lambda: [])))
        cog.excluded=set()
        def broken(*a,**k): raise OSError('fixture unavailable')
        cog.store=NS(report=broken)
        inter=NS(guild_id=1,guild=NS(),user=human(1),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await CommunityOutcomes.report.callback(cog,inter)
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn('未將缺漏當作零', inter.followup.send.call_args.args[0])

    async def test_natural_sampler_never_recovers_accumulated_roster_or_unknown_link(self):
        from cogs.community_outcomes import CommunityOutcomes
        cog=object.__new__(CommunityOutcomes)
        channel=NS(id=10,name='普通遊戲',category=None,members=[human(3)])
        session=dict(id='s1',message=123,participants={'777':'historical'})
        cards=NS(state={'sessions':{'10':session}})
        plans=NS(book=NS(get=lambda _:None))
        guild=NS(id=1,afk_channel=None,get_channel=lambda _:channel)
        cog.bot=NS(is_ready=lambda:True,get_guild=lambda _:guild,get_cog=lambda n:cards if n=='SquadCards' else plans)
        cog.excluded=set()
        with tempfile.TemporaryDirectory() as tmp:
            cog.store=Outcomes(Path(tmp)/'out.sqlite3',clock=lambda:100)
            await cog.observe()
            session['plan_id']='missing';channel.members=[human(4)]
            await cog.observe()
            r=cog.store.report(1,[],0,101)
            self.assertEqual((r['natural_sessions'],r['natural_attendance']), (1,1))
