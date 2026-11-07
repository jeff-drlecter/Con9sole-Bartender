import json
import tempfile
import unittest
from pathlib import Path

from core.sqlite_storage import connect_sqlite
from features.community_levels import Ledger,threshold,REWARD_NAMES
from features.level_baseline import stage_public,build_manifest,save_plan,load_plan,apply_plan,role_mapping
from features.level_migration import restore_backup


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=Ledger(self.root/'live.sqlite3');self.ledger.configure(1,mode='preview')
        self.roles=[{'id':level,'name':f'Lv {level} {name}'} for level,name in REWARD_NAMES.items()]
        self.members=[dict(id=10,aliases=['alpha','nickname'],roles=[5]),dict(id=11,aliases=['beta'],roles=[5,15]),
                      dict(id=12,aliases=['no-proof'],roles=[])]
        self.public=[[1,'alpha',threshold(15)+20,15],[2,'Unknown',55,2]]

    def tearDown(self):self.tmp.cleanup()

    def plan(self):
        manifest=build_manifest(1,99,self.members,self.roles,self.public,1000,'test')
        return save_plan(self.ledger,manifest),manifest

    def apply(self,plan,**changes):
        args=dict(guild=1,actor=99,plan=plan,members=self.members,roles=self.roles,backup_path=self.root/'backup.sqlite3',now=1001)
        args.update(changes)
        return apply_plan(self.ledger,**args)

    def test_exact_public_xp_precedes_role_and_highest_role_uses_floor(self):
        _,data=self.plan();rows={r['user_id']:r for r in data['rows']}
        self.assertEqual(rows[10]['baseline'],threshold(15)+20)
        self.assertEqual(rows[10]['kind'],'public_board')
        self.assertEqual(rows[11]['baseline'],threshold(15))
        self.assertEqual(data['skipped'],[12]);self.assertEqual(data['unknown_departed'],1)
        self.assertEqual(threshold(5),355);self.assertEqual(threshold(15),3955)

    def test_ambiguous_aliases_and_duplicate_public_owner_fall_back_to_roles(self):
        self.members[1]['aliases'].append('alpha')
        _,data=self.plan()
        self.assertTrue(all(r['kind']=='role_floor' for r in data['rows']))
        self.members[1]['aliases'].remove('alpha')
        self.public.append([3,'nickname',threshold(5),5])
        _,data=self.plan()
        self.assertTrue(all(r['kind']=='role_floor' for r in data['rows']))

    def test_public_below_known_role_is_held_as_conflict(self):
        self.public[0]=[1,'alpha',0,0]
        _,data=self.plan()
        self.assertEqual(data['conflicts'],[10]);self.assertNotIn(10,[r['user_id'] for r in data['rows']])

    def test_public_parts_are_immutable_rank_complete_and_curve_checked(self):
        def part(n,rows):return json.dumps(dict(batch='b',part=n,parts=2,rows=rows,expected_count=2,observed_at=100))
        self.assertFalse(stage_public(self.ledger,1,part(1,self.public[:1]),100,expected_count=2)['complete'])
        result=stage_public(self.ledger,1,part(2,self.public[1:]),101,expected_count=2)
        self.assertTrue(result['complete']);self.assertEqual(len(result['rows']),2)
        stage_public(self.ledger,1,part(1,self.public[:1]),102,expected_count=2)
        with self.assertRaises(ValueError):stage_public(self.ledger,1,part(1,[[1,'alpha',0,0]]),103,expected_count=2)
        with self.assertRaises(ValueError):stage_public(self.ledger,1,part(1,[[1,'alpha',55,3]]),103,expected_count=2)

    def test_truncated_ten_or_119_row_board_is_not_a_complete_120_capture(self):
        for size in (10,119):
            rows=[[i,f'person{i}',0,0] for i in range(1,size+1)]
            chunks=[rows[i:i+40] for i in range(0,size,40)]
            for index,chunk in enumerate(chunks,1):
                body=json.dumps(dict(batch=f'b{size}',part=index,parts=len(chunks),rows=chunk,expected_count=120,observed_at=100))
                if index==len(chunks):
                    with self.assertRaises(ValueError):stage_public(self.ledger,1,body,100)
                else:stage_public(self.ledger,1,body,100)

    def test_old_capture_cannot_refresh_and_partial_role_map_is_rejected(self):
        body=json.dumps(dict(batch='old',part=1,parts=1,rows=self.public,expected_count=2,observed_at=100))
        stage_public(self.ledger,1,body,100,expected_count=2)
        with self.assertRaises(ValueError):stage_public(self.ledger,1,body,701,expected_count=2)
        body=body.replace('"observed_at": 100','"observed_at": 700')
        with self.assertRaises(ValueError):stage_public(self.ledger,1,body,701,expected_count=2)
        with self.assertRaises(ValueError):role_mapping(self.roles[:-1])

    def test_commit_replaces_not_adds_archives_shadow_and_retains_new_events(self):
        self.ledger.award(1,10,'activity','old-bot',800)
        plan,data=self.plan()
        self.ledger.award(1,10,'text','new-text',1000)
        self.ledger.award(2,10,'text','other-guild',1000) # off: never leaks across guild
        self.ledger.configure(1,mode='off')
        result=self.apply(plan)
        self.assertFalse(result['already_applied'])
        self.assertEqual(self.ledger.profile(1,10)['total'],threshold(15)+21)
        self.assertEqual(self.ledger.profile(1,11)['total'],threshold(15))
        self.assertIsNone(self.ledger.event_proof(1,'old-bot'))
        self.assertIsNotNone(self.ledger.event_proof(1,'new-text'))
        with connect_sqlite(self.ledger.path) as db:
            shadow=json.loads(db.execute('SELECT events FROM hybrid_shadow WHERE guild=1 AND user=10').fetchone()[0])
            self.assertEqual(shadow[0][0],'old-bot')
        self.assertEqual(self.ledger.settings(1)['mode'],'off')
        self.assertTrue(self.apply(plan)['already_applied'])
        self.assertEqual(self.ledger.profile(1,10)['total'],threshold(15)+21)

    def test_member_or_role_changes_expiry_actor_and_running_mode_reject(self):
        plan,_=self.plan()
        with self.assertRaises(ValueError):self.apply(plan)
        self.ledger.configure(1,mode='off')
        for args in [dict(actor=98),dict(now=1601),dict(members=self.members[:-1]),
                     dict(roles=self.roles+[{'id':55,'name':'Lv 5 註冊會員'}])]:
            with self.assertRaises(ValueError):self.apply(plan,**args)

    def test_late_adjustment_rolls_back_entire_baseline(self):
        self.ledger.award(1,10,'text','before',800)
        plan,_=self.plan()
        self.ledger.adjust(1,11,99,7,'after-preview',1000)
        self.ledger.configure(1,mode='off')
        with self.assertRaises(ValueError):self.apply(plan)
        self.assertEqual(self.ledger.profile(1,10)['total'],1)
        self.assertEqual(self.ledger.profile(1,11)['total'],7)
        with connect_sqlite(self.ledger.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM hybrid_shadow').fetchone()[0],0)
        self.assertEqual(load_plan(self.ledger,1,plan)[1],'preview')

    def test_verified_backup_restores_original_shadow_ledger(self):
        self.ledger.award(1,10,'text','before',800)
        plan,_=self.plan();self.ledger.configure(1,mode='off')
        result=self.apply(plan)
        restore_backup(self.ledger,self.root/'backup.sqlite3',expected_sha=result['backup_sha'],guild=1,checkpoint_path=self.root/'checkpoint.sqlite3')
        self.assertEqual(self.ledger.profile(1,10)['total'],1)
        self.assertEqual(load_plan(self.ledger,1,plan)[1],'preview')


if __name__=='__main__':unittest.main()
