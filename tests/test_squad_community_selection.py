"""Offline squad community interactions using the real directory authorization."""
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
from features.squad_community import (
    active_community, add_community_details, add_community_field, choose_community,
)
from test_community_directory import http_error, member


class SquadCommunityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'synthetic-directory.json'
        self.actor = member(verified=True)
        self.guild = SimpleNamespace(fetch_member=AsyncMock(side_effect=lambda uid: self.actor))
        self.bot = SimpleNamespace(fetch_guild=AsyncMock(return_value=self.guild), get_cog=Mock())
        self.cog = CommunityDirectory(self.bot)
        self.cog.directory = Directory(self.path, config.GUILD_ID)
        self.bot.get_cog.return_value = self.cog
        self.on_select = AsyncMock()

    def seed(self, count=1):
        cards = {f'guild-{i:03}': dict(key=f'guild-{i:03}', name=f'Guild {i:03}',
                 game=f'Game {i % 3}', pic_id=200, notes='Public synthetic notes',
                 status='closed' if i % 2 else 'open', archived=False) for i in range(count)}
        self.path.write_text(json.dumps(dict(version=1, guild_id=config.GUILD_ID, cards=cards)))

    def interaction(self, *, uid=100, guild_id=None, ephemeral=True, source_owner=100, done=False):
        response = SimpleNamespace(is_done=Mock(return_value=done), send_message=AsyncMock())

        async def defer(**kwargs):
            response.is_done.return_value = True

        response.defer = AsyncMock(side_effect=defer)
        return SimpleNamespace(user=member(uid, admin=True),
            guild_id=config.GUILD_ID if guild_id is None else guild_id,
            guild=SimpleNamespace(fetch_member=AsyncMock(return_value=member(200))),
            type=discord.InteractionType.component,
            message=SimpleNamespace(flags=SimpleNamespace(ephemeral=ephemeral),
                interaction_metadata=SimpleNamespace(user=SimpleNamespace(id=source_owner))),
            response=response, edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    def assert_private(self, interaction):
        for sender in [interaction.response.send_message, interaction.followup.send]:
            for call in sender.call_args_list:
                self.assertIs(call.kwargs['ephemeral'], True)
                self.assertEqual(call.kwargs['allowed_mentions'].to_dict(), {'parse': []})

    def result(self, interaction):
        call = (interaction.edit_original_response.call_args or interaction.followup.send.call_args
                or interaction.response.send_message.call_args)
        self.assertIsNotNone(call)
        self.assert_private(interaction)
        return call.kwargs

    async def picker(self, *, current_key=None, interaction=None):
        inter = interaction or self.interaction()
        await choose_community(inter, self.bot, self.on_select, current_key=current_key)
        return self.result(inter)['view']

    async def click(self, view, label=None, *, key=None, interaction=None):
        inter = interaction or self.interaction()
        if label is None:
            item = next(child for child in view.children if isinstance(child, discord.ui.Select))
            item._values = [key]
        else:
            item = next(child for child in view.children if getattr(child, 'label', None) == label)
        if await view.interaction_check(inter):
            try:
                await item.callback(inter)
            except (DirectoryError, DirectoryUnavailable) as error:
                await view.on_error(inter, error, item)
        self.assert_private(inter)
        return inter

    async def details(self, *, key='guild-000', interaction=None):
        view = discord.ui.View()
        add_community_details(view, self.bot, key, custom_id='synthetic:details', row=2)
        inter = interaction or self.interaction(ephemeral=False)
        await view.children[0].callback(inter)
        self.assert_private(inter)
        return inter

    async def test_optional_link_helpers_never_read_for_unlinked_squad(self):
        with patch.object(self.bot, 'get_cog', side_effect=AssertionError('unlinked')):
            self.assertIsNone(active_community(self.bot, None))
            self.assertIsNone(active_community(self.bot, '', strict=True))
            view = discord.ui.View()
            add_community_details(view, self.bot, None, custom_id='none')
            self.assertEqual(view.children, [])
        embed = discord.Embed(title='Ordinary squad')
        add_community_field(embed, None)
        self.assertEqual(embed.fields, [])

    async def test_active_link_degrades_safely_but_strict_distinguishes_unavailable(self):
        self.seed()
        self.assertEqual(active_community(self.bot, 'guild-000')['name'], 'Guild 000')
        for key in ['missing', 'invalid key']:
            self.assertIsNone(active_community(self.bot, key, strict=True))
        self.cog.directory.save('guild-000', archived=True)
        self.assertIsNone(active_community(self.bot, 'guild-000', strict=True))
        self.path.write_text('broken synthetic JSON')
        self.assertIsNone(active_community(self.bot, 'guild-000'))
        with self.assertRaises(DirectoryUnavailable):
            active_community(self.bot, 'guild-000', strict=True)
        self.bot.get_cog.return_value = None
        self.assertIsNone(active_community(self.bot, 'guild-000'))
        with self.assertRaises(DirectoryUnavailable):
            active_community(self.bot, 'guild-000', strict=True)

    async def test_public_field_only_displays_safe_name(self):
        self.seed()
        card = self.cog.directory.save('guild-000', name='**Team** @everyone <@200>')
        embed = discord.Embed()
        add_community_field(embed, card)
        self.assertEqual(len(embed.fields), 1)
        self.assertEqual(embed.fields[0].name, '公會')
        text = embed.fields[0].value
        self.assertIn(r'\*\*Team\*\*', text)
        self.assertNotIn('@everyone', text)
        self.assertNotIn('<@200>', text)
        self.assertNotIn('notes', text)
        self.assertNotIn('Game', text)
        card['archived'] = True
        add_community_field(embed, card)
        self.assertEqual(len(embed.fields), 1)

    async def test_all_500_cards_and_games_are_human_selectable_across_pages(self):
        self.seed(500)
        view = await self.picker(current_key='guild-499')
        found = []
        for page in range(20):
            select = view.children[0]
            self.assertEqual(len(select.options), 25)
            for option in select.options:
                self.assertEqual(option.label, 'Guild ' + option.value[-3:])
                self.assertEqual(option.description, f'Game {int(option.value[-3:]) % 3}')
                found.append(option.value)
            if page < 19:
                inter = await self.click(view, '下一頁')
                inter.response.defer.assert_awaited_once_with()
                view = self.result(inter)['view']
        self.assertEqual(found, [f'guild-{i:03}' for i in range(500)])
        self.assertEqual([option.value for option in view.children[0].options if option.default], ['guild-499'])
        last = await self.click(view, key='guild-499')
        last.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        last.edit_original_response.assert_not_awaited()
        self.on_select.assert_awaited_once_with(last, 'guild-499')

    async def test_active_closed_cards_allowed_archived_excluded_and_no_autoselection(self):
        self.seed(3)
        self.cog.directory.save('guild-000', archived=True)
        view = await self.picker(current_key='guild-000')
        options = view.children[0].options
        self.assertEqual([option.value for option in options], ['guild-001', 'guild-002'])
        self.assertFalse(any(option.default for option in options))
        self.on_select.assert_not_awaited()
        selected = await self.click(view, key='guild-001')
        self.on_select.assert_awaited_once_with(selected, 'guild-001')

    async def test_picker_always_starts_a_new_private_message(self):
        self.seed()
        for done in [False, True]:
            inter = self.interaction(done=done, ephemeral=False)
            await self.picker(interaction=inter)
            inter.edit_original_response.assert_not_awaited()
            self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])

    async def test_owner_binding_and_foreign_guild_fail_privately(self):
        self.seed(26)
        view = await self.picker()
        for label, key in [('下一頁', None), ('不選公會／移除公會', None), (None, 'guild-000')]:
            denied = await self.click(view, label, key=key, interaction=self.interaction(uid=999))
            self.assertNotIn('embed', self.result(denied))
            foreign = await self.click(view, label, key=key, interaction=self.interaction(guild_id=1))
            self.assertNotIn('embed', self.result(foreign))
        self.on_select.assert_not_awaited()

    async def test_roles_refetched_for_each_page_selection_and_removal(self):
        self.seed(26)
        view = await self.picker()
        for actor in [member(), member(admin=True, bot=True)]:
            self.actor = actor
            for label, key in [('下一頁', None), ('不選公會／移除公會', None), (None, 'guild-000')]:
                denied = await self.click(view, label, key=key)
                self.assertNotIn('embed', self.result(denied))
        self.on_select.assert_not_awaited()
        for actor in [member(verified=True), member(helper=True), member(admin=True), member(manage=True)]:
            self.actor = actor
            selected = await self.click(view, key='guild-000')
            self.on_select.assert_awaited_with(selected, 'guild-000')

    async def test_removal_and_empty_directory_keep_ordinary_squad_available(self):
        view = await self.picker(current_key='missing')
        self.assertFalse(any(isinstance(child, discord.ui.Select) for child in view.children))
        with patch.object(self.cog.directory, '_load', side_effect=AssertionError('clearing needs no directory read')):
            cleared = await self.click(view, '不選公會／移除公會')
        cleared.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.on_select.assert_awaited_once_with(cleared, None)

    async def test_selection_rechecks_active_after_authorization_and_rejects_forged_option(self):
        self.seed(26)
        view = await self.picker()
        denied = await self.click(view, key='guild-025')
        self.assertNotIn('embed', self.result(denied))

        async def archive_during_fetch(uid):
            self.cog.directory.save('guild-000', archived=True)
            return self.actor

        self.guild.fetch_member.side_effect = archive_during_fetch
        denied = await self.click(view, key='guild-000')
        self.assertNotIn('embed', self.result(denied))
        self.on_select.assert_not_awaited()

    async def test_unavailable_directory_and_http_failure_fail_privately(self):
        self.seed(26)
        view = await self.picker()
        self.path.write_text('corrupt')
        for label, key in [('下一頁', None), (None, 'guild-000')]:
            denied = await self.click(view, label, key=key)
            self.assertNotIn('embed', self.result(denied))
        inter = self.interaction()
        await choose_community(inter, self.bot, self.on_select)
        self.assertNotIn('embed', self.result(inter))
        self.seed(26)
        self.bot.fetch_guild.side_effect = http_error()
        for label, key in [('下一頁', None), ('不選公會／移除公會', None), (None, 'guild-000')]:
            denied = await self.click(view, label, key=key)
            self.assertNotIn('embed', self.result(denied))
        self.on_select.assert_not_awaited()

    async def test_details_use_private_directory_render_and_refresh_roles(self):
        self.seed()
        inter = await self.details()
        self.assertEqual(self.result(inter)['embed'].title, 'Guild 000')
        inter.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        inter.edit_original_response.assert_not_awaited()
        self.assertEqual(self.bot.fetch_guild.await_count, 2)
        self.actor = member()
        denied = await self.details()
        self.assertNotIn('embed', self.result(denied))
        self.actor = member(admin=True)
        denied = await self.details(interaction=self.interaction(guild_id=1))
        self.assertNotIn('embed', self.result(denied))

    async def test_details_never_reveal_archived_cards_even_to_admins(self):
        self.seed()
        self.actor = member(admin=True)
        self.cog.directory.save('guild-000', archived=True)
        denied = await self.details()
        self.assertNotIn('embed', self.result(denied))
        # Original directory route retains its intentional admin archive access.
        ordinary = self.interaction()
        await self.cog.render_card(ordinary, key='guild-000')
        self.assertIn('已封存', self.result(ordinary)['embed'].footer.text)

    async def test_details_close_archive_races_during_both_external_awaits(self):
        self.seed()
        self.actor = member(admin=True)

        async def archive_during_authorization(uid):
            self.cog.directory.save('guild-000', archived=True)
            return self.actor

        self.guild.fetch_member.side_effect = archive_during_authorization
        denied = await self.details()
        self.assertNotIn('embed', self.result(denied))
        self.cog.directory.save('guild-000', archived=False)
        self.guild.fetch_member.side_effect = lambda uid: self.actor
        inter = self.interaction()

        async def archive_during_pic(uid):
            self.cog.directory.save('guild-000', archived=True)
            return member(200)

        inter.guild.fetch_member.side_effect = archive_during_pic
        denied = await self.details(interaction=inter)
        self.assertNotIn('embed', self.result(denied))

    async def test_details_role_revocation_during_pic_lookup_and_missing_service(self):
        self.seed()
        inter = self.interaction()

        async def revoke_during_pic(uid):
            self.actor = member()
            return member(200)

        inter.guild.fetch_member.side_effect = revoke_during_pic
        denied = await self.details(interaction=inter)
        self.assertNotIn('embed', self.result(denied))
        self.bot.get_cog.return_value = None
        denied = await self.details()
        self.assertNotIn('embed', self.result(denied))
        denied = self.interaction()
        await choose_community(denied, self.bot, self.on_select)
        self.assertNotIn('embed', self.result(denied))

    async def test_pagination_never_edits_public_or_other_owners_source(self):
        self.seed(26)
        view = await self.picker()
        for inter in [self.interaction(ephemeral=False), self.interaction(source_owner=999)]:
            await self.click(view, '下一頁', interaction=inter)
            inter.edit_original_response.assert_not_awaited()
            inter.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
            self.assertIn('view', self.result(inter))
