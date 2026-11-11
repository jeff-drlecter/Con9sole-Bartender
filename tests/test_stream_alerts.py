import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.twitch_alerts import AlertStore, normalize_login, transition
from cogs.stream_alerts import StreamAlerts, StreamAdmin, StreamPanel, TwitchAPI, authorized

STREAM = {'id': 'one', 'user_login': 'alice', 'user_name': 'Alice', 'user_id': '42',
          'started_at': '2026-11-11T18:00:00Z', 'title': 'Test', 'game_name': 'Game'}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.store = AlertStore(self.path, json.dumps([{'login': 'Alice', 'group': 'member'},
                                                     {'login': 'Bob', 'group': 'partner'}]))

    def test_roster_and_disabled_delivery_survive_restart(self):
        self.assertFalse(self.store.state['enabled'])
        self.store.state['partner_minutes'] = 60
        self.store.save()
        restarted = AlertStore(self.path, 'invalid bootstrap ignored for existing store')
        self.assertEqual(set(restarted.state['entries']), {'alice', 'bob'})
        self.assertEqual(restarted.state['partner_minutes'], 60)

    def test_separate_cadence_never_treats_skipped_partners_as_offline(self):
        for e in self.store.state['entries'].values():
            e['last_check'] = 100
        self.assertEqual(self.store.due(400), ['alice'])
        self.assertEqual(self.store.due(1900), ['alice', 'bob'])
        self.store.state['entries']['bob']['enabled'] = False
        self.assertEqual(self.store.due(99999), ['alice'])

    def test_baseline_then_live_then_same_session_then_offline(self):
        e = self.store.state['entries']['alice']
        self.assertEqual(transition(e, STREAM), 'baseline')
        e.update(initialized=True, stream_id='one')
        self.assertEqual(transition(e, STREAM), 'unchanged')
        self.assertEqual(transition(e, None), 'offline')
        self.assertEqual(transition(e, {**STREAM, 'id': 'two'}), 'live')
        e['pending'] = {'stream': STREAM}
        self.assertEqual(transition(e, None), 'pending')

    def test_duplicate_and_url_validation(self):
        self.assertEqual(normalize_login('https://www.twitch.tv/Alice/'), 'alice')
        for value in ('alice?x=1', '<@123>', 'https://evil.example/alice'):
            with self.assertRaises(ValueError):
                normalize_login(value)
        with self.assertRaises(ValueError):
            self.store.add('ALICE', 'partner')

    def test_corrupt_state_fails_closed(self):
        self.path.write_bytes(b'not sqlite')
        with self.assertRaises(Exception):
            AlertStore(self.path)


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cog = StreamAlerts(SimpleNamespace())
        self.cog.store = AlertStore(Path(self.tmp.name) / 'state.sqlite3', '[{"login":"alice","group":"member"}]')
        self.cog.api = SimpleNamespace(requests=1, streams=AsyncMock(return_value={}))
        self.cog.channel = lambda group: None
        self.cog.store.state['enabled'] = True

    async def tick(self):
        await self.cog.poll.coro(self.cog)

    async def test_initial_live_is_silent_and_repeated_poll_does_not_post(self):
        self.cog.api.streams.return_value = {'alice': STREAM}
        self.cog.send_live = AsyncMock()
        self.cog.end_card = AsyncMock()
        await self.tick()
        e = self.cog.store.state['entries']['alice']
        e['last_check'] = 0
        await self.tick()
        self.cog.send_live.assert_not_awaited()
        self.assertEqual(e['stream_id'], 'one')

    async def test_api_failure_never_changes_live_state(self):
        e = self.cog.store.state['entries']['alice']
        e.update(initialized=True, stream_id='one')
        self.cog.api.streams.side_effect = RuntimeError('API down')
        self.cog.end_card = AsyncMock()
        with patch('cogs.stream_alerts.asyncio.sleep', new=AsyncMock()):
            await self.tick()
        self.cog.end_card.assert_not_awaited()
        self.assertEqual(e['stream_id'], 'one')
        self.assertEqual(e['last_check'], 0)

    async def test_failed_send_preserves_pending_for_restart_and_waits_cadence(self):
        e = self.cog.store.state['entries']['alice']
        e['initialized'] = True
        self.cog.api.streams.return_value = {'alice': STREAM}
        async def fail(*args):
            e['pending'] = {'stream': STREAM, 'channel': 123, 'reserved_at': 1}
            raise RuntimeError('network')
        self.cog.send_live = fail
        await self.tick()
        restarted = AlertStore(self.cog.store.path)
        self.assertEqual(restarted.state['entries']['alice']['pending']['stream']['id'], 'one')
        self.assertFalse(self.cog.store.due(__import__('time').time()))

    async def test_stream_request_is_explicitly_bounded_and_malformed_fails(self):
        api = TwitchAPI(None, 'client', 'secret')
        api.get = AsyncMock(return_value={'data': [STREAM]})
        self.assertEqual(await api.streams(['alice']), {'alice': STREAM})
        self.assertIn(('first', '100'), api.get.await_args.args[1])
        api.get.return_value = {'data': [{}]}
        with self.assertRaises(RuntimeError):
            await api.streams(['alice'])
        api.get.side_effect = [{'data': [STREAM], 'pagination': {'cursor': 'next'}}, {'data': []}]
        self.assertEqual(await api.streams(['alice']), {'alice': STREAM})
        self.assertIn(('after', 'next'), api.get.await_args.args[1])

    async def test_incomplete_or_looping_pagination_never_returns_partial_live_map(self):
        api = TwitchAPI(None, 'client', 'secret')
        api.get = AsyncMock(side_effect=[{'data': [STREAM], 'pagination': {'cursor': 'next'}},
                                        RuntimeError('page two failed')])
        with self.assertRaises(RuntimeError):
            await api.streams(['alice'])
        api.get = AsyncMock(return_value={'data': [STREAM], 'pagination': {'cursor': 'same'}})
        with self.assertRaises(RuntimeError):
            await api.streams(['alice'])

    async def test_token_cached_and_401_refresh_only_once(self):
        api = TwitchAPI(None, 'client', 'secret')
        api.request = AsyncMock(side_effect=[{'access_token': 'TOKEN', 'expires_in': 4000},
                                             {'client_id': 'client', 'expires_in': 4000}])
        self.assertEqual(await api.access_token(), 'TOKEN')
        self.assertEqual(await api.access_token(), 'TOKEN')
        self.assertEqual(api.request.await_count, 2)
        api.request = AsyncMock(side_effect=[RuntimeError('Twitch HTTP 401'),
            {'access_token': 'NEW', 'expires_in': 4000}, {'client_id': 'client'}, {'data': []}])
        self.assertEqual(await api.get('users', []), {'data': []})
        self.assertEqual(api.token, 'NEW')

    async def test_ui_rows_and_no_helper_authority(self):
        view = StreamAdmin(self.cog)
        self.assertLessEqual(len(view.children), 25)
        self.assertTrue(all(sum(x.row == row for x in view.children if not isinstance(x, __import__('discord').ui.Select)) <= 5 for row in range(5)))
        self.assertTrue(StreamPanel(self.cog).is_persistent())
        inter = SimpleNamespace(guild_id=123, user=SimpleNamespace(), response=SimpleNamespace(
            is_done=lambda:False, send_message=AsyncMock()))
        self.assertFalse(await authorized(inter))

    async def test_offline_card_has_no_live_image_and_reports_detection_time(self):
        embed, view = self.cog.card('alice', STREAM, ended=True)
        self.assertFalse(embed.image.url)
        self.assertIn('非精確結束時間', str(embed.to_dict()))
        self.assertEqual(len(view.children), 1)

    async def test_restart_recovers_existing_card_without_second_send(self):
        import discord
        channel = unittest.mock.MagicMock(spec=discord.TextChannel)
        channel.id = 123
        channel.guild = SimpleNamespace(id=__import__('config').GUILD_ID)
        channel.send = AsyncMock()
        message = SimpleNamespace(id=456)
        self.cog.bot = SimpleNamespace(get_channel=lambda _: channel)
        self.cog.recover_pending = AsyncMock(return_value=message)
        e = self.cog.store.state['entries']['alice']
        e['pending'] = {'stream': STREAM, 'channel': 123, 'reserved_at': 1}
        await self.cog.send_live('alice', e, STREAM)
        channel.send.assert_not_awaited()
        self.assertEqual(e['message_id'], 456)
        self.assertIsNone(e['pending'])

    async def test_ended_pending_session_is_not_posted_late(self):
        import discord
        channel = unittest.mock.MagicMock(spec=discord.TextChannel)
        channel.guild = SimpleNamespace(id=__import__('config').GUILD_ID)
        channel.send = AsyncMock()
        self.cog.bot = SimpleNamespace(get_channel=lambda _: channel)
        self.cog.recover_pending = AsyncMock(return_value=None)
        e = self.cog.store.state['entries']['alice']
        e['pending'] = {'stream': STREAM, 'channel': 123, 'reserved_at': 1}
        await self.cog.send_live('alice', e, None)
        channel.send.assert_not_awaited()
        self.assertIsNone(e['pending'])

    async def test_offline_edits_original_instead_of_sending(self):
        import discord
        channel = unittest.mock.MagicMock(spec=discord.TextChannel)
        channel.guild = SimpleNamespace(id=__import__('config').GUILD_ID)
        message = SimpleNamespace(edit=AsyncMock())
        channel.fetch_message = AsyncMock(return_value=message)
        channel.send = AsyncMock()
        self.cog.bot = SimpleNamespace(get_channel=lambda _: channel)
        self.cog.api.get = AsyncMock(return_value={'data': []})
        e = self.cog.store.state['entries']['alice']
        e.update(stream=STREAM, started_at=STREAM['started_at'], stream_id='one', message_id=456, message_channel=123)
        await self.cog.end_card('alice', e)
        message.edit.assert_awaited_once()
        channel.send.assert_not_awaited()
        self.assertIsNone(e['stream_id'])


if __name__ == '__main__':
    unittest.main()
