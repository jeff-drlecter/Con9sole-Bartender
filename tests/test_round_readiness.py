import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.inspect_round_readiness import inspect

class Readiness(unittest.TestCase):
    def test_pre_migration_read_only_unknown_receipt_and_no_member_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dbpath=root/'community_stats.sqlite3'
            with sqlite3.connect(dbpath) as db:
                db.executescript('CREATE TABLE squad_interest_delivery(session_id TEXT,users TEXT,state TEXT); CREATE TABLE squad_ended_sessions(session_id TEXT); CREATE TABLE squad_card_posts(state TEXT);')
                db.execute('INSERT INTO squad_interest_delivery VALUES(?,?,?)',('s','[987654321098765432]','pending'))
            (root/'squad_plans.json').write_text(json.dumps({'plans':{'a':{'status':'open'}}}))
            (root/'squad_cards.json').write_text(json.dumps({'sessions':{'a':{'id':'s'}}}))
            before={p.name:p.read_bytes() for p in root.iterdir()}
            result=inspect(root,{})
            self.assertTrue(result['unclassified_active_receipts_present'])
            self.assertTrue(result['persisted_active_voice_sessions_present'])
            self.assertFalse(result['deployment_approved'])
            self.assertFalse(result['plan_event_unresolved_present'])
            self.assertFalse(result['host_notice_unresolved_present'])
            self.assertNotIn('987654321098765432',json.dumps(result))
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            with sqlite3.connect(dbpath) as db:
                db.execute("ALTER TABLE squad_interest_delivery ADD COLUMN origins TEXT DEFAULT '{}'")
                db.execute('UPDATE squad_interest_delivery SET origins=?',(json.dumps({'987654321098765432':{'game':True,'plan':False}}),))
            self.assertFalse(inspect(root,{})['unclassified_active_receipts_present'])

    def test_missing_store_is_not_created_or_reported_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):inspect(Path(tmp),{})
            self.assertEqual(list(Path(tmp).iterdir()),[])
