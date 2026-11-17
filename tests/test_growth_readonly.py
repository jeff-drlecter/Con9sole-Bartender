import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest

from features.community_outcomes import Outcomes
from scripts.inspect_growth_readonly import inspect, read_database, states


class GrowthReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'community_outcomes.sqlite3'
        self.now = 1000

    def store(self):
        return Outcomes(self.path, clock=lambda: self.now)

    def query(self, **kwargs):
        return inspect(self.root, 1, 900, 1100, 1200, environ={}, **kwargs)

    def see(self, store, sid, *, guild=1, test=False, source=10, origin='natural'):
        store.observe(guild, sid, None, [NS(id=987654321, bot=False)], test=test,
            source=dict(channel=source, voice=20, origin=origin))

    def test_missing_sources_never_created_and_unknown_not_zero(self):
        result = self.query()
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(result['outcomes']['status'], 'unavailable_or_incompatible')
        self.assertIsNone(result['outcomes']['rows'])
        self.assertEqual(result['membership_enumeration'], 'not_performed')

    def test_corrupt_source_not_repaired_or_returned_as_empty(self):
        self.path.write_bytes(b'not a database')
        self.assertIsNone(self.query()['outcomes']['rows'])
        self.assertEqual(self.path.read_bytes(), b'not a database')

    def test_empty_raw_data_with_healthy_coverage_not_no_activity_claim(self):
        store = self.store()
        store.heartbeat('run', success=True, guild=1)
        self.now += 5
        store.heartbeat('run', success=True, guild=1)
        r = self.query()['outcomes']
        self.assertEqual(r['diagnostic'], 'raw_attendance_empty')
        self.assertEqual(r['coverage_window']['union_seconds'], 5)
        self.assertEqual(r['observer']['latest_run']['last_success'], 1005)

    def test_test_source_guild_time_filters_and_no_private_identifiers(self):
        store = self.store()
        self.see(store, 'sensitive-session-1', test=True)
        self.see(store, 'sensitive-session-2', guild=2)
        store.observe(1, 'sensitive-legacy', None, [NS(id=123456789,bot=False)])
        r = self.query()['outcomes']
        self.assertEqual(r['diagnostic'], 'target_rows_all_ineligible')
        self.assertEqual(r['window_attendance']['raw_rows'], 2)
        self.see(store, 'sensitive-good')
        r = self.query()
        self.assertEqual(r['outcomes']['window_eligible_attendance']['rows'], 1)
        self.assertNotIn('sensitive-', json.dumps(r))
        self.assertNotIn('987654321', json.dumps(r))
        self.assertNotIn('123456789', json.dumps(r))
        excluded = inspect(self.root,1,900,1100,1200,environ={'OUTCOMES_TEST_CHANNEL_IDS':'10'})
        self.assertEqual(excluded['outcomes']['window_eligible_attendance']['rows'],0)

    def test_half_open_window_and_wrong_guild_not_query_bug(self):
        store = self.store()
        self.now = 1100
        self.see(store, 'at-end')
        self.see(store, 'other-guild', guild=2)
        r = self.query()['outcomes']
        self.assertEqual(r['tables']['outcome_attendance']['rows'],2)
        self.assertEqual(r['diagnostic'],'no_target_guild_window_rows')
        self.assertEqual(r['window_attendance']['raw_rows'],0)

    def test_readonly_transaction_sees_wal_and_cannot_write(self):
        store = self.store()
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO outcome_meta VALUES('wal_fixture',1000)")
        writer.commit()
        self.see(store, 'first')
        before = {p.name:p.read_bytes() for p in (self.path,Path(str(self.path)+'-wal'))}
        self.assertEqual(self.query()['outcomes']['window_eligible_attendance']['rows'],1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.path,Path(str(self.path)+'-wal'))})
        with read_database(self.path) as reader:
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM outcome_attendance').fetchone()[0],1)
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute('DELETE FROM outcome_attendance')
            self.see(store, 'second')
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM outcome_attendance').fetchone()[0],1)
        self.assertEqual(self.query()['outcomes']['window_eligible_attendance']['rows'],2)

    def test_coverage_union_clips_window_and_error_count_not_current_failure(self):
        self.store()
        with sqlite3.connect(self.path) as db:
            db.executemany('INSERT INTO outcome_coverage VALUES(?,?,?,?)',[(1,'a',800,1000),(1,'b',950,1150),(2,'c',0,2000)])
            db.executemany('INSERT INTO outcome_observer_runs VALUES(?,?,?,?)',[('old',500,600,6),('new',1000,1099,0)])
        r = self.query()['outcomes']
        self.assertEqual(r['coverage_window']['union_seconds'],200)
        self.assertEqual(r['coverage_range']['first'],800)
        self.assertEqual(r['observer']['all_runs_failures'],6)
        self.assertEqual(r['observer']['latest_run']['failures'],0)
        self.assertEqual(r['observer']['failure_timestamps'],'not_recorded')

    def test_session_contract_parity_and_no_member_or_plan_details(self):
        from features.squad_outcome_state import session_origin
        plan = dict(id='private-plan',guild=1,status='live',session='linked',created_at=1000)
        sessions = [dict(id='natural',message=3,participants={'123':'SECRET NAME'}),dict(id='waiting'),
            dict(id='linked',plan_id='private-plan',message=4),dict(id='wrong',plan_id='private-plan'),
            dict(id='ended',message=5,ended=1000)]
        cards = self.root/'squad_cards.json'
        plans = self.root/'squad_plans.json'
        cards.write_text(json.dumps(dict(settings={'category':10,'destination':20,'routes':{'10':30}},sessions={str(i):s for i,s in enumerate(sessions)})))
        plans.write_text(json.dumps(dict(plans={plan['id']:plan})))
        result = states(cards,plans,1)
        self.assertEqual(result['routes'],[dict(category=10,destination=30)])
        self.assertEqual({r['origin'] for r in result['session_groups']},
            {session_origin(s,plan if s.get('plan_id') else None,1) for s in sessions})
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertNotIn('private-plan',json.dumps(result))

    def test_referral_half_open_cross_code_union_and_personal_exclusion(self):
        with sqlite3.connect(self.root/'community_levels.sqlite3') as db:
            db.execute('CREATE TABLE referral_links(guild,user,code)')
            db.execute('CREATE TABLE referral_joins(guild,user,joined,code,fresh)')
            db.execute("INSERT INTO referral_links VALUES(1,77,'personal-secret')")
            db.executemany('INSERT INTO referral_joins VALUES(?,?,?,?,?)',[(1,1,900,'public-a',1),
                (1,1,1000,'public-b',0),(1,2,1000,'public-b',1),(1,3,1100,'public-a',1),
                (2,4,1000,'public-a',1),(1,5,1000,None,1),(1,6,1000,'personal-secret',1)])
        r = self.query(codes=['public-a','public-b','public-a','personal-secret'])['referrals']
        self.assertEqual(r['nonpersonal_union'],dict(events=3,distinct_accounts=2))
        self.assertEqual(r['unknown_source_events'],1)
        self.assertEqual(len(r['requested_codes']),3)
        self.assertTrue(r['requested_codes'][2]['personal'])
        self.assertNotIn('personal-secret',json.dumps(r))

    def test_outside_root_override_and_secret_environment_not_exposed(self):
        result = inspect(self.root,1,900,1100,1200,environ={'STATS_DB_PATH':'/elsewhere/private.db',
            'APP_COMMIT':'a'*40,'BOT_TOKEN':'DO NOT PRINT','FLY_API_TOKEN':'DO NOT PRINT'})
        self.assertEqual(result['runtime_app_commit'],'a'*40)
        self.assertEqual(result['card_posts']['status'],'unavailable_or_incompatible')
        self.assertNotIn('DO NOT PRINT',json.dumps(result))
        self.assertNotIn('/elsewhere',json.dumps(result))

    def test_invalid_time_ranges_refused_before_reading(self):
        for start,end,as_of in [(1100,900,1200),(900,1300,1200),(0,91*86400,91*86400),(0,float('inf'),float('inf'))]:
            with self.assertRaises(ValueError):
                inspect(self.root,1,start,end,as_of,environ={})


if __name__ == '__main__':
    unittest.main()
