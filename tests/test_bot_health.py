import sqlite3
import tempfile
import unittest
from pathlib import Path
from features.bot_health import database_health,storage_health
from features.community_levels import Ledger


class HealthTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing'
            self.assertIn('未',database_health(path,[])['status'])
            self.assertFalse(path.exists())

    def test_health_is_read_only_and_reports_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'levels')
            ledger.configure(1,mode='active')
            ledger.adjust(1,10,20,5,'test',100)
            before=ledger.path.read_bytes()
            health=storage_health(ledger.path,1,Path(folder)/'missing-stats')
            self.assertEqual(health['等級帳本']['status'],'ok')
            self.assertEqual(health['等級帳本']['待同步角色'],1)
            self.assertEqual(ledger.path.read_bytes(),before)
            self.assertFalse((Path(folder)/'missing-stats').exists())
