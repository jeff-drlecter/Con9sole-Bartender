import asyncio
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.community_levels import CommunityLevels
from cogs.daily_bar import DailyBarView, DailyBarActionButton
from features import daily_bar as daily
from features.community_levels import Ledger, calendar
from quick_bar_fakes import interaction


class DailyCommunityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(daily, 'STATS_DB', Path(self.temp.name)/'stats.sqlite3')
        self.db_patch.start()
        self.now = datetime(2026, 11, 10, 4, tzinfo=timezone.utc)
        self.task = next(t for t in daily.COMMUNITY_TASKS if t.key == 'text')
        self.task_patch = patch.object(daily, 'get_daily_bar_task', return_value=self.task)
        self.task_patch.start()
        self.cog = CommunityLevels(MagicMock())
        self.cog.ledger = Ledger(Path(self.temp.name)/'levels.sqlite3')
        self.cog.cfg = self.cog.ledger.configure(1, mode='active')
        self.cog.apply_rewards = AsyncMock()
        self.cog.ensure_current_membership = AsyncMock(return_value=True)
        self.inter = interaction()
        self.inter.user.joined_at = self.now-timedelta(days=1)
        self.inter.user.guild = self.inter.guild
        self.clock = patch('cogs.community_levels.time.time', return_value=self.now.timestamp())
        self.clock.start()
        self.guild_patch = patch('config.GUILD_ID', 1)
        self.guild_patch.start()

    def tearDown(self):
        self.guild_patch.stop(); self.clock.stop(); self.task_patch.stop(); self.db_patch.stop(); self.temp.cleanup()

    async def test_progress_counts_successful_events_not_multiplier_or_cooldown_rejections(self):
        stamp = self.now.timestamp()
        self.cog.ledger.award(1, 10, 'text', 'first', stamp-180, multiplier=2)
        self.cog.ledger.award(1, 10, 'text', 'rejected', stamp-179)
        self.cog.ledger.award(1, 10, 'activity', 'drink', stamp-120)
        self.cog.ledger.award(1, 10, 'text', 'second', stamp-60)
        self.assertEqual((await self.cog.daily_task_status(self.inter))['progress'], 2)
        self.assertIsNone(await self.cog.task_credit(self.inter))
        self.cog.ledger.award(1, 10, 'text', 'third', stamp)
        results = await asyncio.gather(*(self.cog.task_credit(self.inter) for _ in range(8)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'], 10)
        self.assertIsNone(self.cog.ledger.award(1,10,'activity','still-cooling',stamp+1))
        status = await self.cog.daily_task_status(self.inter)
        self.assertEqual(status['progress'], 3)
        self.assertIn('已入帳', status['reward_state'])
        self.cog.apply_rewards.assert_awaited_once()

    async def test_committed_task_reward_survives_role_failure_across_midnight(self):
        stamp = datetime(2026, 11, 10, 15, 59, 59, tzinfo=timezone.utc).timestamp()
        self.inter.user.premium_since = None
        self.cog.ledger.award(1,10,'text','one',stamp-120)
        self.cog.ledger.award(1,10,'text','two',stamp-60)
        # Role API work is deliberately unavailable; the reward must commit first
        # against the award's day, even when the processing clock is tomorrow.
        self.cog.apply_rewards = AsyncMock(side_effect=RuntimeError('role API delayed'))
        with patch('cogs.community_levels.time.time',return_value=stamp+2):
            with self.assertLogs('cogs.community_levels',level='ERROR'):
                with self.assertRaises(RuntimeError):
                    await self.cog.credit(self.inter.user,self.inter.channel,'text','third',now=stamp)
        self.assertIsNotNone(self.cog.ledger.event_proof(1,'daily-task:2026-11-10:10'))
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],8)
        self.assertIsNone(self.cog.ledger.daily_bonus(1,10,'2026-11-10',stamp))

    async def test_pending_completion_retries_after_mode_enabled_but_exclusion_blocks_claim(self):
        self.task_patch.stop()
        team = next(t for t in daily.COMMUNITY_TASKS if t.key == 'team')
        self.task_patch = patch.object(daily, 'get_daily_bar_task', return_value=team); self.task_patch.start()
        daily.complete_daily_bar_task(guild_id=1,user_id=10,feature_key='team',now=self.now)
        self.cog.cfg = self.cog.ledger.configure(1,mode='off')
        self.assertIsNone(await self.cog.task_credit(self.inter))
        self.assertIn('待核對', (await self.cog.daily_task_status(self.inter))['reward_state'])
        self.cog.cfg = self.cog.ledger.configure(1,mode='active',excluded_channels=[100])
        self.assertIsNone(await self.cog.task_credit(self.inter))
        self.cog.cfg = self.cog.ledger.configure(1,excluded_channels=[])
        self.assertIsNotNone(await self.cog.task_credit(self.inter))
        self.assertIsNone(await self.cog.task_credit(self.inter))

    async def test_returner_does_not_inherit_old_progress_or_unclaimed_completion(self):
        stamp = self.now.timestamp()
        for n in range(3): self.cog.ledger.award(1,10,'text',str(n),stamp-600+n*60)
        daily.complete_daily_bar_task(guild_id=1,user_id=10,feature_key='text',now=self.now-timedelta(minutes=5))
        self.inter.user.joined_at = self.now-timedelta(minutes=1)
        self.assertEqual((await self.cog.daily_task_status(self.inter))['progress'],0)
        self.assertIsNone(await self.cog.task_credit(self.inter))
        # New committed events may replace an earlier membership's unclaimed completion.
        for n in range(3): self.cog.ledger.award(1,10,'text','new'+str(n),stamp+n*60)
        with patch('cogs.community_levels.time.time',return_value=stamp+120):
            self.assertIsNotNone(await self.cog.task_credit(self.inter))

    async def test_rejoin_completion_compares_instants_across_timezone_formats(self):
        from core.sqlite_storage import connect_sqlite
        daily.init_daily_bar_db()
        # This UTC completion is LATER than the member's HK joined time, even
        # though its ISO wall-clock digits sort before the HK representation.
        with connect_sqlite(daily.STATS_DB) as db:
            db.execute('INSERT INTO daily_bar_completions VALUES(?,?,?,?,?)',
                (1,10,'2026-11-10','text','2026-11-10T03:00:00+00:00'))
        self.assertFalse(daily.complete_daily_bar_task(guild_id=1,user_id=10,feature_key='text',
            joined_since=datetime(2026,11,10,2,tzinfo=timezone.utc).timestamp(),now=self.now))
        self.assertTrue(daily.complete_daily_bar_task(guild_id=1,user_id=10,feature_key='text',
            joined_since=datetime(2026,11,10,3,30,tzinfo=timezone.utc).timestamp(),now=self.now))

    async def test_midnight_panel_and_foreign_owner_rejected_before_actions(self):
        with patch.object(daily,'_current_date',return_value='2026-11-10'):
            view = DailyBarView(guild_id=1,user_id=10)
        with patch.object(daily,'_current_date',return_value='2026-11-11'):
            self.assertFalse(await view.interaction_check(self.inter))
        self.inter.user.id=11
        with patch.object(daily,'_current_date',return_value='2026-11-10'):
            self.assertFalse(await view.interaction_check(self.inter))
        view.stop()

    async def test_text_task_only_gives_instructions_no_xp_from_button(self):
        button = DailyBarActionButton(task_key='text',emoji='💬',completed=False)
        await button.callback(self.inter)
        self.inter.client.get_cog.assert_not_called()
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],0)


