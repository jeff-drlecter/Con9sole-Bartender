import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import discord

from cogs.squad_cards import FootprintView, ParticipantPages, SquadCards
from features import squad_interest, squad_participants as store
from features.squad_subscription_views import SubscriptionView
from quick_bar_fakes import interaction


class ParticipantTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, 'STATS_DB', Path(self.temp.name) / 'stats.sqlite3')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def fixture(self, count=2):
        people = {uid: types.SimpleNamespace(id=uid, bot=False, display_name=f'Player {uid}') for uid in range(10, 10 + count)}
        guild = types.SimpleNamespace(id=1, get_member=people.get)
        permissions = discord.Permissions(view_channel=True)
        channel = types.SimpleNamespace(id=100, permissions_for=lambda _: permissions)
        inter = interaction(guild=guild, channel=channel)
        inter.client.user.id = 99
        inter.message.author.id = 99
        inter.message.embeds = []
        return inter, permissions

    def test_snapshot_is_durable_card_bound_and_never_overwritten_by_legacy(self):
        store.save(500, 1, 100, {'10': 'Old Name'})
        store.initialize.__wrapped__()
        store.preserve_legacy(500, 1, 100, ['wrong'])
        self.assertEqual(store.get(500, 1, 100), dict(names={'10': 'Old Name'}, legacy=[]))
        self.assertIsNone(store.get(500, 2, 100))
        self.assertIsNone(store.get(500, 1, 101))
        store.save(500, 1, 100, {'10': 'Updated', '11': 'B'})
        self.assertEqual(len(store.get(500, 1, 100)['names']), 2)

    def test_legacy_compaction_preserves_names_and_does_not_guess_ids(self):
        embed = discord.Embed(title='🏁 本局已結束，下次再戰！', description='🎮 Other Game\n👥 參與成員 · A、B\n⏱️ 1 小時')
        embed.add_field(name='一齊玩過', value='C @everyone')
        legacy = store.compact_legacy(embed)
        store.preserve_legacy(500, 1, 100, legacy)
        self.assertEqual(store.get(500, 1, 100), dict(names={}, legacy=['A、B', 'C @everyone']))
        self.assertNotIn('A、B', embed.description)
        self.assertEqual(len(embed.fields), 0)
        self.assertEqual(store.compact_legacy(embed), [])

    async def test_readonly_participants_are_private_and_do_not_subscribe(self):
        inter, _ = self.fixture()
        store.save(500, 1, 100, {'10': 'Old A', '11': 'B'})
        topic = squad_interest.topic(1, 'Other Game')
        view = FootprintView(None, topic)
        with patch.object(squad_interest, 'toggle') as toggle:
            await view.show_participants(inter)
        sent = inter.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertIn('<@10>', sent['embed'].description)
        self.assertEqual(sent['allowed_mentions'].to_dict(), {'parse': []})
        self.assertEqual({b.label for b in sent['view'].children}, {'上一頁', '下一頁'})
        self.assertTrue(view.is_persistent())
        toggle.assert_not_called()
        view.stop(); sent['view'].stop()

    async def test_wrong_author_or_missing_visibility_cannot_read_snapshot(self):
        inter, _ = self.fixture()
        store.save(500, 1, 100, {'10': 'A'})
        view = FootprintView(None, squad_interest.topic(1, 'Game'))
        inter.message.author.id = 98
        await view.show_participants(inter)
        inter.followup.send.assert_not_awaited()
        inter.message.author.id = 99
        inter.permissions.view_channel = False
        await view.show_participants(inter)
        inter.followup.send.assert_not_awaited()
        view.stop()

    async def test_private_pages_recheck_owner_guild_and_channel_visibility(self):
        inter, perms = self.fixture(200)
        pages = ParticipantPages(inter, dict(names={str(uid): 'A' for uid in range(10, 210)}, legacy=[]))
        self.assertGreater(len(pages.pages), 1)
        self.assertTrue(all(len(p) <= 3000 for p in pages.pages))
        other, _ = self.fixture()
        other.user.id = 20
        self.assertFalse(await pages.interaction_check(other))
        inter.guild_id = 2
        self.assertFalse(await pages.interaction_check(inter))
        inter.guild_id = 1
        perms.view_channel = False
        await pages.move(inter, 1)
        inter.response.edit_message.assert_not_awaited()
        self.assertEqual(pages.page, 0)
        pages.stop()

    async def test_participants_filter_departed_bots_and_hidden_members(self):
        inter, _ = self.fixture()
        hidden = types.SimpleNamespace(id=12, bot=False, display_name='Hidden')
        robot = types.SimpleNamespace(id=13, bot=True, display_name='Bot')
        people = {12: hidden, 13: robot, 10: types.SimpleNamespace(id=10, bot=False, display_name='@everyone')}
        inter.guild.get_member = people.get
        inter.channel.permissions_for = lambda m: discord.Permissions(view_channel=m.id != 12)
        pages = ParticipantPages(inter, dict(names={str(uid): 'Old' for uid in (10, 11, 12, 13)}, legacy=[]))
        text = pages.embed().description
        self.assertIn('<@10>', text)
        self.assertNotIn('@everyone', text)
        for uid in (11, 12, 13):
            self.assertNotIn(f'<@{uid}>', text)
        pages.stop()

    async def test_long_legacy_names_are_private_paginated_and_mentions_escaped(self):
        inter, _ = self.fixture()
        pages = ParticipantPages(inter, dict(names={}, legacy=['@everyone ' + 'A' * 9000]))
        self.assertGreater(len(pages.pages), 1)
        self.assertTrue(all(len(p) <= 3000 for p in pages.pages))
        self.assertNotIn('@everyone', ''.join(pages.pages))
        pages.stop()

    async def test_subscription_updates_replace_panel_and_no_empty_pagination(self):
        inter, _ = self.fixture()
        cog = types.SimpleNamespace(lock=asyncio.Lock(), menu_entry=AsyncMock())
        rows = [dict(id='game', label='Other Game', kind='once')]
        view = SubscriptionView(cog, 1, inter.user.id, rows)
        select = next(c for c in view.children if isinstance(c, discord.ui.Select))
        select._values = ['game']
        with patch('features.squad_subscription_views.run_stats', new=AsyncMock()):
            await select.callback(inter)
        cog.menu_entry.assert_awaited_once_with(inter, replace=True)
        self.assertFalse(any(b.label in {'上一頁', '下一頁'} for b in view.children if isinstance(b, discord.ui.Button)))
        self.assertEqual(len(view.embed().fields), 2)
        view.stop()

    async def test_menu_replacement_edits_instead_of_sending_new_message(self):
        inter, _ = self.fixture()
        cog = types.SimpleNamespace()
        with patch('cogs.squad_cards.config.GUILD_ID', 1), patch('cogs.squad_cards.run_stats', new=AsyncMock(return_value=[])):
            await SquadCards.menu_entry(cog, inter, replace=True)
        inter.edit_original_response.assert_awaited_once()
        inter.followup.send.assert_not_awaited()
        inter.edit_original_response.call_args.kwargs['view'].stop()

    async def test_legacy_save_failure_leaves_public_names_intact(self):
        inter, _ = self.fixture()
        inter.message.embeds = [discord.Embed(description='👥 參與成員 · A、B')]
        inter.channel.fetch_message = AsyncMock(return_value=inter.message)
        view = FootprintView(None, squad_interest.topic(1, 'Game'))
        with patch.object(squad_interest, 'STATS_DB', store.STATS_DB), patch.object(store, 'preserve_legacy', side_effect=OSError('disk full')):
            squad_interest.remember(view.topic)
            with self.assertRaises(OSError):
                await view.refresh(inter)
        inter.message.edit.assert_not_awaited()
        self.assertIn('A、B', inter.message.embeds[0].description)
        view.stop()
