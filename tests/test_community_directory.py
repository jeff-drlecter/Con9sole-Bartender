"""Synthetic offline interactions through real command callbacks and permissions."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import config
from cogs.community_directory import CommunityDirectory
from features.community_directory import Directory, DirectoryError, DirectoryUnavailable


def member(uid=100, *, verified=False, admin=False, manage=False, helper=False, bot=False):
    result = Mock(spec=discord.Member)
    result.id, result.bot = uid, bot
    result.roles = ([SimpleNamespace(id=config.VERIFIED_ROLE_ID, name='Verified')] if verified else [])
    if helper:
        result.roles.append(SimpleNamespace(id=999, name='Helper'))
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
        response = SimpleNamespace(is_done=Mock(return_value=False), send_message=AsyncMock())
        async def defer(**kwargs):
            self.assertTrue(kwargs['ephemeral'])
            response.is_done.return_value = True
        response.defer = AsyncMock(side_effect=defer)
        return SimpleNamespace(guild_id=config.GUILD_ID if guild_id is None else guild_id,
                               guild=SimpleNamespace(fetch_member=AsyncMock(return_value=self.contact)),
                               user=member(admin=True), response=response,
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
        for actor in [member(), member(helper=True), member(bot=True, admin=True)]:
            self.actor = actor
            for command, kwargs in [('list_cards', {}), ('show', {'key': 'team-a'})]:
                inter = await self.call(command, **kwargs)
                self.assertNotIn('embed', inter.followup.send.call_args.kwargs)
        for actor in [member(verified=True), member(verified=True, helper=True)]:
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
