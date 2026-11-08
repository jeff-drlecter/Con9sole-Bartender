import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.sqlite_storage import connect_sqlite
from features.community_levels import Ledger, threshold
from features.level_migration import (strict_json,validate_snapshot,apply_snapshot,
                                     create_backup,restore_backup,role_restore_plan)


class MigrationTests(unittest.TestCase):
    def test_existing_activation_or_bonus_blocks_raw_snapshot(self):
        for key in ('historical_bonus','activation','activation_intent'):
            self.ledger.configure(1,**{key:{'state':'applied'}})
            with self.assertRaisesRegex(ValueError,'reviewed rebase'):
                apply_snapshot(self.ledger,self.snapshot,**self.args)
            self.ledger.configure(1,**{key:None})

    def test_import_guard_is_rechecked_after_backup(self):
        def changed_during_backup(ledger,path):
            digest=create_backup(ledger,path)
            ledger.configure(1,activation={'state':'active'})
            return digest
        with patch('features.level_migration.create_backup',side_effect=changed_during_backup):
            with self.assertRaisesRegex(ValueError,'reviewed rebase'):
                apply_snapshot(self.ledger,self.snapshot,**self.args,commit=True)
        self.assertEqual(self.ledger.profile(1,10)['total'],0)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=Ledger(self.root/'live.sqlite3');self.ledger.configure(1,mode='off')
        self.snapshot=dict(schema=1,source='amari',guild_id='1',
            captured_at='2026-11-06T15:00:00Z',cutover_at='2026-11-06T15:00:00Z',
            source_frozen_at='2026-11-06T15:00:00Z',weekly_period='Amari counter captured at cutover; start unknown',
            users=[dict(user_id='10',total_xp=threshold(15)+123,level=15,level_xp=123,weekly_xp=10000),
                   dict(user_id='11',total_xp=0,level=0,level_xp=0,weekly_xp=0)])
        self.args=dict(guild=1,roster_ids=[10,11],expected_count=2,backup_path=self.root/'before.sqlite3')

    def tearDown(self): self.tmp.cleanup()

    def validate(self,snapshot=None):
        return validate_snapshot(snapshot or self.snapshot,guild=1,roster_ids=[10,11],expected_count=2)

    def test_strict_values_and_source_set(self):
        for value in [True,1.5,float('nan'),-1,2**63,'01']:
            s=copy.deepcopy(self.snapshot);s['users'][0]['total_xp']=value
            with self.subTest(value=value),self.assertRaises(ValueError):self.validate(s)
        for body in ['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}']:
            with self.assertRaises(ValueError): strict_json(body)
        s=copy.deepcopy(self.snapshot);s['users'][1]['user_id']='10'
        with self.assertRaises(ValueError):self.validate(s)
        with self.assertRaises(ValueError):validate_snapshot(self.snapshot,guild=1,roster_ids=[10,12],expected_count=2)
        s=copy.deepcopy(self.snapshot);s['schema']=True
        with self.assertRaises(ValueError):self.validate(s)

    def test_curve_weekly_may_exceed_total_and_no_naive_time(self):
        self.validate()
        s=copy.deepcopy(self.snapshot);s['users'][0]['level_xp']=1
        with self.assertRaises(ValueError):self.validate(s)
        s=copy.deepcopy(self.snapshot);s['cutover_at']='2026-11-06T15:00:00'
        with self.assertRaises(ValueError):self.validate(s)
        s=copy.deepcopy(self.snapshot);s['source_frozen_at']='2026-11-06T15:00:01Z'
        with self.assertRaises(ValueError):self.validate(s)

    def test_preview_replaced_post_cutover_only_replayed_exactly_and_seed_notices(self):
        cutoff=self.validate()['cutover']
        self.ledger.configure(1,mode='preview')
        self.ledger.award(1,10,'text','pre',cutoff-60)
        self.ledger.award(1,10,'activity','post',cutoff+60)
        self.ledger.configure(1,mode='off')
        plan=apply_snapshot(self.ledger,self.snapshot,**self.args)
        self.assertEqual(plan['bridge_events'],1)
        self.assertEqual(self.ledger.profile(1,10)['total'],2)
        result=apply_snapshot(self.ledger,self.snapshot,**self.args,commit=True)
        self.assertEqual(self.ledger.profile(1,10)['total'],threshold(15)+124)
        self.assertEqual(self.ledger.profile(1,10)['activity'],1)
        self.assertEqual(self.ledger.profile(1,10)['text'],0)
        self.assertEqual(self.ledger.leaderboard(1,'amari-legacy'),[(10,10000),(11,0)])
        self.assertEqual(self.ledger.notice_level(1,10,0),15)
        with self.assertRaises(ValueError):apply_snapshot(self.ledger,self.snapshot,**self.args,commit=True)
        self.ledger.configure(1,mode='preview')
        self.assertIsNone(self.ledger.award(1,11,'text','late-pre',cutoff-1))
        self.assertIsNone(self.ledger.award(1,10,'activity','post',cutoff+600))
        self.assertTrue(result['backup_sha'])

    def test_injected_failure_rolls_back_all_preview_data(self):
        self.ledger.configure(1,mode='preview');self.ledger.award(1,10,'text','m1',100)
        self.ledger.configure(1,mode='off')
        with connect_sqlite(self.ledger.path) as db:
            db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON periods BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(Exception):apply_snapshot(self.ledger,self.snapshot,**self.args,commit=True)
        self.assertEqual(self.ledger.profile(1,10)['total'],1)
        with connect_sqlite(self.ledger.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM xp_events').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM migration_manifests').fetchone()[0],0)

    def test_wal_backup_restore_and_current_checkpoint_preserved(self):
        self.ledger.configure(1,mode='preview');self.ledger.award(1,10,'text','m1',100)
        self.ledger.configure(1,mode='off')
        path=self.root/'backup.sqlite3';sha=create_backup(self.ledger,path)
        self.ledger.adjust(1,10,99,123,'later',200)
        restore_backup(self.ledger,path,expected_sha=sha,guild=1,checkpoint_path=self.root/'post.sqlite3')
        self.assertEqual(self.ledger.profile(1,10)['total'],1)
        self.assertEqual(self.ledger.settings(1)['mode'],'off')
        self.assertEqual(Ledger(self.root/'post.sqlite3').profile(1,10)['total'],124)
        with self.assertRaises(ValueError):create_backup(self.ledger,path)
        with self.assertRaises(ValueError):restore_backup(self.ledger,path,expected_sha='bad',guild=1,checkpoint_path=self.root/'unused')
        with self.assertRaises(ValueError):restore_backup(self.ledger,path,expected_sha=sha,guild=2,checkpoint_path=self.root/'unused')

    def test_only_off_and_safe_role_restore_plan(self):
        self.ledger.configure(1,mode='preview')
        with self.assertRaises(ValueError):apply_snapshot(self.ledger,self.snapshot,**self.args,commit=True)
        result=role_restore_plan({'10':[50]}, {'10':[150,999]}, [50,150])
        self.assertEqual(result,[dict(user_id=10,add=[50],remove=[150])])
        with self.assertRaises(ValueError):role_restore_plan({'10':[999]}, {}, [50,150])
        with self.assertRaises(ValueError):role_restore_plan({'10':[50,50]}, {}, [50])


if __name__=='__main__':unittest.main()
