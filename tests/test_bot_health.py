import sqlite3
import tempfile
import unittest
from pathlib import Path
from features.bot_health import database_health,storage_health,review_history
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


    def test_audit_is_guild_scoped_bounded_and_read_only(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'stats'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE notification_reviews(id INTEGER PRIMARY KEY,guild INTEGER,audit TEXT)')
                for i in range(15):
                    db.execute('INSERT INTO notification_reviews(guild,audit) VALUES(?,?)',(1,json.dumps(dict(actor=7,stamp=i,action='retry'))))
                db.execute('INSERT INTO notification_reviews(guild,audit) VALUES(?,?)',(2,json.dumps(dict(actor=9,stamp=100,action='retry'))))
            before=path.read_bytes()
            rows=review_history(None,1,path)
            self.assertEqual(len(rows),10)
            self.assertEqual(rows[0]['stamp'],14)
            self.assertEqual({r['actor'] for r in rows},{7})
            self.assertEqual(path.read_bytes(),before)

    def test_audit_missing_files_are_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing'
            self.assertEqual(review_history(path,1,path),[])
            self.assertFalse(path.exists())


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_without_level_cog_still_reads_queues(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from cogs.bot_health import BotHealth
        member=SimpleNamespace(id=7)
        bot=SimpleNamespace(get_cog=lambda name:None)
        inter=SimpleNamespace(guild_id=1,user=member,
            guild=SimpleNamespace(get_member=lambda uid:member),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),followup=SimpleNamespace(send=AsyncMock()))
        with patch('config.GUILD_ID',1), patch('cogs.bot_health.can_use_staff_tool',return_value=True), patch('cogs.bot_health.HealthView',return_value=None), patch('cogs.bot_health.storage_health',return_value={'社群紀錄':{'待發通知':3}}) as read:
            await BotHealth(bot).menu_entry(inter,refresh=True)
        read.assert_called_once()
        inter.response.defer.assert_awaited_once_with(ephemeral=True,thinking=False)
        inter.edit_original_response.assert_awaited_once()
        inter.followup.send.assert_not_awaited()
        embed=inter.edit_original_response.call_args.kwargs['embed']
        self.assertTrue(any(f.name=='社群紀錄' and '3' in f.value for f in embed.fields))
