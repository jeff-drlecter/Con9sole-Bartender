import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from features.community_levels import Ledger, calendar
from features.daily_bar import _current_date


class DailyBonusTests(unittest.TestCase):
    def test_extra_reward_bypasses_but_does_not_reset_shared_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(Path(folder)/'levels')
            ledger.configure(1, mode='active')
            now = datetime(2026,11,8,4,tzinfo=timezone.utc).timestamp()
            ledger.award(1,10,'text','text',now)
            self.assertEqual(ledger.daily_bonus(1,10,calendar(now)[0],now+1),(1,6))
            self.assertIsNone(ledger.award(1,10,'activity','activity',now+2))
            self.assertEqual(ledger.leaderboard(1,calendar(now)[1]),[(10,6)])
            self.assertIsNone(Ledger(ledger.path).daily_bonus(1,10,calendar(now)[0],now+60))
            tomorrow=now+86400
            self.assertEqual(ledger.daily_bonus(1,10,calendar(tomorrow)[0],tomorrow),(6,11))

    def test_off_and_preview_do_not_consume_reward(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'levels')
            now=datetime(2026,11,8,4,tzinfo=timezone.utc).timestamp()
            for mode in ('off','preview'):
                ledger.configure(1,mode=mode)
                self.assertIsNone(ledger.daily_bonus(1,10,calendar(now)[0],now))
            ledger.configure(1,mode='active')
            self.assertEqual(ledger.daily_bonus(1,10,calendar(now)[0],now),(0,5))

    def test_task_and_reward_use_same_hong_kong_midnight(self):
        for hour,day in ((15,'2026-11-08'),(16,'2026-11-09')):
            now=datetime(2026,11,8,hour,tzinfo=timezone.utc)
            self.assertEqual(_current_date(now=now),day)
            self.assertEqual(calendar(now.timestamp())[0],day)
