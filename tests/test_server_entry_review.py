"""Exercise read-only entry, public/private wording and ended-plan access."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from cogs.member_entry import MemberEntryView
from cogs.squad_plans import SquadPlans, PlanView, card
from cogs.welcome_log import welcome_message
from core.secret_redaction import redact_credentials
from features.squad_plans import PlanBook
from features.language_preferences import language, localize_menu, ROLE_NAMES
from features.menu_embeds import build_quick_bar_embed


def channel(ident, name, writable=True, visible=True):
    value = MagicMock(spec=discord.TextChannel)
    value.id, value.name, value.category = ident, name, None
    perms = discord.Permissions(view_channel=visible, read_message_history=visible,
                                send_messages=writable, embed_links=True)
    value.permissions_for.return_value = perms
    return value


def interaction(source):
    return N(user=N(id=3, roles=[]), channel=source, channel_id=source.id, guild_id=config.GUILD_ID,
             response=N(send_message=AsyncMock(), defer=AsyncMock()), followup=N(send=AsyncMock()))


class ServerEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_guide_routes_only_to_accessible_writable_destinations(self):
        source = channel(1, '組隊與語音指南', writable=False)
        target = channel(2, 'fc-吹水組隊')
        hidden = channel(4, 'gta-吹水組隊', visible=False)
        read_only = channel(5, 'bf-吹水組隊', writable=False)
        i = interaction(source)
        i.guild = N(text_channels=[source, target, hidden, read_only], me=N(id=99))
        with patch('cogs.squad_plans.is_verified_member', return_value=True):
            await SquadPlans.menu_entry(N(), i)
        picker = i.response.send_message.await_args.kwargs['view']
        self.assertEqual([option.value for option in picker.children[0].options], ['2'])
        self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])
        target.send.assert_not_called()

    async def test_no_destination_provides_game_selection_instead_of_bypassing_permissions(self):
        source = channel(1, '組隊與語音指南', writable=False)
        i = interaction(source)
        i.guild = N(text_channels=[], me=N(id=99))
        with patch('cogs.squad_plans.is_verified_member', return_value=True):
            await SquadPlans.menu_entry(N(), i)
        self.assertIn('<id:customize>', i.response.send_message.await_args.args[0])
        self.assertNotIn('view', i.response.send_message.await_args.kwargs)

    async def test_ended_plan_roster_is_read_only_and_rechecks_source_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            book = PlanBook(Path(folder) / 'plans.json', clock=lambda: 100)
            p = book.create(guild=config.GUILD_ID, channel=2, owner=3, game='FC', mode='PS5／Clubs', start=200, party=1, capacity=3)
            book.publish(p['id'], 9)
            book.clock = lambda: 201
            book.expire()
            cog = N(book=book, lock=asyncio.Lock())
            i = interaction(channel(2, 'fc-吹水組隊', writable=False))
            i.message = N(id=9)
            view = PlanView(cog, book.get(p['id']))
            self.assertEqual([b.disabled for b in view.children], [True, True, False])
            with patch('cogs.squad_plans.is_verified_member', return_value=True):
                await view.handle(i, 'manage')
            self.assertIsNone(i.response.send_message.await_args.kwargs['view'])
            self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])
            self.assertEqual(book.get(p['id'])['status'], 'started')
            i.response.send_message.reset_mock()
            i.channel.permissions_for.return_value.view_channel = False
            with patch('cogs.squad_plans.is_verified_member', return_value=True):
                await view.handle(i, 'manage')
            self.assertNotIn('view', i.response.send_message.await_args.kwargs)

    async def test_public_entry_is_persistent_and_opens_private_personal_menu(self):
        view = MemberEntryView()
        self.assertTrue(view.is_persistent())
        self.assertEqual(len({b.custom_id for b in view.children}), 4)
        i = interaction(channel(2, 'bartender使用指南', writable=False))
        menu = N(open_main_menu=AsyncMock())
        i.client = N(get_cog=lambda name: menu if name == 'Menu' else None)
        await view.open(i, 'menu')
        menu.open_main_menu.assert_awaited_once_with(i)
        await view.open(i, 'games')
        self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])

    async def test_public_card_is_compact_and_unknown_language_is_neutral(self):
        p = dict(game='FC', mode='PS5／Clubs', start=200, party=1, members=[4], capacity=4, owner=3, status='open')
        embed = card(p)
        self.assertIn('尚欠 2 人', embed.description)
        self.assertIn('PS5／Clubs', embed.description)
        self.assertNotIn('<@4>', str(embed.to_dict()))
        member = N(id=3, mention='<@3>', guild=N(name='Con9sole'), roles=[])
        self.assertEqual(language(member), 'neutral')
        localized, _ = localize_menu(member, build_quick_bar_embed(member))
        self.assertNotIn('嘢', localized.description)
        neutral = welcome_message(member, '<#1>', '<@99>')
        member.roles = [N(name=ROLE_NAMES['hk'], managed=False, permissions=discord.Permissions.none())]
        self.assertEqual(welcome_message(member, '<#1>', '<@99>'), neutral)


class CredentialTests(unittest.TestCase):
    def test_audit_redacts_credentials_before_escaping_or_truncating(self):
        fake = 'oauth:' + 'a' * 30
        text = '{"twitch_oauth":"' + fake + '","discord_channel_id":"123456789012345678"}'
        result = redact_credentials(text)
        self.assertNotIn(fake, result)
        self.assertIn('123456789012345678', result)
        self.assertEqual(redact_credentials('今晚玩 token hunter？'), '今晚玩 token hunter？')
        from cogs.community_audit import preview
        self.assertNotIn(fake, preview(N(content=fake, channel=N(is_nsfw=lambda: False))))
        self.assertNotIn('abcdef0123456789', redact_credentials('TWITCH_CLIENT_SECRET="abcdef0123456789"'))
