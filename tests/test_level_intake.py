import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from features.level_intake import prepare_intake,normalize,read_rows
from features.level_migration import validate_snapshot


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.args=dict(guild=1,totals_raw=b'user_id,total_xp,level,weekly_xp\n10,55,2,90\n11,0,0,0\n',
            totals_format='csv',totals_mapping={'columns':{k:k for k in ('user_id','total_xp','level','weekly_xp')}},
            roster_ids=[10,11],source_count=2,metadata=dict(guild_id='1',exported_at='2026-11-07T05:00:00Z',
                weekly_period='Amari supplied period/reset description',source_reference='official export receipt'))

    def test_staging_is_not_an_importable_snapshot_and_preserves_large_weekly(self):
        result=prepare_intake(**self.args)
        self.assertEqual(result['users'][0],dict(user_id=10,total_xp=55,level=2,level_xp=0,weekly_xp=90))
        self.assertFalse(result['migration_ready'])
        self.assertEqual(len(result['raw_sha256']['totals']),64)
        self.assertEqual(result['mappings']['totals'],self.args['totals_mapping'])
        with self.assertRaises(ValueError):validate_snapshot(result,guild=1,roster_ids=[10,11],expected_count=2)

    def test_wrapped_json_needs_explicit_mapping_and_preserves_snowflake_precision(self):
        raw=b'{"data":[{"id":"9007199254740993","exp":55,"weekly":100}]}'
        mapping={'rows_key':'data','columns':{'user_id':'id','total_xp':'exp','weekly_xp':'weekly'}}
        rows,derived=normalize(raw,'json',mapping)
        self.assertIn(9007199254740993,rows)
        self.assertTrue(derived)
        with self.assertRaises(ValueError):read_rows(raw,'json')

    def test_missing_weekly_is_pending_not_zero_and_separate_weekly_join_is_exact(self):
        args=copy.deepcopy(self.args)
        args['totals_raw']=b'user_id,total_xp\n10,55\n11,0\n'
        args['totals_mapping']={'columns':{'user_id':'user_id','total_xp':'total_xp'}}
        pending=prepare_intake(**args)
        self.assertEqual(pending['missing_weekly_ids'],[10,11])
        self.assertIsNone(pending['users'][0]['weekly_xp'])
        args.update(weekly_raw=b'id,weekly\n11,2\n10,900\n',weekly_format='csv',
                    weekly_mapping={'columns':{'user_id':'id','weekly_xp':'weekly'}})
        ready=prepare_intake(**args)
        self.assertEqual([r['weekly_xp'] for r in ready['users']],[900,2])
        args['weekly_raw']=b'id,weekly\n12,1\n'
        with self.assertRaises(ValueError):prepare_intake(**args)

    def test_bad_values_keys_csv_width_and_duplicate_ids_are_rejected(self):
        for raw in [b'[{"id":"10","id":"11","xp":1}]',b'[{"id":true,"xp":1}]',
                    b'[{"id":"01","xp":1}]',b'[{"id":"10","xp":1.0}]',
                    b'[{"id":"10","xp":NaN}]',b'[{"id":"10","xp":-1}]',
                    b'[{"id":"10","xp":1},{"id":"10","xp":2}]']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                normalize(raw,'json',{'columns':{'user_id':'id','total_xp':'xp'}})
        for raw in [b'id,id\n10,10\n',b'id,xp\n10\n',b'id,xp\n10,1,extra\n']:
            with self.assertRaises(ValueError):read_rows(raw,'csv')

    def test_exclusions_need_ids_and_independent_counts_cannot_be_guessed(self):
        args=copy.deepcopy(self.args);args['roster_ids']=[10];args['excluded_ids']=[11]
        self.assertEqual(prepare_intake(**args)['excluded_ids'],[11])
        for value in [[],[10],[12],['Unknown']]:
            args['excluded_ids']=value
            with self.assertRaises(ValueError):prepare_intake(**args)
        args=copy.deepcopy(self.args);args['source_count']=1
        with self.assertRaises(ValueError):prepare_intake(**args)

    def test_wrong_guild_naive_time_and_level_mismatch_fail(self):
        for change in [dict(guild_id=2),dict(exported_at='2026-11-07T05:00:00'),dict(source_reference='')]:
            args=copy.deepcopy(self.args);args['metadata'].update(change)
            with self.assertRaises(ValueError):prepare_intake(**args)
        args=copy.deepcopy(self.args);args['totals_raw']=args['totals_raw'].replace(b'10,55,2',b'10,55,3')
        with self.assertRaises(ValueError):prepare_intake(**args)

    def test_roster_objects_are_not_silently_read_as_id_keys(self):
        args=copy.deepcopy(self.args);args['roster_ids']={'10':True,'11':True}
        with self.assertRaises(ValueError):prepare_intake(**args)
        args=copy.deepcopy(self.args);args['excluded_ids']={}
        with self.assertRaises(ValueError):prepare_intake(**args)

    def test_separate_weekly_timestamp_must_be_aware_and_capture_mismatch_is_flagged(self):
        args=copy.deepcopy(self.args)
        args['totals_mapping']['columns'].pop('weekly_xp')
        args.update(weekly_raw=b'[{"id":"10","xp":90},{"id":"11","xp":0}]',weekly_format='json',
            weekly_mapping={'columns':{'user_id':'id','weekly_xp':'xp'}})
        self.assertTrue(any('timestamp is missing' in b for b in prepare_intake(**args)['blockers']))
        args['metadata'].update(weekly_exported_at='2026-11-07T05:00:01Z',weekly_source_reference='weekly receipt')
        self.assertTrue(any('capture times differ' in b for b in prepare_intake(**args)['blockers']))
        args['metadata']['weekly_exported_at']='2026-11-07T05:00:01'
        with self.assertRaises(ValueError):prepare_intake(**args)

    def test_cli_creates_private_outputs_once_without_touching_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'totals.csv').write_bytes(self.args['totals_raw'])
            for name,value in [('mapping',self.args['totals_mapping']),('roster',[10,11]),('metadata',self.args['metadata'])]:
                (root/f'{name}.json').write_text(json.dumps(value))
            before={p.name:p.read_bytes() for p in root.iterdir()}
            command=[sys.executable,'scripts/prepare_level_data.py','--guild','1','--totals',str(root/'totals.csv'),
                '--format','csv','--mapping',str(root/'mapping.json'),'--roster',str(root/'roster.json'),
                '--metadata',str(root/'metadata.json'),'--source-count','2','--output',str(root/'output')]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(os.stat(root/'output/intake.json').st_mode&0o777,0o600)
            self.assertEqual(os.stat(root/'output').st_mode&0o777,0o700)
            original=(root/'output/intake.json').read_bytes()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual((root/'output/intake.json').read_bytes(),original)
            self.assertEqual({name:(root/name).read_bytes() for name in before},before)


if __name__=='__main__':unittest.main()
