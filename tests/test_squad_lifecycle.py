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


if __name__ == '__main__':
    unittest.main()
