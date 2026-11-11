import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.menu import Menu
from data.menu_registry import PREVIOUS_HOME_MENU_ITEMS, SECTION_MENU_ITEMS
from features.menu_views import HomeMenuView, LegacyMenuView, QuickBarView, SectionMenuView
from quick_bar_fakes import interaction


class UnifiedMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_previous_deployed_ids_and_each_section_remain_persistent(self):
        cog = MagicMock()
        home = HomeMenuView(cog, include_admin=True)
        legacy = LegacyMenuView(cog, 'home')
        registered = {b.custom_id for v in (home, legacy) for b in v.children}
        for item in PREVIOUS_HOME_MENU_ITEMS:
            self.assertIn(f'bartender:home:{item.id}', registered)
        self.assertIn('bartender:home:public_explore', registered)
        for section in SECTION_MENU_ITEMS:
            view = SectionMenuView(cog, section)
            self.assertTrue(view.is_persistent())
            self.assertTrue({'返回上一頁', '返回酒吧'} <= {b.label for b in view.children})
            for row in range(5):
                self.assertLessEqual(sum(b.row == row for b in view.children), 3)
            view.stop()
        home.stop(); legacy.stop()

    async def test_category_and_back_routes_bypass_activity_cooldown(self):
        menu = MagicMock()
        menu.enforce_menu_button_cooldown = AsyncMock(return_value=False)
        menu.open_records_menu = AsyncMock()
        menu.open_main_menu = AsyncMock()
        view = HomeMenuView(menu)
        inter = interaction()
        await view.handle_item(inter, next(b.item for b in view.children if b.item.id == 'records'))
        menu.open_records_menu.assert_awaited_once_with(inter)
        section = SectionMenuView(menu, 'records')
        await section.handle_item(inter, next(b.item for b in section.children if b.item.id == 'quick_bar'))
        menu.open_main_menu.assert_awaited_once_with(inter)
        menu.enforce_menu_button_cooldown.assert_not_awaited()
        view.stop(); section.stop()

    async def test_open_section_reads_only_and_customize_does_not_assign_roles(self):
        cog = MagicMock()
        cog.record_usage = AsyncMock()
        inter = interaction()
        with patch('cogs.menu.send_or_followup', new=AsyncMock()) as send:
            await Menu._open_section(cog, inter, 'records')
            self.assertTrue(send.call_args.kwargs['ephemeral'])
            self.assertIsInstance(send.call_args.kwargs['view'], SectionMenuView)
            await Menu.open_customize_menu(cog, inter)
            self.assertIn('<id:customize>', send.call_args.kwargs['content'])
        inter.user.add_roles.assert_not_called()
        inter.user.remove_roles.assert_not_called()
        inter.client.get_cog.assert_not_called()

    async def test_missing_feature_has_safe_return_without_activity_side_effect(self):
        view = SectionMenuView(MagicMock(), 'records')
        inter = interaction()
        inter.client.get_cog.return_value = None
        with patch('features.menu_views.send_or_followup', new=AsyncMock()) as send:
            await view.handle_item(inter, next(b.item for b in view.children if b.item.id == 'drink_collection'))
            self.assertIsInstance(send.call_args.kwargs['view'], QuickBarView)
            self.assertTrue(send.call_args.kwargs['ephemeral'])
        view.stop()
