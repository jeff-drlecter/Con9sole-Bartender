import asyncio
import json
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs import activity_reminder as ar, confession as cf, tempvc as tv
from cogs.teams import TeamState
from core.sqlite_storage import connect_sqlite
from features import team_storage as ts, menu_stats as stats


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_queue_serves_two_users_and_skips_user_who_left(self):
        cog = tv.TempVC(MagicMock())
        cog._find_owned_room = AsyncMock(return_value=None)
        started, release = asyncio.Event(), asyncio.Event()
        created = []
        async def create(member, channel):
            created.append(member.id)
            if member.id == 1:
                started.set()
                await release.wait()
            return object()
        cog._create_temp_vc_for_member = create
        hub = types.SimpleNamespace(id=99)
        members = [types.SimpleNamespace(id=i, bot=False, guild=types.SimpleNamespace(id=1),
                    voice=types.SimpleNamespace(channel=hub), move_to=AsyncMock(), send=AsyncMock()) for i in (1,2,3)]
        with patch.object(tv, 'mention_or_id', AsyncMock(return_value='m')), patch.object(tv, 'send_log', AsyncMock()), patch.object(tv, 'voice_arrow', return_value='join'), patch.object(tv, 'emb'), patch.object(tv, 'is_temp_vc_id', return_value=False), patch.object(tv, '_is_hub_channel', return_value=True):
            first = asyncio.create_task(cog.on_voice_state_update(members[0], types.SimpleNamespace(channel=None), types.SimpleNamespace(channel=hub)))
            await started.wait()
            rest = [asyncio.create_task(cog.on_voice_state_update(m, types.SimpleNamespace(channel=None), types.SimpleNamespace(channel=hub))) for m in members[1:]]
            await asyncio.sleep(0)
            self.assertEqual(created, [1])
            members[2].voice = None
            release.set()
            await asyncio.gather(first, *rest)
        self.assertEqual(created, [1,2])
        self.assertFalse(cog._creating_for_members)

    async def test_reminder_id_survives_removal_and_retry_is_bounded(self):
        cog = object.__new__(ar.ActivityReminder)
        cog.sent_cache = {}; cog._save = lambda: None
        first = datetime(2026,11,4,10,tzinfo=ar.TZ)
        a = ar.Activity('a','game',1,2,[ar.Schedule([2],'10:00'),ar.Schedule([2],'11:00')])
        channel = MagicMock(spec=discord.TextChannel); channel.send = AsyncMock()
        role = types.SimpleNamespace(mention='role')
        await cog._send_if_needed(None, channel, role, a, 0, first, 'start')
        a.schedules.pop(0)
        await cog._send_if_needed(None, channel, role, a, 0, first+timedelta(hours=1), 'start')
        self.assertEqual(channel.send.await_count,2)
        cog.sent_cache = {}; cog.activities = {'a':a}
        guild = types.SimpleNamespace(get_channel=lambda _:channel, get_role=lambda _:role)
        cog.bot = types.SimpleNamespace(is_ready=lambda:True,get_guild=lambda _:guild)
        channel.send.reset_mock(); channel.send.side_effect = [RuntimeError('offline'), None]
        for minute in (0,1,2,3):
            with patch.object(ar,'_now',return_value=first+timedelta(hours=1,minutes=minute)):
                await ar.ActivityReminder._tick.coro(cog)
        self.assertEqual(channel.send.await_count,2)
        cog.sent_cache = {}; channel.send.reset_mock()
        with patch.object(ar,'_now',return_value=first+timedelta(hours=1,minutes=3)):
            await ar.ActivityReminder._tick.coro(cog)
        channel.send.assert_not_awaited()

    async def test_legacy_reminders_backed_up_and_sent_cache_migrated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'reminders.json'; today=ar._now().date().isoformat()
            raw={'activities':[{'id':'a','name':'game','channel_id':1,'ping_role_id':2,'schedules':[{'weekdays':[2],'time_hhmm':'10:00'}]}], 'sent_cache':{f'a|0|{today}|start':'sent'}}
            p.write_text(json.dumps(raw)); original=p.read_bytes()
            cog=object.__new__(ar.ActivityReminder); cog.data_file=str(p); cog.data_dir=d
            cog._load()
            sid=cog.activities['a'].schedules[0].id
            self.assertIn(f'a|{sid}|{today}|start:10:00',cog.sent_cache)
            backups=list(Path(d).glob('*.pre-schedule-ids.*'))
            self.assertEqual(len(backups),1); self.assertEqual(backups[0].read_bytes(),original)
            cog._load(); self.assertEqual(cog.activities['a'].schedules[0].id,sid)
            self.assertEqual(len(list(Path(d).glob('*.pre-schedule-ids.*'))),1)

    async def test_bad_team_preserved_and_good_team_loads(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ts,'STATS_DB',Path(d)/'db'):
            ts.init_team_db(); ts.save_team(1,{'valid':'record'})
            with connect_sqlite(ts.STATS_DB) as conn:
                conn.execute('INSERT INTO team_cards VALUES (?,?)',(2,'{broken'))
            self.assertEqual(ts.load_teams(),[(1,{'valid':'record'})])
            with connect_sqlite(ts.STATS_DB) as conn:
                self.assertEqual(conn.execute('SELECT payload FROM team_cards_quarantine').fetchone()[0],'{broken')
            self.assertEqual(ts.load_teams(),[(1,{'valid':'record'})])

    async def test_invalid_team_fields_rejected(self):
        state=TeamState(1,2,'game',3,4,message_id=5)
        self.assertEqual(TeamState.restore(state.payload()).message_id,5)
        for key,value in [('created_at','bad'),('required',-1),('join_now','abc'),('message_id',None)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                TeamState.restore({**state.payload(),key:value})

    async def test_confession_acknowledged_and_duplicate_blocked(self):
        cog=cf.Confession(MagicMock()); started,release=asyncio.Event(),asyncio.Event()
        def interaction():
            return types.SimpleNamespace(user=types.SimpleNamespace(id=999),response=types.SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),followup=types.SimpleNamespace(send=AsyncMock()))
        i,j=interaction(),interaction()
        async def send(**kwargs):
            i.response.defer.assert_awaited_once(); started.set(); await release.wait()
        channel=types.SimpleNamespace(send=AsyncMock(side_effect=send))
        with patch.object(cog,'_target_channel',return_value=channel),patch.dict(cf.USER_CONFESSION_COOLDOWNS,{},clear=True):
            task=asyncio.create_task(cog.submit_confession(i,'hello'))
            await started.wait(); await cog.submit_confession(j,'again')
            channel.send.assert_awaited_once(); j.response.send_message.assert_awaited_once()
            release.set(); await task
            self.assertGreater(cf.get_retry_after(999),0)
            i.followup.send.assert_awaited_once()

    async def test_stats_work_is_serial_and_off_event_loop(self):
        with tempfile.TemporaryDirectory() as d, patch.object(stats,'STATS_DB',Path(d)/'stats'):
            with patch.object(stats,'_create_stats_schema',wraps=stats._create_stats_schema) as schema:
                stats.init_stats_db()
                await asyncio.gather(*(stats.record_usage('menu',i,1) for i in range(10)))
                self.assertEqual(await stats.run_stats(stats.get_total_usage,1),10)
                self.assertEqual(schema.call_count,1)
            worker=await stats.run_stats(threading.get_ident)
            self.assertNotEqual(worker,threading.get_ident())
            self.assertEqual(worker,await stats.run_stats(threading.get_ident))
