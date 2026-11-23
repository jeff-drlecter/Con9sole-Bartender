import unittest
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from cogs.rss_delivery import RSSDelivery
from core.rss_personal_ui import IntelligenceSettings, NewsCardPanel, PreferencesView
from core.rss_preferences import DEFAULT
from data.menu_registry import PREVIOUS_QUICK_MENU_ITEMS
from features.drink_views import MemberCardView
from features.language_preferences import localize_menu
from features.menu_actions import open_quick_bar_menu
from features.menu_embeds import build_quick_bar_embed
from features.menu_views import HomeMenuView, LegacyMenuView, QuickBarView
from quick_bar_fakes import interaction, member


class RoundIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_public_area_role_gets_current_native_guidance_in_own_language(self):
        from features.menu_views import PublicExploreButton
        for code in ('hk', 'tw', 'neutral'):
            inter = interaction()
            inter.guild.id = inter.guild_id = config.GUILD_ID
            if code != 'neutral':
                inter.user.roles = [S(id=123456789, name='語境偏好｜' + ('香港' if code == 'hk' else '台灣'),
                                      managed=False, permissions=S(value=0))]
            with patch('features.menu_views.send_or_followup', new=AsyncMock()) as send:
                await PublicExploreButton().callback(inter)
            result = send.call_args.kwargs
            self.assertTrue(result['ephemeral'])
            self.assertIn('<id:customize>', result['content'])
            self.assertIn('揀選' if code == 'hk' else '選擇', result['content'])
            self.assertNotIn('你想加入綜合聊天區嗎', result['content'])
            inter.user.add_roles.assert_not_called()

    async def test_public_explore_links_only_the_visible_public_chat(self):
        from features.menu_views import PublicExploreButton
        inter = interaction()
        inter.guild.id = inter.guild_id = config.GUILD_ID
        inter.user.roles = [S(id=123, name='off-topic')]
        chat = MagicMock(spec=discord.TextChannel)
        chat.mention = '<#1013033957383741542>'
        chat.jump_url = f'https://discord.com/channels/{config.GUILD_ID}/1013033957383741542'
        inter.guild.get_channel.return_value = chat
        with patch('features.menu_views.send_or_followup', new_callable=AsyncMock) as send:
            for visible in (True, False):
                chat.permissions_for.return_value = discord.Permissions(view_channel=visible)
                await PublicExploreButton().callback(inter)
                result = send.await_args.kwargs
                self.assertTrue(result['ephemeral'])
                inter.guild.get_channel.assert_called_with(1013033957383741542)
                if visible:
                    self.assertEqual(result['view'].children[0].url, chat.jump_url)
                    self.assertIn(chat.mention, result['content'])
                else:
                    self.assertNotIn('view', result)
                    self.assertNotIn(chat.mention, result['content'])

            inter.guild.id = inter.guild_id = 1
            inter.guild.get_channel.reset_mock()
            await PublicExploreButton().callback(inter)
            inter.guild.get_channel.assert_not_called()
            self.assertNotIn('view', send.await_args.kwargs)
        inter.user.add_roles.assert_not_called()

    async def test_all_previous_quick_ids_and_removed_actions_dispatch(self):
        cog = MagicMock()
        current, legacy = QuickBarView(cog), LegacyMenuView(cog, 'quick')
        ids = {c.custom_id for v in (current, legacy) for c in v.children}
        self.assertTrue({f'bartender:quick:{x.id}' for x in PREVIOUS_QUICK_MENU_ITEMS} <= ids)
        self.assertNotIn('tempvc_control', {c.item.id for c in current.children})
        self.assertIn('daily_bar', {c.item.id for c in HomeMenuView(cog).children})
        self.assertIn('DailyBar', {c.cog_name for c in MemberCardView().children})
        for key, target, method in [('tempvc_control', 'TempVC', 'open_control_panel_from_menu'),
                                    ('daily_bar', 'DailyBar', 'menu_entry'),
                                    ('invite', 'Invites', 'menu_entry')]:
            inter = interaction()
            feature = S(**{method: AsyncMock()})
            inter.client.get_cog.return_value = feature
            item = next(c.item for v in (current, legacy) for c in v.children if c.item.id == key)
            await legacy.handle_item(inter, item)
            inter.client.get_cog.assert_called_with(target)
            getattr(feature, method).assert_awaited_once_with(inter)

    async def test_new_menu_private_language_and_three_buttons_per_row(self):
        for code in ('hk', 'tw', 'neutral'):
            user = member()
            user.roles = [] if code == 'neutral' else [S(name='語境偏好｜' + ('香港' if code == 'hk' else '台灣'),
                                                        managed=False, permissions=S(value=0))]
            embed, view = localize_menu(user, build_quick_bar_embed(user), QuickBarView(S()))
            self.assertEqual(len(view.children), 12)
            self.assertTrue(all(sum(c.row == row for c in view.children) == 3 for row in range(4)))
            self.assertIn('偏好與設定' if code != 'hk' else '偏好同設定', embed.description)
            self.assertEqual(view.children[6].label, '飲一杯' if code == 'hk' else '喝一杯')
            self.assertTrue(view.is_persistent())

    async def test_rss_settings_are_access_checked_and_legacy_card_can_return(self):
        cog = S(personal_access=AsyncMock(return_value=False))
        inter = interaction()
        with patch('core.rss_personal_ui.open_settings', new=AsyncMock()) as opened:
            await RSSDelivery.settings_entry(cog, inter)
            opened.assert_not_awaited()
            cog.personal_access.return_value = True
            await RSSDelivery.settings_entry(cog, inter)
            opened.assert_awaited_once_with(cog, inter)
            panel = NewsCardPanel(cog)
            await panel.preferences.callback(inter)
            self.assertEqual(opened.await_count, 2)
        settings = IntelligenceSettings(cog, inter.user.id, inter.user)
        self.assertIn('Menu', {getattr(c, 'cog_name', None) for c in settings.children})
        prefs = PreferencesView(S(digest_config=S(simulation=False)), inter.user.id, DEFAULT, inter.user)
        self.assertIn('返回情報設定', {getattr(c, 'label', None) for c in prefs.children})
        for row in prefs.to_components():
            self.assertLessEqual(len(row['components']), 5)

    async def test_private_navigation_replaces_only_private_component_messages(self):
        for shared in (True, False):
            inter = interaction()
            inter.type = discord.InteractionType.component
            inter.message.flags.ephemeral = not shared
            with patch('features.menu_actions.record_usage', new=AsyncMock()):
                await open_quick_bar_menu(MagicMock(), inter, ephemeral=True)
            if shared:
                self.assertTrue(inter.response.send_message.call_args.kwargs['ephemeral'])
                inter.response.edit_message.assert_not_awaited()
            else:
                inter.response.edit_message.assert_awaited_once()
                inter.response.send_message.assert_not_awaited()
            sender = inter.response.send_message if shared else inter.response.edit_message
            view = sender.call_args.kwargs['view']
            self.assertEqual(next(c.label for c in view.children if c.item.id == 'support'), '聯絡 Helper')

    async def test_back_from_deferred_private_help_replaces_existing_panel(self):
        inter = interaction()
        inter.type = discord.InteractionType.component
        inter.message.flags.ephemeral = True
        inter.response.is_done.return_value = True
        inter.response.type = discord.InteractionResponseType.deferred_message_update
        with patch('features.menu_actions.record_usage', new=AsyncMock()):
            await open_quick_bar_menu(MagicMock(), inter, ephemeral=True)
        inter.edit_original_response.assert_awaited_once()
        inter.followup.send.assert_not_awaited()
