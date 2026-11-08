import json
import tempfile
import unittest
from pathlib import Path
from core.sqlite_storage import connect_sqlite
from features.community_levels import Ledger,REWARD_NAMES
from features.level_activation import readiness,commit,role_plan
from features.level_migration import create_backup,restore_backup

class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.ledger=Ledger(self.root/'live')
        mapping={str(k):k*10 for k in REWARD_NAMES}
        self.cfg=self.ledger.configure(1,mode='preview',cutover_at=100,rewards=mapping,
            role_drill=dict(id='drill',state='restored',remove_observed=True,remove_succeeded=True,mapping=mapping),
            historical_bonus=dict(manifest=dict(baseline='base')))
        with connect_sqlite(self.ledger.path) as db:
            db.execute('INSERT INTO hybrid_plans VALUES(?,?,?,?,?,?,?,?,?)',(1,'base',99,100,'{}','d','applied','p','s'))
        for uid in (10,11):self.ledger.award(1,uid,'voice',f'v:30:{uid}:1000',1000)
        self.members=[dict(user=uid,roles=[]) for uid in (10,11,12)]
    def tearDown(self):self.temp.cleanup()
    def prepare(self):
        evidence=readiness(self.ledger,1,self.ledger.settings(1),1010)
        self.ledger.configure(1,activation_intent=dict(actor=99,stamp=1010,members=self.members,mapping=self.cfg['rewards']))
        sha=create_backup(self.ledger,self.root/'backup')
        self.preview=role_plan(self.ledger,1,self.cfg['rewards'],self.members)['digest']
        return evidence,dict(announcement_channel=123,announcement_ping=True,backup_path=str(self.root/'backup'),backup_sha=sha)
    def test_atomic_active_and_all_member_jobs_without_notices_and_restore(self):
        evidence,changes=self.prepare()
        with connect_sqlite(self.ledger.path) as db:
            original={t:db.execute(f'SELECT * FROM {t}').fetchall() for t in ('xp','periods','cooldowns','xp_events')}
        cfg=commit(self.ledger,1,changes,self.members,evidence,1010,self.preview)
        self.assertEqual(cfg['mode'],'active');self.assertTrue(cfg['announcement_ping'])
        with connect_sqlite(self.ledger.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM role_jobs').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM notice_state').fetchone()[0],2)
            for t,rows in original.items():self.assertEqual(rows,db.execute(f'SELECT * FROM {t}').fetchall())
        with self.assertRaises(ValueError):commit(self.ledger,1,changes,self.members,evidence,1010,self.preview)
        self.ledger.configure(1,mode='off')
        restore_backup(self.ledger,self.root/'backup',expected_sha=changes['backup_sha'],guild=1,checkpoint_path=self.root/'checkpoint')
        self.assertEqual(self.ledger.settings(1)['mode'],'off')
        with connect_sqlite(self.ledger.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM role_jobs').fetchone()[0],0)
    def test_role_drill_and_historical_baseline_evidence_cannot_be_skipped(self):
        cfg=dict(self.cfg,role_drill={})
        with self.assertRaises(ValueError):readiness(self.ledger,1,cfg,1010)
        cfg=dict(self.cfg,historical_bonus={})
        with self.assertRaises(ValueError):readiness(self.ledger,1,cfg,1010)
    def test_one_voice_user_is_insufficient_and_no_config_change(self):
        with connect_sqlite(self.ledger.path) as db:db.execute('DELETE FROM xp_events WHERE user=11')
        with self.assertRaises(ValueError):readiness(self.ledger,1,self.cfg,1010)
        self.assertEqual(self.ledger.settings(1)['mode'],'preview')
    def test_changed_evidence_or_member_scope_never_partially_activates(self):
        evidence,changes=self.prepare()
        with self.assertRaises(ValueError):commit(self.ledger,1,changes,self.members+[self.members[0]],evidence,1010,self.preview)
        with self.assertRaises(ValueError):commit(self.ledger,1,changes,self.members,{**evidence,'role_drill':'changed'},1010,self.preview)
        self.assertEqual(self.ledger.settings(1)['mode'],'preview')
        with connect_sqlite(self.ledger.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM role_jobs').fetchone()[0],0)

    def test_conflict_or_roleholder_without_profile_is_held_never_zeroed(self):
        self.members[-1]['roles']=[150]
        with connect_sqlite(self.ledger.path) as db:db.execute("UPDATE hybrid_plans SET manifest=? WHERE plan='base'",(json.dumps(dict(conflicts=[12])),))
        plan=role_plan(self.ledger,1,self.cfg['rewards'],self.members)
        self.assertEqual(plan['counts']['hold'],1)
        row=next(r for r in plan['rows'] if r['user']==12)
        self.assertEqual(row['remove'],[]);self.assertEqual(row['target'],[150])
        evidence,changes=self.prepare()
        with self.assertRaises(ValueError):commit(self.ledger,1,changes,self.members,evidence,1010,self.preview)
        self.assertEqual(self.ledger.settings(1)['mode'],'preview')
        with connect_sqlite(self.ledger.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM role_jobs').fetchone()[0],0)
