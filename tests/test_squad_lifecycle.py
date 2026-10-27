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
        channel = types.SimpleNamespace(id=10, category_id=20, members=members[:1])
        guild = types.SimpleNamespace(voice_channels=[channel], afk_channel=None)
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
        now[0] += 59
        await tick()
        self.assertEqual(calls, [])
        channel.members = []
        await tick()
        now[0] += 5
        channel.members = members[:]
        await tick()
        now[0] += 59
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
        guild = types.SimpleNamespace(voice_channels=channels, afk_channel=channels[2])
        calls = []
        async def render(channel, session, ended=False):
            calls.append((channel.id, session['destination'], ended))
            session['message'] = channel.id
        cog = types.SimpleNamespace(
            state={'settings': {'routes': {'20': 30, '21': 31, '22': 32}}, 'sessions': {}},
            bot=types.SimpleNamespace(get_guild=lambda _: guild), save=lambda: None, render=render)
        await namespace['reconcile'](cog)
        now[0] += 60
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
        cog = types.SimpleNamespace(state={'settings': {'category': 20, 'destination': 30}, 'sessions': {}},
                                    lock=asyncio.Lock(), save=lambda: None, last_error=None,
                                    tick=types.SimpleNamespace(get_task=lambda: None, is_running=lambda: True))
        inter = types.SimpleNamespace(guild=types.SimpleNamespace(me=object(), voice_channels=[]),
                                      response=types.SimpleNamespace(send_message=AsyncMock()))
        permissions = types.SimpleNamespace(view_channel=True, send_messages=True,
                                             embed_links=True, read_message_history=True)
        destination = types.SimpleNamespace(id=31, mention='<#31>', permissions_for=lambda _: permissions)
        await scope['squad_setup'](cog, inter, types.SimpleNamespace(id=21, name='2K'), destination)
        self.assertEqual(cog.state['settings']['routes'], {'20': 30, '21': 31})
        destination.id = 32
        await scope['squad_setup'](cog, inter, types.SimpleNamespace(id=21, name='2K'), destination)
        self.assertEqual(cog.state['settings']['routes'], {'20': 30, '21': 32})


    async def test_first_player_ping_only_on_initial_send(self):
        from unittest.mock import AsyncMock
        render_method = next(n for c in ast.parse(source.read_text()).body
                             if isinstance(c, ast.ClassDef) and c.name == 'SquadCards'
                             for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'render')
        class Mentions:
            def __init__(self, **kwargs):
                self.users = kwargs.get('users', [])
            @classmethod
            def none(cls):
                return cls()
        embeds = []
        def make_embed(**kwargs):
            embed = types.SimpleNamespace(**kwargs, fields=[], add_field=lambda **kw: embed.fields.append(kw))
            embeds.append(embed)
            return embed
        fake_discord = types.SimpleNamespace(
            utils=types.SimpleNamespace(escape_markdown=lambda s: s),
            Embed=make_embed,
            AllowedMentions=Mentions, Object=lambda **kw: types.SimpleNamespace(**kw),
            NotFound=type('NotFound', (Exception,), {}))
        scope = dict(discord=fake_discord, humans=namespace['humans'], CardView=lambda *a: None,
                     game_profile=lambda *a: '', GAME_LABELS={})
        exec(compile(ast.Module(body=[render_method], type_ignores=[]), str(source), 'exec'), scope)
        message = types.SimpleNamespace(id=99, content='<@1> prompt', edit=AsyncMock())
        destination = types.SimpleNamespace(send=AsyncMock(return_value=message),
                                             fetch_message=AsyncMock(return_value=message))
        cog = types.SimpleNamespace(bot=types.SimpleNamespace(get_channel=lambda _: destination),
                                    save=lambda: None)
        channel = types.SimpleNamespace(id=10, members=[
            types.SimpleNamespace(id=1, display_name='A', bot=False),
            types.SimpleNamespace(id=2, display_name='B', bot=False)])
        session = dict(destination=30, first_member=1, participants={'1': 'A', '2': 'B'},
                       started=1000, ended=2000)
        await scope['render'](cog, channel, session)
        sent = destination.send.call_args.kwargs
        self.assertEqual(sent['embed'].title, '🟢 開緊團 · 歡迎加入')
        self.assertIn('<@1>', sent['content'])
        self.assertNotIn('<@2>', sent['content'])
        self.assertEqual([u.id for u in sent['allowed_mentions'].users], [1])
        await scope['render'](cog, channel, session)
        self.assertEqual(destination.send.await_count, 1)
        self.assertEqual(message.edit.call_args.kwargs['allowed_mentions'].users, [])
        session['missing'] = 2
        await scope['render'](cog, channel, session)
        self.assertEqual(embeds[-1].title, '🙌 缺 2 人，一齊玩！')
        session['missing'] = 0
        await scope['render'](cog, channel, session)
        self.assertEqual(embeds[-1].title, '🟢 開緊團 · 歡迎加入')
        session['mode'] = 'Clubs Rush'
        await scope['render'](cog, channel, session)
        self.assertIn({'name': '🏟️ 模式', 'value': 'Clubs Rush', 'inline': False}, embeds[-1].fields)
        await scope['render'](cog, channel, session, ended=True)
        self.assertEqual(embeds[-1].title, '🏁 今晚收工，下次再戰！')
        self.assertIn({'name': '🏟️ 模式', 'value': 'Clubs Rush', 'inline': False}, embeds[-1].fields)
        self.assertTrue(any('16 分鐘' in f['name'] for f in embeds[-1].fields))
        self.assertIsNone(message.edit.call_args.kwargs['view'])
        self.assertIsNone(message.edit.call_args.kwargs['content'])


    async def test_edit_permissions_checked_on_button_and_submission(self):
        from unittest.mock import AsyncMock
        parsed = ast.parse(source.read_text())
        edit = next(n for c in parsed.body if isinstance(c, ast.ClassDef) and c.name == 'CardView'
                    for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'edit')
        submit = next(n for c in parsed.body if isinstance(c, ast.ClassDef) and c.name == 'Details'
                      for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'on_submit')
        scope = dict(humans=namespace['humans'],
                     is_admin_or_helper=lambda u: u.kind in ('admin', 'helper'),
                     Details=lambda *args: object(), RecruitmentChoices=lambda *args: object())
        exec(compile(ast.Module(body=[edit, submit], type_ignores=[]), str(source), 'exec'), scope)
        for kind, in_call, active, allowed in [
                ('admin', False, True, True), ('helper', False, True, True),
                ('player', True, True, True), ('player', False, True, False),
                ('admin', False, False, False), ('helper', False, False, False)]:
            with self.subTest(kind=kind, active=active, in_call=in_call):
                user = types.SimpleNamespace(kind=kind, bot=False)
                session = {}
                channel = types.SimpleNamespace(members=[user] if in_call else [])
                cog = types.SimpleNamespace(
                    state={'sessions': {'10': session} if active else {}},
                    bot=types.SimpleNamespace(get_channel=lambda _: channel),
                    lock=asyncio.Lock(), save=lambda: None, render=AsyncMock())
                view = types.SimpleNamespace(cog=cog, key='10', session=session,
                    game=types.SimpleNamespace(value='Game'), mode=types.SimpleNamespace(value='Custom mode'), missing=types.SimpleNamespace(value='2'))
                inter = types.SimpleNamespace(user=user,
                    response=types.SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock(),
                                                   defer=AsyncMock()),
                    followup=types.SimpleNamespace(send=AsyncMock()))
                await scope['edit'](view, inter)
                self.assertEqual(inter.response.send_message.call_args.kwargs.get('view') is not None, allowed)
                await scope['on_submit'](view, inter)
                self.assertEqual(cog.render.await_count, int(allowed))


    async def test_quick_counts_recheck_permissions_and_preserve_game(self):
        from unittest.mock import AsyncMock
        parsed = ast.parse(source.read_text())
        method = next(n for c in parsed.body if isinstance(c, ast.ClassDef) and c.name == 'RecruitmentChoices'
                      for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'set_count')
        scope = dict(humans=namespace['humans'], is_admin_or_helper=lambda u: u.kind in ('admin', 'helper'))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
        for kind, in_call, active, allowed in [
                ('admin', False, True, True), ('helper', False, True, True),
                ('player', True, True, True), ('player', False, True, False),
                ('player', False, False, False), ('admin', False, False, False)]:
            for count in (1, 2, 3, None):
                with self.subTest(kind=kind, active=active, count=count):
                    user = types.SimpleNamespace(kind=kind, bot=False)
                    session = {'game': 'FC', 'missing': 9}
                    channel = types.SimpleNamespace(members=[user] if in_call else [])
                    cog = types.SimpleNamespace(
                        state={'sessions': {'10': session} if active else {}},
                        bot=types.SimpleNamespace(get_channel=lambda _: channel),
                        lock=asyncio.Lock(), save=lambda: None, render=AsyncMock())
                    view = types.SimpleNamespace(cog=cog, key='10', session=session)
                    inter = types.SimpleNamespace(user=user,
                        response=types.SimpleNamespace(defer=AsyncMock()),
                        followup=types.SimpleNamespace(send=AsyncMock()))
                    await scope['set_count'](view, inter, count)
                    self.assertEqual(cog.render.await_count, int(allowed))
                    self.assertEqual(session['missing'], count if allowed else 9)
                    self.assertEqual(session['game'], 'FC')


    async def test_mode_selection_permissions_clear_and_stale_profile(self):
        from unittest.mock import AsyncMock
        parsed = ast.parse(source.read_text())
        definitions = [n for n in parsed.body if
                       isinstance(n, ast.FunctionDef) and n.name == 'game_profile' or
                       isinstance(n, ast.Assign) and any(isinstance(a, ast.Name) and a.id in
                       ('GAME_LABELS', 'MODE_PRESETS') for a in n.targets)]
        scope = dict(humans=namespace['humans'], is_admin_or_helper=lambda u: u.kind in ('admin', 'helper'))
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), scope)
        method = next(n for c in parsed.body if isinstance(c, ast.ClassDef) and c.name == 'ModePicker'
                      for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'callback')
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
        self.assertNotIn('Crew HQ', scope['MODE_PRESETS']['2k'])
        self.assertIn('Crew HQ', scope['MODE_PRESETS']['2k27'])
        for kind, in_call, active, stale, allowed in [
                ('admin', False, True, False, True), ('helper', False, True, False, True),
                ('player', True, True, False, True), ('player', False, True, False, False),
                ('admin', False, False, False, False), ('admin', False, True, True, False)]:
            for selected in ('Clubs Rush', '__none__'):
                with self.subTest(kind=kind, active=active, stale=stale, selected=selected):
                    user = types.SimpleNamespace(kind=kind, bot=False)
                    session = {'mode': 'Clubs 球會', 'profile': '2k27' if stale else 'fc', 'missing': 2}
                    channel = types.SimpleNamespace(members=[user] if in_call else [])
                    cog = types.SimpleNamespace(state={'sessions': {'10': session} if active else {}},
                        bot=types.SimpleNamespace(get_channel=lambda _: channel),
                        lock=asyncio.Lock(), save=lambda: None, render=AsyncMock())
                    view = types.SimpleNamespace(cog=cog, key='10', session=session, profile='fc', values=[selected])
                    inter = types.SimpleNamespace(user=user,
                        response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                        followup=types.SimpleNamespace(send=AsyncMock()))
                    await scope['callback'](view, inter)
                    self.assertEqual(cog.render.await_count, int(allowed))
                    self.assertEqual(session['mode'], ('' if selected == '__none__' else selected) if allowed else 'Clubs 球會')
                    self.assertEqual(session['missing'], 2)


    async def test_discord_menu_layout_and_option_callbacks(self):
        try:
            import discord
        except ImportError:
            self.skipTest('discord.py is installed by CI')
        parsed = ast.parse(source.read_text())
        names = {'game_profile', 'ModePicker', 'GamePicker', 'RecruitmentChoices'}
        nodes = [n for n in parsed.body if
                 isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names or
                 isinstance(n, ast.Assign) and any(isinstance(a, ast.Name) and a.id in
                 ('GAME_LABELS', 'MODE_PRESETS') for a in n.targets)]
        scope = dict(discord=discord)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        channel = types.SimpleNamespace(category=types.SimpleNamespace(name='NBA 2K'))
        cog = types.SimpleNamespace(bot=types.SimpleNamespace(get_channel=lambda _: channel))
        for profile in ('fc', '2k', '2k27', 'other'):
            view = scope['RecruitmentChoices'](cog, '10', {'profile': profile})
            self.assertEqual(len(view.children), 7)
            self.assertEqual([item.row for item in view.children], [0, 1, 2, 2, 2, 2, 2])
            self.assertEqual(len(view.children[1].options),
                             len(scope['MODE_PRESETS'].get(profile, ())) + 2)
            chosen = []
            async def capture(interaction, value):
                chosen.append(value)
            view.set_count = capture
            for button in view.children[2:6]:
                await button.callback(None)
            self.assertEqual(chosen, [1, 2, 3, None])
            view.stop()

if __name__ == '__main__':
    unittest.main()