class TaskScheduleTests(unittest.TestCase):
    def test_legacy_day_unchanged_and_new_pool_has_no_passive_view_task(self):
        import hashlib
        now = datetime(2026,11,8,15,59,tzinfo=timezone.utc)
        idx = int(hashlib.sha256(b'1:2026-11-08').hexdigest()[:8],16)%len(daily.DAILY_BAR_TASKS)
        self.assertEqual(daily.get_daily_bar_task(1,now=now),daily.DAILY_BAR_TASKS[idx])
        self.assertNotIn('drink_collection',{t.key for t in daily.COMMUNITY_TASKS})
        self.assertTrue({'text','voice','team'} <= {t.key for t in daily.COMMUNITY_TASKS})

    def test_daily_bonus_is_atomic_across_connections_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'xp.sqlite3'); ledger.configure(1,mode='active')
            stamp=datetime(2026,11,10,4,tzinfo=timezone.utc).timestamp()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda _: Ledger(ledger.path).daily_bonus(1,10,calendar(stamp)[0],stamp), range(8)))
            self.assertEqual(sum(x is not None for x in results),1)
            self.assertEqual(ledger.profile(1,10)['total'],5)
            self.assertEqual(ledger.leaderboard(1,calendar(stamp)[1]),[(10,5)])
