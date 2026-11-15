import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.verify_community_runtime import verify, GUILD


class RuntimeTests(unittest.TestCase):
    def test_read_only_inventory_does_not_create_missing_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=verify(root,{'RSS_DIGEST_CONFIG':str(root/'missing')},100)
            self.assertEqual(result['outcome_store'],'unavailable')
            self.assertEqual(list(root.iterdir()),[])

    def test_policy_allowlist_never_outputs_private_settings_or_event_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with sqlite3.connect(root/'community_levels.sqlite3') as db:
                db.execute('CREATE TABLE settings(guild INTEGER,value TEXT)')
                db.execute('INSERT INTO settings VALUES(?,?)',(GUILD,json.dumps(dict(mode='active',activity_daily_cap=0,private='SECRET',member=987654321))))
            (root/'squad_plans.json').write_text(json.dumps(dict(plans={'a':dict(start=1,owner=987654321,game='PRIVATE GAME')})))
            before={p.name:p.read_bytes() for p in root.iterdir()}
            result=verify(root,{'RSS_DIGEST_CONFIG':str(root/'missing'),'DISCORD_TOKEN':'SECRET'},100)
            output=json.dumps(result)
            self.assertNotIn('SECRET',output)
            self.assertNotIn('987654321',output)
            self.assertNotIn('PRIVATE GAME',output)
            self.assertEqual(result['stored_exp_policy']['activity_daily_cap'],0)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
