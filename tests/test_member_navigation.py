import types
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from features.drink_views import MemberCardView,MemberNavigationView,LevelBoardView,DrinkCollectionView,DrinkResultView
from features.drink_leaderboard import DrinkLeaderboardView
from cogs.daily_bar import DailyBarView


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_paging_retains_selected_week_and_does_not_award_xp(self):
        cog=MagicMock();cog.leaderboard.callback=AsyncMock()
        view=LevelBoardView(cog,'2026-W45',2,True)
        inter=object()
        await next(b for b in view.children if b.label=='下一頁').callback(inter)
        cog.leaderboard.callback.assert_awaited_once_with(cog,inter,weekly=True,page=3,period='2026-W45')
        cog.credit.assert_not_called()
        view.stop()

    async def test_mobile_navigation_and_persistent_result_ids(self):
        views=[MemberCardView(),MemberNavigationView(),LevelBoardView(MagicMock(),None,1,False),DrinkResultView(),DrinkLeaderboardView(guild=None)]
        for view in views:
            self.assertTrue(any(b.label=='返回吧枱' for b in view.children))
            for row in range(5):self.assertLessEqual(sum(b.row==row for b in view.children),3)
            view.stop()
        result=DrinkResultView()
        self.assertTrue(result.is_persistent())
        self.assertIn('bartender:result:menu_entry',{b.custom_id for b in result.children})
        result.stop()

    async def test_collection_preserves_title_select_row_and_navigation(self):
        from features.drink_views import CollectionTitleSelect
        view=DrinkCollectionView(owner_id=10,guild=None,target_user=types.SimpleNamespace(id=10))
        self.assertFalse(any(b.row==3 for b in view.children))
        self.assertIn('我的會員卡',{b.label for b in view.children})
        self.assertIn('酒吧排行榜',{b.label for b in view.children})
        view.stop()

    async def test_daily_task_keeps_completion_state_and_has_refresh_and_return(self):
        with patch('cogs.daily_bar.get_daily_bar_completion',return_value={'task_key':'drink'}):
            view=DailyBarView(guild_id=1,user_id=10)
        self.assertTrue(view.children[0].disabled)
        self.assertTrue({'我的會員卡','我的收藏','重新整理','返回吧枱'}<={b.label for b in view.children})
        view.stop()
