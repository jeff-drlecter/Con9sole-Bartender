import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.community_levels import CommunityLevels
from features.community_levels import Ledger
from features.drink_views import DrinkResultView, MemberCardView


class BarLevelTests(unittest.IsolatedAsyncioTestCase):
    async def test_component_rank_and_boards_defer_as_private_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            cog = CommunityLevels(MagicMock())
            cog.ledger = Ledger(Path(temp) / 'levels')
            cog.cfg = {'mode': 'active'}
            inter = types.SimpleNamespace(guild_id=1, user=types.SimpleNamespace(id=10, mention='<@10>'), response=types.SimpleNamespace(defer=AsyncMock()), followup=types.SimpleNamespace(send=AsyncMock()))
            with patch('features.collection_milestones.collection_snapshot', return_value={'names': set(), 'awards': [], 'selected': None}):
                await cog.menu_entry(inter)
            inter.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
            inter.response.defer.reset_mock()
            await cog.weekly_entry(inter)
            inter.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)

    async def test_drink_uses_shared_cooldown_and_durable_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch('config.GUILD_ID', 1):
            cog = CommunityLevels(MagicMock())
            cog.ledger = Ledger(Path(temp) / 'levels')
            cog.cfg = cog.ledger.configure(1, mode='active')
            cog.apply_rewards = AsyncMock()
            member = types.SimpleNamespace(id=10, guild=types.SimpleNamespace(id=1), bot=False, roles=[], premium_since=None)
            channel = types.SimpleNamespace(id=30, parent_id=None, category_id=None)
            inter = types.SimpleNamespace(id=100, user=member, channel=channel)
            cog.ledger.award(1, 10, 'text', 'text-message', 100)
            with patch('cogs.community_levels.time.time', return_value=120):
                self.assertIsNone(await cog.drink_credit(inter))
            inter.id = 101
            with patch('cogs.community_levels.time.time', return_value=170):
                self.assertEqual(await cog.drink_credit(inter), '會員 XP +1')
            with patch('cogs.community_levels.time.time', return_value=240):
                self.assertIsNone(await cog.drink_credit(inter))
            profile = cog.ledger.profile(1, 10)
            self.assertEqual((profile['total'], profile['text'], profile['activity']), (2, 1, 1))

    async def test_preview_does_not_claim_live_xp(self):
        cog = CommunityLevels(MagicMock())
        cog.cfg = {'mode': 'preview'}
        cog.credit = AsyncMock(return_value=(0, 1))
        self.assertIsNone(await cog.drink_credit(MagicMock()))

    async def test_card_navigation_fits_and_result_links_to_card(self):
        view = MemberCardView()
        self.assertEqual({(b.cog_name,b.method) for b in view.children}, {('CommunityLevels','leaderboard_entry'), ('CommunityLevels','weekly_entry'), ('Drink','collection_entry'), ('DailyBar','menu_entry'), ('Menu','open_main_menu'), ('TitleRoles','menu_entry')})
        self.assertLessEqual(len(view.children), 6)
        result = DrinkResultView()
        self.assertTrue(result.is_persistent())
        self.assertTrue(any(b.cog_name == 'CommunityLevels' and b.method == 'menu_entry' for b in result.children))
