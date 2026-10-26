"""Exercise the production state machine without Discord/network dependencies."""
import ast
import asyncio
import pathlib
import types
import unittest
import uuid

source = pathlib.Path(__file__).resolve().parents[1] / 'cogs' / 'squad_cards.py'
tree = ast.parse(source.read_text())
method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'SquadCards'
              for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'reconcile')
namespace = dict(config=types.SimpleNamespace(GUILD_ID=1), uuid=uuid,
                 humans=lambda c: [m for m in c.members if not m.bot])
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_threshold_reset_live_roster_and_footprint(self):
        now = [1000]
        namespace['time'] = types.SimpleNamespace(time=lambda: now[0])
        members = [types.SimpleNamespace(id=i, display_name=str(i), bot=False) for i in (1, 2)]
        channel = types.SimpleNamespace(id=10, category_id=20, members=members[:])
        guild = types.SimpleNamespace(voice_channels=[channel], afk_channel_id=None)
        calls = []
        async def render(channel, session, ended=False):
            calls.append((ended, dict(session['participants'])))
            session['message'] = 99
        cog = types.SimpleNamespace(
            state={'settings': {'category': 20, 'destination': 30}, 'sessions': {}},
            bot=types.SimpleNamespace(get_guild=lambda _: guild), save=lambda: None, render=render)
        async def tick():
            await namespace['reconcile'](cog)
        await tick()
        now[0] += 599
        await tick()
        self.assertEqual(calls, [])
        channel.members = members[:1]
        await tick()
        now[0] += 5
        channel.members = members[:]
        await tick()
        now[0] += 599
        await tick()
        self.assertEqual(calls, [])
        now[0] += 1
        await tick()
        self.assertEqual(len(calls), 1)
        channel.members = members[:1]
        await tick()
        self.assertFalse(calls[-1][0])
        channel.members = []
        await tick()
        self.assertTrue(calls[-1][0])
        self.assertEqual(set(calls[-1][1]), {'1', '2'})
        self.assertFalse(cog.state['sessions'])
        await tick()
        self.assertEqual(len(calls), 3)


    async def test_multiple_games_route_independently(self):
        now = [1000]
        namespace['time'] = types.SimpleNamespace(time=lambda: now[0])
        members = [types.SimpleNamespace(id=i, display_name=str(i), bot=False) for i in (1, 2)]
        channels = [types.SimpleNamespace(id=i, category_id=category, members=members[:])
                    for i, category in ((10, 20), (11, 21), (12, 22))]
        guild = types.SimpleNamespace(voice_channels=channels, afk_channel_id=None)
        calls = []
        async def render(channel, session, ended=False):
            calls.append((channel.id, session['destination'], ended))
            session['message'] = channel.id
        cog = types.SimpleNamespace(
            state={'settings': {'routes': {'20': 30, '21': 31}}, 'sessions': {}},
            bot=types.SimpleNamespace(get_guild=lambda _: guild), save=lambda: None, render=render)
        await namespace['reconcile'](cog)
        now[0] += 600
        await namespace['reconcile'](cog)
        self.assertEqual(set(calls), {(10, 30, False), (11, 31, False)})
        channels[0].members = []
        await namespace['reconcile'](cog)
        self.assertIn((10, 30, True), calls)
        self.assertIn('11', cog.state['sessions'])
        self.assertNotIn('12', cog.state['sessions'])

    async def test_setup_preserves_other_games_and_migrates_legacy(self):
        from unittest.mock import AsyncMock
        setup_method = next(n for c in ast.parse(source.read_text()).body
                            if isinstance(c, ast.ClassDef) and c.name == 'SquadCards'
                            for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'squad_setup')
        setup_method.decorator_list = []
        for arg in setup_method.args.args:
            arg.annotation = None
        scope = {}
        exec(compile(ast.Module(body=[setup_method], type_ignores=[]), str(source), 'exec'), scope)
        cog = types.SimpleNamespace(state={'settings': {'category': 20, 'destination': 30}},
                                    lock=asyncio.Lock(), save=lambda: None)
        inter = types.SimpleNamespace(guild=types.SimpleNamespace(me=object()),
                                      response=types.SimpleNamespace(send_message=AsyncMock()))
        permissions = types.SimpleNamespace(view_channel=True, send_messages=True,
                                             embed_links=True, read_message_history=True)
        destination = types.SimpleNamespace(id=31, mention='<#31>', permissions_for=lambda _: permissions)
        await scope['squad_setup'](cog, inter, types.SimpleNamespace(id=21, name='2K'), destination)
        self.assertEqual(cog.state['settings']['routes'], {'20': 30, '21': 31})
        destination.id = 32
        await scope['squad_setup'](cog, inter, types.SimpleNamespace(id=21, name='2K'), destination)
        self.assertEqual(cog.state['settings']['routes'], {'20': 30, '21': 32})

if __name__ == '__main__':
    unittest.main()
