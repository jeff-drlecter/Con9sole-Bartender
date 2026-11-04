import tempfile
import types
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from core.json_storage import load_json_object
from cogs.squad_cards import SquadCards
from cogs import activity_reminder as reminders


class JsonReadProtection(unittest.TestCase):
    def test_read_failure_propagates_and_original_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            path.write_text('{"settings":{"route":123}}')
            original = path.read_bytes()
            with patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
                with self.assertLogs('con9sole-bartender.storage.json', level='ERROR'), self.assertRaises(PermissionError):
                    load_json_object(path, dict)
            self.assertEqual(path.read_bytes(), original)

    def test_backup_failure_never_returns_empty_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            path.write_text('{bad json')
            with patch.object(Path, 'replace', side_effect=OSError('disk error')):
                with self.assertLogs('con9sole-bartender.storage.json', level='ERROR'), self.assertRaises(OSError):
                    load_json_object(path, dict)
            self.assertEqual(path.read_text(), '{bad json')

    def test_invalid_encoding_is_backed_up_exactly(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'; original = b'\xff\xfe\x00broken'
            path.write_bytes(original)
            with self.assertLogs('con9sole-bartender.storage.json', level='ERROR'):
                self.assertEqual(load_json_object(path, dict), {})
            self.assertEqual(next(Path(d).glob('*.corrupt.*')).read_bytes(), original)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_card_does_not_block_healthy_card_and_still_retries(self):
        member = types.SimpleNamespace(id=1, display_name='Jeff', bot=False)
        channels = [types.SimpleNamespace(id=i,category_id=20,members=[member]) for i in (10,11)]
        guild = types.SimpleNamespace(voice_channels=channels,afk_channel=None)
        cog = object.__new__(SquadCards)
        cog.bot = types.SimpleNamespace(get_guild=lambda _:guild)
        cog.state = {'settings':{'routes':{'20':30}},'sessions':{
            str(i):{'message':99+i,'participants':{},'roster':[]} for i in (10,11)}}
        cog.save = MagicMock()
        async def render(channel, session, ended=False):
            if channel.id == 10:
                raise RuntimeError('destination unavailable')
        cog.render = AsyncMock(side_effect=render)
        with self.assertLogs('cogs.squad_cards',level='ERROR'):
            await cog.reconcile()
        self.assertEqual(cog.state['sessions']['10']['roster'],[])
        self.assertEqual(cog.state['sessions']['11']['roster'],[1])
        with self.assertLogs('cogs.squad_cards',level='ERROR'):
            await cog.reconcile()
        self.assertEqual(cog.render.await_count,3)

    async def test_late_pre_reminder_uses_remaining_time_and_only_target_role(self):
        cog = object.__new__(reminders.ActivityReminder)
        cog.sent_cache = {}; cog._save = MagicMock()
        event = datetime(2026,11,4,12,tzinfo=reminders.TZ)
        activity = reminders.Activity('a','game @everyone <@456>',1,2,[reminders.Schedule([2],'12:00')])
        role = types.SimpleNamespace(id=2,mention='<@&2>'); channel = types.SimpleNamespace(send=AsyncMock())
        with patch.object(reminders,'_now',return_value=event-timedelta(minutes=3)):
            await cog._send_if_needed(None,channel,role,activity,0,event,'pre')
        call = channel.send.call_args
        self.assertIn('仲有 **3 分鐘**',call.args[0])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict(),{'roles':[2],'parse':[]})
        cog.sent_cache = {}
        with patch.object(reminders,'_now',return_value=event):
            await cog._send_if_needed(None,channel,role,activity,0,event,'pre')
        self.assertEqual(channel.send.await_count,1)

    async def test_midnight_save_failure_does_not_stop_due_reminder(self):
        cog = object.__new__(reminders.ActivityReminder)
        now = datetime(2026,11,4,0,tzinfo=reminders.TZ)
        activity = reminders.Activity('a','game',1,2,[reminders.Schedule([2],'00:00')])
        channel = MagicMock(spec=discord.TextChannel)
        guild = types.SimpleNamespace(get_channel=lambda _:channel,get_role=lambda _:object())
        cog.bot = types.SimpleNamespace(is_ready=lambda:True,get_guild=lambda _:guild)
        cog.activities = {'a':activity}; cog._save = MagicMock(side_effect=OSError('disk busy'))
        cog._prune_cache = MagicMock(); cog._send_if_needed = AsyncMock()
        with patch.object(reminders,'_now',return_value=now), self.assertLogs(reminders.log,level='ERROR'):
            await reminders.ActivityReminder._tick.coro(cog)
        cog._send_if_needed.assert_awaited_once()
