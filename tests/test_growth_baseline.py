import json
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import discord
from core.sqlite_storage import connect_sqlite
from features.community_outcomes import Outcomes
from features.growth_baseline import (MemberSnapshot, TestAccountRegistry,
                                      baseline, enumerate_members, render, windows)
from features.observed_returns import HK


def ts(day, hour=0):
    return datetime(2026, 12, day, hour, tzinfo=HK).timestamp()


def snapshot(ids=(1, 2, 3), bots=(), complete=True):
    return MemberSnapshot(frozenset(ids), frozenset(bots), dict(
        snapshot_started_at=ts(30), snapshot_finished_at=ts(30)+1,
        enumeration_method='fixture_rest', enumeration_exhausted=complete,
        enumeration_complete=complete, atomic=False, reported_member_count=len(ids),
        reported_member_count_before=len(ids), reported_count_method='fixture',
        reported_count_drift=0, duplicate_ids=0, unknown_reason=[] if complete else ['member_list_incomplete']))


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'outcomes.sqlite3'
        self.now = ts(1)
        self.store = Outcomes(self.path, clock=lambda: self.now)

    def see(self, sid, stamp, uid=1, *, guild=1, origin='natural', source=10, voice=None, test=False, bot=False):
        self.now = stamp
        self.store.observe(guild, sid, None, [NS(id=uid, bot=bot)], test=test,
                           source=dict(channel=source, voice=source if voice is None else voice, origin=origin))

    def query(self, **kwargs):
        members = kwargs.pop('membership', snapshot())
        return baseline(self.path, 1, ts(30,12), members, **kwargs)

    def test_hk_complete_days_and_separate_today_at_month_year_boundary(self):
        as_of = datetime(2027, 1, 1, 1, tzinfo=HK).timestamp()
        periods = windows(as_of)
        self.assertEqual(periods[0], ('7', datetime(2026,12,25,tzinfo=HK).timestamp(), as_of-3600))
        self.assertEqual(periods[1][2]-periods[1][1], 28*86400)
        self.assertEqual(periods[2], ('today_partial', as_of-3600, as_of))
        with self.assertRaises(ValueError): windows(float('nan'))

    def test_actual_timestamp_union_reentry_cross_sources_guild_and_test_filters(self):
        self.see('old', ts(1), 1)
        self.see('old', ts(25), 1)  # visit, first attendance is outside both windows
        self.see('linked', ts(25), 1, origin='linked')
        self.see('natural', ts(26), 2)
        self.see('otherguild', ts(26), 4, guild=2)
        self.see('bot', ts(26), 99, bot=True)
        self.see('test', ts(26), 5, test=True)
        self.see('excluded_source', ts(26), 6, source=20)
        self.see('excluded_voice', ts(26), 7, voice=20)
        self.see('boundary_end', ts(30), 8)
        self.see('boundary_start', ts(23), 9)
        self.see('just_outside', ts(23)-1, 10)
        self.see('asof', ts(30,12), 11)
        r = self.query(excluded_channels=[20])
        self.assertEqual([w['observed_lower_bound'] for w in r['windows']], [3,4,1])
        self.assertIsNone(r['windows'][0]['distinct_accounts'])
        self.assertEqual(r['windows'][0]['current_members']['observed_lower_bound'], 2)
        # Actual first_seen controls eligibility even when a stored day is wrong.
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE outcome_visits SET day='1900-01-01' WHERE session='linked'")
        self.assertEqual(self.query(excluded_channels=[20])['windows'][0]['observed_lower_bound'], 3)

    def test_missing_registry_unknown_staff_not_blanket_excluded_explicit_registry_only(self):
        self.see('staff_or_tester', ts(25), 1)
        self.see('owned_test', ts(25), 2)
        unknown = self.query()
        self.assertIsNone(unknown['membership']['confirmed_owned_test_accounts'])
        self.assertEqual(unknown['windows'][0]['observed_lower_bound'], 2)
        registry = TestAccountRegistry(frozenset({2}), 'synthetic owner confirmation')
        r = self.query(registry=registry)
        self.assertEqual(r['windows'][0]['observed_lower_bound'], 1)
        self.assertEqual(r['membership']['confirmed_owned_test_accounts'], 1)
        self.assertNotIn('account_registry_unverified', r['windows'][0]['unknown_reason'])
        with self.assertRaises(ValueError): TestAccountRegistry(frozenset({2}), '')
        self.assertNotIn('synthetic owner confirmation', json.dumps(r))

    def test_complete_members_intersection_required_no_departure_inference(self):
        self.see('present', ts(25), 1)
        self.see('not_enumerated', ts(25), 2)
        # Fully evidenced interval plus explicitly confirmed (empty) exclusion subset.
        with connect_sqlite(self.path) as db:
            db.execute('INSERT INTO outcome_coverage VALUES(1,?,?,?)', ('fixture',ts(1),ts(30,12)))
        registry = TestAccountRegistry(frozenset(), 'synthetic confirmation')
        partial = self.query(membership=snapshot(ids=(1,),complete=False),registry=registry)
        current = partial['windows'][0]['current_members']
        self.assertIsNone(current['distinct_accounts'])
        self.assertEqual(current['observed_lower_bound'], 1)
        exact = self.query(membership=snapshot(ids=(1,)),registry=registry)
        self.assertEqual(exact['windows'][0]['current_members']['distinct_accounts'], 1)
        self.assertEqual(exact['windows'][0]['distinct_accounts'], 2)
        self.assertNotIn('departed', json.dumps(partial))

    def test_unknown_source_orphan_missing_date_and_test_rows_not_backfilled(self):
        with connect_sqlite(self.path) as db:
            db.execute('INSERT INTO outcome_sessions(guild,session,first_seen,test) VALUES(1,\'legacy\',?,0)', (ts(25),))
            db.execute('INSERT INTO outcome_attendance VALUES(1,\'legacy\',1,?)', (ts(25),))
            db.execute('INSERT INTO outcome_attendance VALUES(1,\'orphan\',2,?)', (ts(25),))
            db.execute('INSERT INTO outcome_attendance VALUES(1,\'orphan\',3,NULL)')
        self.see('test', ts(25), 5, test=True)
        r = self.query()
        self.assertEqual(r['windows'][0]['observed_lower_bound'], 0)
        self.assertEqual(r['windows'][0]['unknown_source_rows'], 2)
        self.assertEqual(r['windows'][0]['unknown_date_rows'], 1)
        self.assertIn('date_unknown', r['windows'][0]['unknown_reason'])
        with connect_sqlite(self.path) as db:
            self.assertIsNone(db.execute("SELECT origin FROM outcome_sessions WHERE session='legacy'").fetchone()[0])

    def test_heartbeat_does_not_create_attendance_or_coverage_uptime(self):
        self.now = ts(29)
        self.store.heartbeat('old',success=False,guild=1)
        self.store.heartbeat('old',success=True,guild=1)
        self.now += 5
        self.store.heartbeat('old',success=True,guild=1)
        self.now = ts(30)
        self.store.heartbeat('new',success=False,guild=1)
        r = self.query()
        self.assertEqual(r['windows'][0]['observed_lower_bound'], 0)
        self.assertEqual(r['windows'][0]['coverage'], dict(status='gap',seconds=5))
        self.assertEqual(r['heartbeat']['cumulative_failures'], 2)
        self.assertIsNone(r['heartbeat']['latest_run']['last_success'])
        self.assertEqual(r['heartbeat']['last_success'], ts(29)+5)
        self.assertNotIn('uptime', json.dumps(r))

    def test_missing_database_schema_or_query_failure_never_create_or_zero(self):
        missing = Path(self.tmp.name)/'missing.sqlite3'
        with self.assertRaises(sqlite3.Error): baseline(missing,1,ts(30),snapshot())
        self.assertFalse(missing.exists())
        with connect_sqlite(self.path) as db: db.execute('DROP TABLE outcome_visits')
        with self.assertRaises(sqlite3.Error): self.query()

    def test_queries_read_live_wal_no_mutations_and_rerun_equivalence(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL').fetchone()
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO outcome_sessions(guild,session,first_seen,test,source_channel,voice_channel,origin) VALUES(1,'live_wal',?,0,10,10,'natural')", (ts(25),))
        writer.execute("INSERT INTO outcome_attendance VALUES(1,'live_wal',1,?)", (ts(25),))
        writer.commit()
        files = [self.path, Path(str(self.path)+'-wal')]
        before = {str(p):p.read_bytes() for p in files}
        r = self.query()
        self.assertEqual(r, self.query())
        self.assertEqual(r['windows'][0]['observed_lower_bound'], 1)
        self.assertEqual(before, {str(p):p.read_bytes() for p in files})

    def test_empty_database_unknown_totals_and_safe_hk_tw_neutral_copy(self):
        r = self.query()
        for code in ('hk','tw','neutral'):
            text = render(r,code)
            self.assertIn('+08:00', text)
            self.assertIn('pending', text)
            self.assertIn('非 Bot 帳戶不代表獨立真人', text)
            self.assertNotIn('<@', text)
            self.assertIn('未知', text)
        self.assertIn('冇記錄唔代表冇活動', render(r,'hk'))
        self.assertIn('沒有記錄不代表沒有活動', render(r,'tw'))


class EnumerationTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self, rows, *, count=None, after=None, error=None):
        guild = NS(member_count=len(rows) if count is None else count)
        async def fetch(*, limit):
            self.assertIsNone(limit)
            for row in rows: yield row
            if after is not None: guild.member_count = after
            if error: raise error
        guild.fetch_members = fetch
        # A cache read is deliberately impossible.
        result = await enumerate_members(guild, clock=iter([100,200]).__next__)
        return result

    async def test_exhausted_rest_unique_ids_bot_totals_capture_times(self):
        r = await self.capture([NS(id=1,bot=False),NS(id=2,bot=True)])
        self.assertTrue(r.metadata['enumeration_complete'])
        self.assertEqual(r.metadata['snapshot_started_at'], 100)
        self.assertEqual(r.metadata['snapshot_finished_at'], 200)
        self.assertEqual(r.aggregate()['non_bot_accounts'], 1)
        self.assertEqual(r.aggregate()['bot_accounts'], 1)
        self.assertFalse(r.metadata['atomic'])

    async def test_duplicate_drift_mismatch_and_failed_pagination_no_cache_fallback(self):
        for kwargs, reason in [({},'duplicate_member_ids'),
                               ({'after':3},'reported_member_count_drift'),
                               ({'count':5},'reported_member_count_mismatch'),
                               ({'error':OSError('private secret')},'membership_read_failed')]:
            rows = [NS(id=1,bot=False)]*2 if not kwargs else [NS(id=1,bot=False)]
            r = await self.capture(rows,**kwargs)
            self.assertFalse(r.metadata['enumeration_complete'])
            self.assertIsNone(r.aggregate()['total_accounts'])
            self.assertEqual(r.aggregate()['observed_total_lower_bound'], 1)
            self.assertIn(reason, r.metadata['unknown_reason'])
            self.assertNotIn('secret', json.dumps(r.aggregate()))


class PrivateBaselineTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        from cogs.community_outcomes import CommunityOutcomes
        cog = object.__new__(CommunityOutcomes)
        cog.store = NS(path=Path('/never/read'))
        cog.excluded = set()
        cog.baseline_scope = lambda guild, now: dict(status='fixture',counts={})
        cog.health_status = lambda: dict(available=True,heartbeat=1,error=None)
        cog.authorized = AsyncMock(return_value=True)
        inter = NS(guild_id=1,guild=NS(id=1),user=NS(id=1),response=NS(defer=AsyncMock(),send_message=AsyncMock()),followup=NS(send=AsyncMock()))
        return CommunityOutcomes,cog,inter

    async def test_denied_admin_helper_member_no_query_and_during_query_revocation(self):
        cls,cog,inter = self.context()
        # Handler consumes the same fresh-authorization policy for all role labels.
        for role in ('member','Helper','Tester'):
            cog.authorized = AsyncMock(return_value=False)
            with patch('features.growth_baseline.enumerate_members',AsyncMock()) as fetch:
                await cls.baseline_report(cog,inter)
                fetch.assert_not_awaited()
            self.assertIn('管理員', inter.followup.send.call_args.args[0])
        cog.authorized = AsyncMock(side_effect=[True,False])
        with patch('features.growth_baseline.enumerate_members',AsyncMock(return_value=snapshot())), \
                patch('features.growth_baseline.baseline',return_value={}), \
                patch('features.growth_baseline.render',return_value='PRIVATE AGGREGATES'):
            await cls.baseline_report(cog,inter)
        self.assertIn('權限已改變', inter.followup.send.call_args.args[0])
        self.assertNotIn('PRIVATE', inter.followup.send.call_args.args[0])

    async def test_actual_member_authorization_fresh_roles_owner_and_guild_checks(self):
        import config
        cls,cog,inter = self.context()
        del cog.authorized
        client = discord.Client(intents=discord.Intents.none())
        self.addAsyncCleanup(client.close)
        guild = discord.Guild(state=client._connection,data=dict(
            id=str(config.GUILD_ID),name='synthetic',owner_id='999',roles=[
                dict(id=str(config.GUILD_ID),name='@everyone',permissions='0'),
                dict(id='77',name='Admin',permissions=str(discord.Permissions(administrator=True).value))]))
        member = discord.Member(guild=guild,state=client._connection,data={
            'user':{'id':'10','username':'fixture','discriminator':'0','avatar':None},
            'roles':['77'],'joined_at':None,'flags':0})
        inter.guild = guild; inter.guild_id = guild.id; inter.user = member
        with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)), \
                patch.object(discord.Guild,'fetch_roles',AsyncMock(return_value=list(guild.roles))):
            self.assertTrue(await cls.authorized(cog,inter))
        for name in ('Admin revoked','Helper','Tester','member'):
            revoked = discord.Role(guild=guild,state=client._connection,data=dict(id='77',name=name,permissions='0'))
            with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)), \
                    patch.object(discord.Guild,'fetch_roles',AsyncMock(return_value=[guild.default_role,revoked])):
                self.assertFalse(await cls.authorized(cog,inter))
        inter.guild_id = guild.id+1
        with patch.object(discord.Guild,'fetch_member',AsyncMock()) as fetch:
            self.assertFalse(await cls.authorized(cog,inter))
            fetch.assert_not_awaited()

    async def test_success_and_query_error_private_no_mentions_or_side_effects(self):
        cls,cog,inter = self.context()
        with patch('features.growth_baseline.enumerate_members',AsyncMock(return_value=snapshot())), \
                patch('features.growth_baseline.baseline',return_value={}), \
                patch('features.growth_baseline.render',return_value='aggregate'):
            await cls.baseline_report(cog,inter)
        self.assertEqual(inter.followup.send.call_args.args, ('aggregate',))
        self.assertEqual(cog.authorized.await_count, 2)
        self.assertTrue(inter.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(inter.followup.send.call_args.kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        with patch('features.growth_baseline.enumerate_members',AsyncMock(return_value=snapshot())), \
                patch('features.growth_baseline.baseline',side_effect=OSError('SECRET')):
            await cls.baseline_report(cog,inter)
        self.assertIn('缺漏未當作零', inter.followup.send.call_args.args[0])
        self.assertNotIn('SECRET', inter.followup.send.call_args.args[0])

    async def test_each_output_rechecks_admin_and_respects_message_limits(self):
        cls,cog,inter = self.context()
        cog.authorized = AsyncMock(side_effect=[True,True,False])
        with patch('features.growth_baseline.enumerate_members',AsyncMock(return_value=snapshot())), \
                patch('features.growth_baseline.baseline',return_value={}), \
                patch('features.growth_baseline.render',return_value=('a'*1000+'\n')*3):
            await cls.baseline_report(cog,inter)
        self.assertEqual(inter.followup.send.await_count, 2)
        self.assertIn('權限已改變', inter.followup.send.call_args.args[0])
        self.assertTrue(all(len(call.args[0]) <= 1900 for call in inter.followup.send.call_args_list))

    async def test_menu_owner_guild_and_reauthorization(self):
        cls,cog,inter = self.context()
        await cls.menu_entry(cog,inter)
        self.assertEqual(cog.authorized.await_count,2)
        view = inter.response.send_message.call_args.kwargs['view']
        button = next(b for b in view.children if b.label == '成員／觀測基線')
        other = NS(user=NS(id=2),guild_id=1,response=NS(send_message=AsyncMock()))
        await button.callback(other)
        self.assertIn('自己的',other.response.send_message.call_args.args[0])
        other.user.id = 1; other.guild_id = 2
        await button.callback(other)
        self.assertIn('自己的',other.response.send_message.call_args.args[0])
        with patch('features.growth_baseline.enumerate_members',AsyncMock(return_value=snapshot())), \
                patch('features.growth_baseline.baseline',return_value={}), \
                patch('features.growth_baseline.render',return_value='button aggregate'):
            await button.callback(inter)
        self.assertEqual(inter.followup.send.call_args.args, ('button aggregate',))
        cog.authorized = AsyncMock(side_effect=[True,False])
        await cls.menu_entry(cog,inter)
        self.assertNotIn('view',inter.response.send_message.call_args.kwargs)

    async def test_current_session_scope_is_not_historical_attendance(self):
        cls,cog,inter = self.context()
        del cog.baseline_scope
        sessions = {'10':dict(id='n',message=2), '11':dict(id='w'),
                    '12':dict(id='u',plan_id='bad'), '13':dict(id='end',ended=1),
                    '14':dict(id='afk',message=3), '15':dict(id='missing',message=3)}
        afk = NS(id=14)
        guild = NS(id=1,afk_channel=afk,get_channel=lambda uid: None if uid==15 else afk if uid==14 else NS(id=uid))
        cog.bot = NS(get_cog=lambda name: NS(state={'sessions':sessions}) if name=='SquadCards' else NS(book=NS(get=lambda _:None)))
        r = cls.baseline_scope(cog,guild,100)
        self.assertEqual(r['counts'],dict(natural=1,waiting=1,unknown=1,ended=1,afk=1,channel_unavailable=1))
        self.assertEqual(r['historical_reason'],'historical_reason_not_recorded')
        self.assertNotIn('members',r)
