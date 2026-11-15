import tempfile
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime, timedelta
import unittest
from unittest.mock import AsyncMock, patch
from features.community_outcomes import Outcomes
from features.observed_returns import returns, render, HK
from core.sqlite_storage import connect_sqlite


def ts(day, hour=12):
    return datetime(2026,12,day,hour,tzinfo=HK).timestamp()


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'out.sqlite3';self.now=ts(1)
        self.store=Outcomes(self.path,clock=lambda:self.now)

    def see(self, sid, t, uid=1, *, source=10, origin='natural', guild=1, test=False):
        self.now=t
        self.store.observe(guild,sid,None,[NS(id=uid,bot=False)],test=test,
                           source=dict(channel=source,voice=source,origin=origin))

    def query(self, now, **kw):
        return returns(self.path,1,ts(1,0),ts(2,0),now,**kw)

    def test_same_session_restart_d0_and_cross_day(self):
        self.see('a',ts(1));self.store=Outcomes(self.path,clock=lambda:self.now)
        self.see('a',ts(1)+5);self.see('a',ts(2))
        r=self.query(ts(9,0));self.assertEqual(r['first_observed'],1)
        self.assertEqual((r['windows'][0]['numerator'],r['windows'][7]['numerator']),(0,0))
        self.see('b',ts(1)+10)
        r=self.query(ts(9,0));self.assertEqual(r['windows'][0]['numerator'],1)
        self.see('b',ts(2)) # Same second session re-observed after HK midnight.
        r=self.query(ts(9,0));self.assertEqual(r['windows'][7]['numerator'],1)

    def test_d7_inclusive_d8_excluded_and_d28_maturity(self):
        self.see('a',ts(1));self.see('b',ts(8,23)) # D7
        r=self.query(ts(8,23));self.assertEqual(r['windows'][7]['denominator'],0)
        self.assertEqual(r['windows'][7]['pending'],1)
        r=self.query(ts(9,0));self.assertEqual((r['windows'][7]['numerator'],r['windows'][7]['denominator']),(1,1))
        self.see('first2',ts(1),uid=2);self.see('late2',ts(9,0),uid=2) # D8
        self.see('first3',ts(1),uid=3);self.see('late3',ts(29,23),uid=3) # D28
        r=self.query(ts(30,0))
        self.assertEqual((r['windows'][7]['numerator'],r['windows'][7]['denominator']),(1,3))
        self.assertEqual((r['windows'][28]['numerator'],r['windows'][28]['denominator']),(3,3))
        self.assertIsNone(r['windows'][28]['rate'])

    def test_hk_midnight_year_and_d29_not_return(self):
        first=datetime(2026,12,31,23,59,59,tzinfo=HK).timestamp()
        self.see('a',first);self.see('b',first+2)
        end=datetime(2027,1,28,0,tzinfo=HK).timestamp()
        r=returns(self.path,1,first-86399,first+1,end)
        self.assertEqual(r['windows'][0]['numerator'],0)
        self.assertEqual(r['windows'][7]['numerator'],1)
        self.assertEqual(r['windows'][28]['denominator'],0) # D28 not yet finished.
        r=returns(self.path,1,first-86399,first+1,end+86400)
        self.assertEqual(r['windows'][28]['denominator'],1)

    def test_unknown_legacy_no_backfill_and_migration_rerun(self):
        self.store.observe(1,'legacy',None,[NS(id=1,bot=False)])
        self.store=Outcomes(self.path,clock=lambda:self.now)
        self.see('legacy',ts(1)+1)
        self.see('new',ts(1)+2)
        r=self.query(ts(30,0))
        self.assertEqual((r['first_observed'],r['unknown_people'],r['unknown_rows']),(0,1,1))
        with connect_sqlite(self.path) as db:
            self.assertIsNone(db.execute("SELECT origin FROM outcome_sessions WHERE session='legacy'").fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM outcome_attendance').fetchone()[0],2)

    def test_old_schema_transactional_migration_rerun(self):
        other=Path(self.tmp.name)/'old.sqlite3'
        with sqlite3.connect(other) as db:
            db.execute('CREATE TABLE outcome_sessions(guild INTEGER,session TEXT,plan TEXT,first_seen REAL,test INTEGER,PRIMARY KEY(guild,session))')
            db.execute('INSERT INTO outcome_sessions VALUES(1,\'old\',NULL,100,0)')
        Outcomes(other);Outcomes(other)
        with sqlite3.connect(other) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM outcome_sessions').fetchone()[0],1)
            self.assertIsNone(db.execute('SELECT origin FROM outcome_sessions').fetchone()[0])

    def test_exclusions_later_apply_to_linked_and_natural_without_deletion(self):
        self.see('a',ts(1),origin='linked');self.see('b',ts(2),source=20)
        self.see('test',ts(1),uid=2,test=True)
        self.see('guild2',ts(1),uid=3,guild=2)
        self.assertEqual(self.query(ts(9,0))['windows'][7]['numerator'],1)
        self.assertEqual(self.query(ts(9,0),excluded_channels=[20])['windows'][7]['numerator'],0)
        self.assertEqual(self.query(ts(9,0),origins=['linked'])['windows'][7]['numerator'],0)
        self.assertEqual(self.query(ts(9,0),excluded_channels=[10])['first_observed'],0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM outcome_attendance').fetchone()[0],4)

    def test_coverage_gap_disconnect_error_restart_and_positive_lower_bound(self):
        self.see('a',ts(1));self.see('b',ts(2))
        self.now=ts(1);self.store.heartbeat('run1',success=True,guild=1)
        self.now+=5;self.store.heartbeat('run1',success=True,guild=1)
        self.now+=1;self.store.heartbeat('run1',success=False,guild=1)
        self.now+=1;self.store.heartbeat('run1',success=True,guild=1)
        self.now=ts(9,0);self.store.heartbeat('run2',success=True,guild=1)
        r=self.query(self.now)
        self.assertEqual(r['coverage_seconds'],5)
        self.assertEqual(r['windows'][7]['numerator'],1)
        self.assertIsNone(r['windows'][7]['rate'])
        self.assertIn('不等於流失',render(r))
        self.assertNotIn('user',render(r))

    def test_complete_evidenced_interval_may_show_observed_ratio(self):
        self.see('a',ts(1));self.see('b',ts(2))
        # Equivalent evidence fixture; production extends only <=10s successes.
        with connect_sqlite(self.path) as db:
            db.execute('INSERT INTO outcome_coverage VALUES(?,?,?,?)',(1,'fixture',ts(1),ts(9,0)))
        r=self.query(ts(9,0));self.assertEqual(r['windows'][7]['rate'],1)
        self.assertEqual(r['windows'][28]['pending'],1)

    def test_coplay_ab_does_not_turn_passerby_c_into_qualified_player(self):
        self.see('session',ts(1),uid=1);self.see('session',ts(1),uid=2)
        self.store.mark_coplay(1,'session',10,ts(1)+120)
        self.see('session',ts(1)+130,uid=3)
        r=self.query(ts(30,0))
        self.assertEqual(r['first_observed'],3)
        self.assertEqual(r['windows'][28]['numerator'],0)
        self.assertIn('沒有個人達標推算',render(r))
        with sqlite3.connect(self.path) as db:
            self.assertNotIn('user',{r[1] for r in db.execute('PRAGMA table_info(outcome_coplay)')})

    def test_query_bounds_empty_and_failure(self):
        r=self.query(ts(30,0));self.assertEqual(r['first_observed'],0)
        self.assertIsNone(r['windows'][28]['rate'])
        with self.assertRaises(ValueError):self.query(ts(30,0),origins=['unknown'])
        with self.assertRaises(ValueError):returns(self.path,1,0,100*86400,200*86400)
        with sqlite3.connect(self.path) as db:db.execute('DROP TABLE outcome_attendance')
        with self.assertRaises(sqlite3.Error):self.query(ts(30,0))


class PrivateReturnTests(unittest.IsolatedAsyncioTestCase):
    async def test_denial_revocation_and_query_error_never_output_data(self):
        from cogs.community_outcomes import CommunityOutcomes
        with tempfile.TemporaryDirectory() as tmp:
            cog=object.__new__(CommunityOutcomes);cog.store=Outcomes(Path(tmp)/'db');cog.excluded=set()
            inter=NS(guild_id=1,user=NS(id=1),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
            cog.authorized=AsyncMock(return_value=False)
            await CommunityOutcomes.returns_report.callback(cog,inter)
            self.assertIn('管理員',inter.followup.send.call_args.args[0])
            cog.authorized=AsyncMock(side_effect=[True,False])
            await CommunityOutcomes.returns_report.callback(cog,inter)
            self.assertIn('權限已改變',inter.followup.send.call_args.args[0])
            cog.authorized=AsyncMock(return_value=True)
            with patch('features.observed_returns.returns',side_effect=OSError('test')):
                await CommunityOutcomes.returns_report.callback(cog,inter)
            self.assertIn('缺漏未當作零',inter.followup.send.call_args.args[0])
            self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])

    async def test_health_has_no_attendance_and_contract_matches_03(self):
        from cogs.community_outcomes import CommunityOutcomes, source_contract
        cog=object.__new__(CommunityOutcomes)
        cog.bot=NS(is_ready=lambda:True);cog.sample=NS(is_running=lambda:True)
        cog.last_error=None;cog.last_success=123
        self.assertEqual(set(cog.health_status()),{'available','heartbeat','error'})
        self.assertEqual(source_contract(dict(guild=1,id='p',channel=10,origin='instant'))['origin'],'instant')


class MoreEvidenceTests(unittest.TestCase):
    setUp=ReturnTests.setUp
    see=ReturnTests.see
    query=ReturnTests.query
    def test_source_scope_does_not_relabel_old_member_first_observation(self):
        self.see('old',ts(1)-86400,origin='linked')
        self.see('natural',ts(1),origin='natural')
        self.assertEqual(self.query(ts(30,0),origins=['natural'])['first_observed'],0)

    def test_d29_event_not_in_28day_numerator(self):
        self.see('a',ts(1));self.see('b',ts(30,0))
        self.assertEqual(self.query(ts(31,0))['windows'][28]['numerator'],0)

    def test_source_change_is_unknown_not_silently_rewritten(self):
        self.see('a',ts(1))
        with self.assertRaises(ValueError):self.see('a',ts(1)+5,source=20,origin='linked')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT source_channel,origin FROM outcome_sessions WHERE session='a'").fetchone(),(10,'natural'))
