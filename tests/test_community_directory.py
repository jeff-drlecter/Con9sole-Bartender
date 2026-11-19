"""Synthetic offline interactions through real command callbacks and permissions."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.app_commands.namespace import ResolveKey
import config
from cogs.community_directory import CommunityDirectory
from features.community_directory import Directory, DirectoryError, DirectoryUnavailable


def member(uid=100, *, verified=False, admin=False, manage=False, helper=False, bot=False):
    result = Mock(spec=discord.Member)
    result.id, result.bot = uid, bot
    result.roles = ([SimpleNamespace(id=config.VERIFIED_ROLE_ID, name='Verified')] if verified else [])
    if helper:
        result.roles.append(SimpleNamespace(id=999, name=config.HELPER_ROLE_NAMES[0]))
    result.guild_permissions = SimpleNamespace(administrator=admin, manage_guild=manage)
    return result


def http_error(cls=discord.HTTPException):
    return cls(SimpleNamespace(status=404 if cls is discord.NotFound else 503, reason='synthetic'), 'synthetic')


class DirectoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'directory.json'
        self.actor = member(admin=True)
        self.contact = member(200)
        self.fresh_guild = SimpleNamespace(fetch_member=AsyncMock(side_effect=lambda uid: self.actor))
        self.bot = SimpleNamespace(fetch_guild=AsyncMock(return_value=self.fresh_guild))
        self.cog = CommunityDirectory(self.bot)
        self.cog.directory = Directory(self.path, config.GUILD_ID)

    def interaction(self, *, guild_id=None):
        response = SimpleNamespace(is_done=Mock(return_value=False), send_message=AsyncMock(), send_modal=AsyncMock())
        async def defer(**kwargs):
            if kwargs:
                self.assertTrue(kwargs['ephemeral'])
            response.is_done.return_value = True
        response.defer = AsyncMock(side_effect=defer)
        return SimpleNamespace(guild_id=config.GUILD_ID if guild_id is None else guild_id,
                               guild=SimpleNamespace(fetch_member=AsyncMock(return_value=self.contact)),
                               user=member(admin=True), response=response, edit_original_response=AsyncMock(),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def call(self, command, interaction=None, **kwargs):
        inter = interaction or self.interaction()
        try:
            await getattr(CommunityDirectory, command).callback(self.cog, inter, **kwargs)
        except (DirectoryError, DirectoryUnavailable) as exc:
            await self.cog.cog_app_command_error(inter, exc)
        for send in [inter.response.send_message, inter.followup.send]:
            for call in send.call_args_list:
                self.assertTrue(call.kwargs['ephemeral'])
                self.assertEqual(call.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        return inter

    async def create(self, key='team-a', name='Team A', **kwargs):
        return await self.call('create', key=key, name=name, game='Example', pic=discord.Object(id=200), **kwargs)

    async def test_shared_pic_handover_restart_clear_archive_restore(self):
        await self.create(notes='Shared public description')
        await self.create('team-b', 'Team B')
        self.assertEqual([c['pic_id'] for c in self.cog.directory.cards()], [200, 200])
        self.contact = member(300)
        await self.call('edit', key='team-a', pic=discord.Object(id=300), clear_notes=True)
        self.cog.directory = Directory(self.path, config.GUILD_ID)
        self.assertEqual(self.cog.directory.get('team-a')['pic_id'], 300)
        self.assertEqual(self.cog.directory.get('team-a')['notes'], '')
        self.assertEqual(self.cog.directory.get('team-b')['pic_id'], 200)
        await self.call('archive', key='team-a')
        self.assertEqual([c['key'] for c in self.cog.directory.cards()], ['team-b'])
        self.actor = member(verified=True)
        inter = await self.call('show', key='team-a')
        self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
        self.actor = member(manage=True)
        await self.call('restore', key='team-a')
        self.assertFalse(Directory(self.path, config.GUILD_ID).get('team-a')['archived'])

    async def test_real_role_boundaries_and_fresh_roles_each_operation(self):
        await self.create()
        for actor in [member(), member(200), member(bot=True, admin=True)]:
            self.actor = actor
            for command, kwargs in [('list_cards', {}), ('show', {'key': 'team-a'})]:
                inter = await self.call(command, **kwargs)
                self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
        for actor in [member(verified=True), member(200, verified=True)]:
            self.actor = actor
            inter = await self.call('list_cards')
            self.assertIn('embed', inter.followup.send.call_args.kwargs)
            before = self.path.read_bytes()
            for command, kwargs in [('create', dict(key='forbidden', name='Forbidden', game='Game', pic=discord.Object(id=200))),
                                    ('edit', dict(key='team-a', name='Changed')),
                                    ('archive', dict(key='team-a')), ('restore', dict(key='team-a')),
                                    ('list_cards', dict(archived=True))]:
                await self.call(command, **kwargs)
                self.assertEqual(self.path.read_bytes(), before)
        self.assertGreater(self.bot.fetch_guild.await_count, 10)
        self.actor = member(manage=True)
        await self.call('edit', key='team-a', name='Allowed')
        self.assertEqual(self.cog.directory.get('team-a')['name'], 'Allowed')
        inter = self.interaction(guild_id=1)
        count = self.bot.fetch_guild.await_count
        await self.call('list_cards', inter)
        self.assertEqual(self.bot.fetch_guild.await_count, count)

    async def test_helper_create_edit_pic_and_active_views_without_verified(self):
        for actor in [member(helper=True), member(helper=True, verified=True)]:
            self.actor = actor
            key = 'verified-helper' if actor.roles[0].name == 'Verified' else 'helper'
            await self.create(key, key, notes='Original')
            for command, kwargs in [('list_cards', {}), ('show', dict(key=key))]:
                inter = await self.call(command, **kwargs)
                self.assertIn('embed', inter.followup.send.call_args.kwargs)
            self.contact = member(300)
            await self.call('edit', key=key, name=key + ' edited', game='New game',
                            pic=discord.Object(id=300), notes='Updated', status='closed')
            card = Directory(self.path, config.GUILD_ID).get(key)
            self.assertEqual((card['name'], card['game'], card['pic_id'], card['notes'], card['status']),
                             (key + ' edited', 'New game', 300, 'Updated', 'closed'))
            await self.call('edit', key=key, clear_notes=True)
            self.assertEqual(self.cog.directory.get(key)['notes'], '')
        # The existing central Helper role-ID path also applies when its name changes.
        self.actor = member()
        self.actor.roles = [SimpleNamespace(id=777, name='Renamed role')]
        with patch('core.permissions.HELPER_ROLE_IDS', {777}):
            await self.create('role-id', 'Role ID')
        self.assertEqual(self.cog.directory.get('role-id')['name'], 'Role ID')

    async def test_helper_cannot_archive_restore_query_or_edit_archived(self):
        await self.create(notes='Archived content')
        self.actor = member(helper=True)
        before = self.path.read_bytes()
        await self.call('archive', key='team-a')
        self.assertEqual(self.path.read_bytes(), before)
        self.actor = member(admin=True)
        await self.call('archive', key='team-a')
        before = self.path.read_bytes()
        for actor in [member(helper=True), member(helper=True, verified=True), member(200)]:
            self.actor = actor
            for command, kwargs in [('restore', dict(key='team-a')),
                                    ('list_cards', dict(archived=True)), ('show', dict(key='team-a')),
                                    ('edit', dict(key='team-a', name='Forbidden', pic=discord.Object(id=300)))]:
                inter = await self.call(command, **kwargs)
                self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
                inter.guild.fetch_member.assert_not_awaited()
                self.assertEqual(self.path.read_bytes(), before)
        self.actor = member(manage=True)
        inter = await self.call('show', key='team-a')
        self.assertIn('embed', inter.followup.send.call_args.kwargs)
        inter = await self.call('list_cards', archived=True)
        self.assertEqual(len(inter.followup.send.call_args.kwargs['embed'].fields), 1)
        await self.call('edit', key='team-a', name='Admin repaired')
        await self.call('restore', key='team-a')
        self.assertEqual(self.cog.directory.get('team-a')['name'], 'Admin repaired')
        self.assertFalse(self.cog.directory.get('team-a')['archived'])

    async def test_helper_revocation_and_pic_only_cannot_write(self):
        await self.create()
        before = self.path.read_bytes()
        for command, kwargs in [('create', dict(key='new', name='New', game='Game', pic=discord.Object(id=200))),
                                ('edit', dict(key='team-a', pic=discord.Object(id=300)))]:
            self.fresh_guild.fetch_member.side_effect = [member(helper=True), member(verified=True)]
            await self.call(command, **kwargs)
            self.assertEqual(self.path.read_bytes(), before)
            self.fresh_guild.fetch_member.side_effect = lambda uid: member(200)
            await self.call(command, **kwargs)
            self.assertEqual(self.path.read_bytes(), before)
        # A stale interaction Helper role must not override REST revocation.
        inter = self.interaction()
        inter.user = member(helper=True)
        self.fresh_guild.fetch_member.side_effect = lambda uid: member(verified=True)
        await self.call('edit', inter, key='team-a', notes='Forbidden')
        self.assertEqual(self.path.read_bytes(), before)

    async def test_helper_edit_rechecks_archive_after_pic_and_final_authorization(self):
        await self.create()
        self.actor = member(helper=True)
        for stage in ['pic', 'final_auth']:
            self.cog.directory.save('team-a', archived=False)
            original = self.cog.directory.get('team-a')
            inter = self.interaction()
            if stage == 'pic':
                async def pic_lookup(uid):
                    self.cog.directory.save('team-a', archived=True)
                    return member(300)
                inter.guild.fetch_member.side_effect = pic_lookup
            else:
                calls = 0
                async def final_auth(uid):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        self.cog.directory.save('team-a', archived=True)
                    return self.actor
                self.fresh_guild.fetch_member.side_effect = final_auth
            await self.call('edit', inter, key='team-a', name='Must not save', pic=discord.Object(id=300))
            self.assertEqual(self.cog.directory.get('team-a'), dict(original, archived=True))
            self.assertNotIn('embed', inter.followup.send.call_args.kwargs)

    async def test_member_lookup_failures_and_revocation_do_not_write(self):
        await self.create()
        before = self.path.read_bytes()
        for err in [http_error(discord.NotFound), http_error()]:
            inter = self.interaction()
            inter.guild.fetch_member.side_effect = err
            await self.call('edit', inter, key='team-a', pic=discord.Object(id=300))
            self.assertEqual(self.path.read_bytes(), before)
        self.contact = member(300, bot=True)
        await self.call('edit', key='team-a', pic=discord.Object(id=300))
        self.assertEqual(self.path.read_bytes(), before)
        self.contact = member(300)
        self.fresh_guild.fetch_member.side_effect = [member(admin=True), member()]
        await self.call('edit', key='team-a', pic=discord.Object(id=300))
        self.assertEqual(self.path.read_bytes(), before)
        self.bot.fetch_guild.side_effect = http_error()
        await self.call('archive', key='team-a')
        self.assertEqual(self.path.read_bytes(), before)

    async def test_card_pic_link_no_ping_and_departure_never_deletes(self):
        await self.create(name='Team @everyone **A**', notes='Hello <@200> @here [label](https://example.com)')
        self.actor = member(verified=True)
        before = self.path.read_bytes()
        for err, text in [(None, '<@200>'), (http_error(discord.NotFound), '已離開'), (http_error(), '暫時無法確認')]:
            inter = self.interaction()
            inter.guild.fetch_member.side_effect = err
            await self.call('show', inter, key='team-a')
            embed = inter.followup.send.call_args.kwargs['embed']
            self.assertIn(text, embed.fields[-1].value)
            self.assertIn('<@200>', embed.fields[-1].value)
            self.assertNotIn('@everyone', embed.title)
            self.assertNotIn('<@200>', embed.description)
            self.assertEqual(self.path.read_bytes(), before)

    async def test_show_and_restore_reject_concurrent_change(self):
        await self.create()
        self.actor = member(verified=True)
        inter = self.interaction()
        async def archive_during_lookup(uid):
            self.cog.directory.save('team-a', archived=True)
            return self.contact
        inter.guild.fetch_member.side_effect = archive_during_lookup
        await self.call('show', inter, key='team-a')
        self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
        self.actor = member(admin=True)
        inter = self.interaction()
        async def handover_during_lookup(uid):
            self.cog.directory.save('team-a', pic_id=300)
            return self.contact
        inter.guild.fetch_member.side_effect = handover_during_lookup
        await self.call('restore', inter, key='team-a')
        self.assertTrue(self.cog.directory.get('team-a')['archived'])
        self.assertEqual(self.cog.directory.get('team-a')['pic_id'], 300)

    async def test_duplicate_names_ids_input_limits_and_pagination(self):
        await self.create()
        before = self.path.read_bytes()
        await self.create(name='Duplicate ID')
        await self.create('team-b', 'team a')
        await self.create('Bad Key', 'Bad Key')
        await self.create('team-b', 'B' * 81)
        await self.create('team-b', 'Bad\u202ename')
        await self.call('edit', key='team-a', notes='conflict', clear_notes=True)
        self.assertEqual(self.path.read_bytes(), before)
        for number in range(12):
            await self.create(f'group-{number}', f'Group {number}')
        inter = await self.call('list_cards', page=2)
        fields = inter.followup.send.call_args.kwargs['embed'].fields
        self.assertEqual(len(fields), 3)
        self.assertTrue(all('PIC：<@200>' in field.value for field in fields))
        inter.guild.fetch_member.assert_not_awaited()
        inter = await self.call('list_cards', page=3)
        self.assertNotIn('embed', inter.followup.send.call_args.kwargs)

    async def test_corrupt_incomplete_foreign_and_failed_atomic_state_preserved(self):
        await self.create()
        valid = self.path.read_bytes()
        incomplete = json.loads(valid)
        del incomplete['cards']['team-a']['notes']
        foreign = json.loads(valid)
        foreign['guild_id'] = 1
        for raw in [b'broken', b'{}', b'{"version":1,"version":2}', json.dumps(incomplete).encode(), json.dumps(foreign).encode()]:
            self.path.write_bytes(raw)
            await self.create('team-b', 'Team B')
            await self.call('list_cards')
            self.assertEqual(self.path.read_bytes(), raw)
        self.path.write_bytes(valid)
        with patch('core.json_storage.os.fsync', side_effect=OSError('synthetic failure')):
            await self.call('edit', key='team-a', name='Unsaved')
        self.assertEqual(self.path.read_bytes(), valid)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    async def click(self, view, label, interaction=None):
        inter = interaction or self.interaction()
        button = next(item for item in view.children if getattr(item, 'label', None) == label)
        if await view.interaction_check(inter):
            try:
                await button.callback(inter)
            except (DirectoryError, DirectoryUnavailable) as exc:
                await view.on_error(inter, exc, button)
        return inter

    async def submit(self, form, **fields):
        inter = self.interaction()
        resolved = {}
        payload = []
        for field, value in fields.items():
            item = getattr(form, field)
            data = {'custom_id': item.custom_id, 'type': item.type.value}
            if isinstance(item, discord.ui.UserSelect):
                data['values'] = [str(value.id)] if value is not None else []
                if value is not None:
                    resolved[ResolveKey(id=str(value.id), type=6)] = value
            elif isinstance(item, discord.ui.Select):
                data['values'] = [value]
            else:
                data['value'] = value
            payload.append({'type': 18, 'component': data})
        self.assertTrue(await form.interaction_check(inter))
        form._refresh(inter, payload, resolved)
        try:
            await form.on_submit(inter)
        except (DirectoryError, DirectoryUnavailable) as exc:
            await form.on_error(inter, exc)
        response = inter.followup.send.call_args or inter.response.send_message.call_args
        self.assertTrue(response.kwargs['ephemeral'])
        self.assertEqual(response.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        return inter

    async def test_both_slash_groups_bind_same_callbacks_and_keep_old_parameters(self):
        from discord.ext import commands
        guild = discord.Object(config.GUILD_ID)
        async with commands.Bot(command_prefix='!', intents=discord.Intents.none()) as bot:
            await bot.load_extension('cogs.community_directory')
            for phase in ['load', 'reload']:
                if phase == 'reload':
                    await bot.reload_extension('cogs.community_directory')
                en = bot.tree.get_command('community', guild=guild)
                zh = bot.tree.get_command('公會', guild=guild)
                self.assertIsNone(bot.tree.get_command('公會'))
                for chinese, english in [('列表', 'list'), ('查看', 'show'), ('建立', 'create'),
                                         ('編輯', 'edit'), ('封存', 'archive'), ('還原', 'restore')]:
                    self.assertIs(zh.get_command(chinese).callback, en.get_command(english).callback)
                    self.assertIs(zh.get_command(chinese).binding, bot.get_cog('CommunityDirectory'))
                    self.assertTrue(all(p.display_name == p.name for p in en.get_command(english).parameters))
                    self.assertTrue(all(p.display_name != p.name for p in zh.get_command(chinese).parameters))

    async def test_owner_private_selection_pagination_and_role_revocation(self):
        for index in range(12):
            await self.create(f'guild-{index:02}', f'Guild {index:02}')
        self.actor = member(verified=True)
        first = self.interaction()
        await self.cog.menu_entry(first)
        view = first.followup.send.call_args.kwargs['view']
        select = view.children[0]
        self.assertEqual(len(select.options), 10)
        self.assertFalse(any(getattr(item, 'label', '') == '建立公會卡' for item in view.children))
        stranger = self.interaction()
        stranger.user = member(999, verified=True)
        self.assertFalse(await view.interaction_check(stranger))
        self.assertTrue(stranger.response.send_message.call_args.kwargs['ephemeral'])
        page = await self.click(view, '下一頁')
        second = page.followup.send.call_args.kwargs['view']
        select = second.children[0]
        self.assertEqual([o.value for o in select.options], ['guild-10', 'guild-11'])
        select._values = ['guild-11']
        inter = self.interaction()
        await select.callback(inter)
        self.assertEqual(inter.followup.send.call_args.kwargs['embed'].title, 'Guild 11')
        self.actor = member()
        inter = self.interaction()
        await select.callback(inter)
        self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
        denied = await self.click(second, '上一頁')
        self.assertNotIn('embed', denied.followup.send.call_args.kwargs)

    async def test_helper_forms_then_admin_archive_restore_after_restart(self):
        self.actor = member(helper=True)
        entry = self.interaction()
        await self.cog.menu_entry(entry)
        directory = entry.followup.send.call_args.kwargs['view']
        launch = await self.click(directory, '建立公會卡')
        launch.response.defer.assert_not_awaited()
        form = launch.response.send_modal.call_args.args[0]
        self.assertEqual(len(form.to_dict()['components']), 5)
        self.assertTrue(form.pic.required)
        stranger = self.interaction()
        stranger.user = member(321, helper=True)
        self.assertFalse(await form.interaction_check(stranger))
        fields = dict(key='old-key', name='Adventure', game='Game', pic=self.contact, notes='Original')
        self.actor = member(verified=True)
        await self.submit(form, **fields)
        self.assertFalse(self.path.exists())
        self.actor = member(helper=True)
        created = await self.submit(form, **fields)
        card = await self.click(created.followup.send.call_args.kwargs['view'], '查看公會卡')
        view = card.followup.send.call_args.kwargs['view']
        self.assertEqual([item.label for item in view.children], ['返回目錄', '編輯公會／交接 PIC'])
        launch = await self.click(view, '編輯公會／交接 PIC')
        edit = launch.response.send_modal.call_args.args[0]
        self.assertEqual(len(edit.to_dict()['components']), 5)
        self.assertEqual(edit.name.default, 'Adventure')
        self.assertFalse(edit.pic.required)
        self.contact = member(301, bot=True)
        fields = dict(name='Renamed', game='New game', notes='', pic=self.contact, status='closed')
        await self.submit(edit, **fields)
        self.assertEqual(self.cog.directory.get('old-key')['name'], 'Adventure')
        self.contact = member(301)
        fields['pic'] = self.contact
        await self.submit(edit, **fields)
        self.cog = CommunityDirectory(self.bot)
        self.cog.directory = Directory(self.path, config.GUILD_ID)
        self.assertEqual(self.cog.directory.get('old-key'), dict(key='old-key', name='Renamed',
                         game='New game', notes='', pic_id=301, status='closed', archived=False))
        self.actor = member(admin=True)
        card = await self.call('show_zh', key='old-key')
        view = card.followup.send.call_args.kwargs['view']
        self.actor = member(helper=True)
        await self.click(view, '封存公會')
        self.assertFalse(self.cog.directory.get('old-key')['archived'])
        self.actor = member(admin=True)
        await self.click(view, '封存公會')
        self.assertTrue(self.cog.directory.get('old-key')['archived'])
        entry = await self.call('list_zh')
        archived = await self.click(entry.followup.send.call_args.kwargs['view'], '已封存公會')
        select = archived.followup.send.call_args.kwargs['view'].children[0]
        self.assertEqual([o.value for o in select.options], ['old-key'])
        select._values = ['old-key']
        card = self.interaction()
        await select.callback(card)
        view = card.followup.send.call_args.kwargs['view']
        self.contact = member(301, bot=True)
        await self.click(view, '還原公會')
        self.assertTrue(self.cog.directory.get('old-key')['archived'])
        self.contact = member(301)
        await self.click(view, '還原公會')
        self.assertFalse(self.cog.directory.get('old-key')['archived'])

    async def test_stale_form_never_overwrites_new_card_or_discloses_archived_fields(self):
        await self.create(notes='Before')
        card = await self.call('show', key='team-a')
        view = card.followup.send.call_args.kwargs['view']
        launch = await self.click(view, '編輯公會／交接 PIC')
        form = launch.response.send_modal.call_args.args[0]
        self.cog.directory.save('team-a', notes='Newer')
        await self.submit(form, name='Old', game='Example', notes='Before', pic=None, status='open')
        self.assertEqual(self.cog.directory.get('team-a')['notes'], 'Newer')
        self.cog.directory.save('team-a', archived=True)
        self.actor = member(helper=True)
        # Opening a modal never waits for REST or reads fields added after the viewer saw it.
        click = self.interaction()
        click.user = self.actor
        with patch.object(self.cog.directory, 'get', side_effect=AssertionError('must only use snapshot')):
            with patch.object(self.bot, 'fetch_guild', side_effect=AssertionError('modal must acknowledge first')):
                await self.click(view, '編輯公會／交接 PIC', click)
        old = click.response.send_modal.call_args.args[0]
        self.assertEqual(old.notes.default, 'Before')
        click.response.defer.assert_not_awaited()
        await self.submit(old, name='Old', game='Example', notes='Before', pic=None, status='open')
        self.assertEqual(self.cog.directory.get('team-a')['notes'], 'Newer')

        self.actor = member(admin=True)
        archived = await self.call('show', key='team-a')
        archived_view = archived.followup.send.call_args.kwargs['view']
        for actor in [member(helper=True), member(verified=True), member(admin=True, bot=True)]:
            click = self.interaction()
            click.user = actor
            await self.click(archived_view, '編輯公會／交接 PIC', click)
            click.response.send_modal.assert_not_awaited()
            self.assertTrue(click.response.send_message.call_args.kwargs['ephemeral'])
        for click in [self.interaction(guild_id=1), self.interaction()]:
            if click.guild_id == config.GUILD_ID:
                click.user = member(verified=True)
            await self.click(view, '編輯公會／交接 PIC', click)
            click.response.send_modal.assert_not_awaited()
            self.assertTrue(click.response.send_message.call_args.kwargs['ephemeral'])

    async def test_directory_navigation_replaces_only_own_ephemeral_component_source(self):
        for index in range(11):
            await self.create(f'guild-{index:02}', f'Guild {index:02}')
        self.actor = member(verified=True)
        first = await self.call('list_cards')
        view = first.followup.send.call_args.kwargs['view']

        def component(*, ephemeral=True, owner=100):
            inter = self.interaction()
            inter.type = discord.InteractionType.component
            inter.message = SimpleNamespace(flags=SimpleNamespace(ephemeral=ephemeral),
                                            interaction_metadata=SimpleNamespace(user=member(owner)))
            return inter

        page = await self.click(view, '下一頁', component())
        page.response.defer.assert_awaited_once_with()
        page.followup.send.assert_not_awaited()
        edit = page.edit_original_response.call_args.kwargs
        self.assertIsNone(edit['content'])
        self.assertEqual(edit['allowed_mentions'].to_dict(), {'parse': []})
        select = edit['view'].children[0]
        self.assertEqual([o.value for o in select.options], ['guild-10'])
        select._values = ['guild-10']
        card = component()
        await select.callback(card)
        edit = card.edit_original_response.call_args.kwargs
        self.assertEqual(edit['embed'].title, 'Guild 10')
        back = await self.click(edit['view'], '返回目錄', component())
        self.assertEqual(back.edit_original_response.call_args.kwargs['embed'].title, '公會目錄')

        wrong_type = component()
        wrong_type.type = discord.InteractionType.application_command
        for inter in [component(ephemeral=False), component(ephemeral=None), component(owner=999),
                      self.interaction(), wrong_type]:
            await self.click(view, '下一頁', inter)
            inter.edit_original_response.assert_not_awaited()
            inter.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
            self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])

        # A slash or registry invocation never claims a GUI source to edit.
        slash = component()
        await self.call('list_zh', slash)
        slash.edit_original_response.assert_not_awaited()
        self.assertTrue(slash.followup.send.call_args.kwargs['ephemeral'])
        self.actor = member()
        denied = await self.click(view, '下一頁', component())
        denied.edit_original_response.assert_not_awaited()
        self.assertNotIn('embed', denied.followup.send.call_args.kwargs)
        self.assertTrue(denied.followup.send.call_args.kwargs['ephemeral'])

        menu = SimpleNamespace(open_main_menu=AsyncMock())
        self.bot.get_cog = Mock(return_value=menu)
        home = await self.click(view, '返回主選單', component())
        self.bot.get_cog.assert_called_once_with('Menu')
        menu.open_main_menu.assert_awaited_once_with(home)
