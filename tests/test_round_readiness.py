import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.inspect_round_readiness import inspect, require_idle

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
            with self.assertRaises(ValueError):require_idle(result)
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

    def test_idle_gate_rejects_missing_unknown_and_every_inflight_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with sqlite3.connect(root/'community_stats.sqlite3') as db:
                db.executescript('CREATE TABLE squad_interest_delivery(session_id TEXT,users TEXT,state TEXT); CREATE TABLE squad_ended_sessions(session_id TEXT); CREATE TABLE squad_card_posts(state TEXT);')
            (root/'squad_plans.json').write_text('{"plans":{}}')
            (root/'squad_cards.json').write_text('{"sessions":{}}')
            result=inspect(root,{})
            require_idle(result)
            for key,value in result.items():
                if key.endswith('_present'):
                    for unsafe in (True,None,'false'):
                        with self.subTest(key=key,unsafe=unsafe), self.assertRaises(ValueError):
                            require_idle(dict(result,**{key:unsafe}))
                    missing=dict(result);del missing[key]
                    with self.assertRaises(ValueError):require_idle(missing)
            with self.assertRaises(ValueError):require_idle({})

    def test_event_unknown_and_queued_host_notice_hold_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with sqlite3.connect(root/'community_stats.sqlite3') as db:
                db.executescript('CREATE TABLE squad_interest_delivery(session_id TEXT,users TEXT,state TEXT); CREATE TABLE squad_ended_sessions(session_id TEXT); CREATE TABLE squad_card_posts(state TEXT);')
            (root/'squad_plans.json').write_text(json.dumps({'plans':{'a':{'status':'ended','delivery':{'event':{'state':'unknown'},'notices':[{'state':'queued'}]}}}}))
            (root/'squad_cards.json').write_text('{"sessions":{}}')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            result=inspect(root,{})
            with self.assertRaises(ValueError):require_idle(result)
            self.assertTrue(result['plan_event_unresolved_present'])
            self.assertTrue(result['host_notice_unresolved_present'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
