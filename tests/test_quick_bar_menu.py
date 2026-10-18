import unittest
from unittest.mock import MagicMock

from quick_bar_fakes import member

from data.menu_registry import LEGACY_HOME_MENU_ITEMS, LEGACY_QUICK_MENU_ITEMS
from features.drink_views import DrinkCollectionView, DrinkResultView
from features.menu_embeds import build_quick_bar_embed
from features.menu_views import HomeMenuView, LegacyMenuView, QuickBarView


class MenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_quick_bar_is_five_stable_actions(self):
        view = QuickBarView(MagicMock())
        self.assertEqual(
            [(b.label, b.row) for b in view.children],
            [
                ("飲一杯", 0),
                ("請人飲", 0),
                ("搵人玩", 1),
                ("小隊 call", 1),
                ("更多", 2),
            ],
        )
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(build_quick_bar_embed(member()).fields), 0)

    async def test_member_more_menu_hides_admin_but_retains_collections(self):
        view = HomeMenuView(MagicMock())
        ids = {b.custom_id for b in view.children}
        self.assertNotIn("bartender:home:admin_tool", ids)
        self.assertIn("bartender:home:drink_collection", ids)
        self.assertIn("bartender:home:public_explore", ids)
        self.assertIn(
            "bartender:home:admin_tool",
            {
                b.custom_id
                for b in HomeMenuView(MagicMock(), include_admin=True).children
            },
        )

    async def test_old_menu_button_ids_remain_routable(self):
        cog = MagicMock()
        for layer, items, new in (
            ("quick", LEGACY_QUICK_MENU_ITEMS, QuickBarView(cog)),
            ("home", LEGACY_HOME_MENU_ITEMS, HomeMenuView(cog, include_admin=True)),
        ):
            registered = {b.custom_id for b in new.children} | {
                b.custom_id for b in LegacyMenuView(cog, layer).children
            }
            for item in items:
                self.assertIn(f"bartender:{layer}:{item.id}", registered)

    async def test_collection_and_result_navigation_fit_discord_rows(self):
        views = [
            DrinkCollectionView(owner_id=10, guild=None, target_user=member()),
            DrinkResultView(),
        ]
        for view in views:
            for row in range(5):
                self.assertLessEqual(
                    sum(1 for button in view.children if button.row == row), 5
                )
        self.assertTrue(views[1].is_persistent())

    async def test_navigation_and_primary_actions_are_not_blocked_by_menu_cooldown(
        self,
    ):
        from unittest.mock import AsyncMock
        from quick_bar_fakes import interaction

        menu = MagicMock()
        menu.enforce_menu_button_cooldown = AsyncMock(return_value=False)
        team = MagicMock(menu_entry=AsyncMock())
        i = interaction()
        i.client.get_cog.return_value = team
        view = QuickBarView(menu)
        button = next(button for button in view.children if button.item.id == "team")
        await view.handle_item(i, button.item)
        team.menu_entry.assert_awaited_once_with(i)
        menu.enforce_menu_button_cooldown.assert_not_awaited()
