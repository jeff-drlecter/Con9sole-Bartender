import json
import tempfile
import unittest
from pathlib import Path
from core.sqlite_storage import connect_sqlite
from features.community_levels import Ledger
from features.level_bonus import prepare,apply
from features.level_migration import restore_backup

class BonusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.ledger=Ledger(self.root/'live')
        self.ledger.configure(1,mode='preview');self.ledger.award(1,10,'text','m:retained',200)
        baseline=dict(cutover=1786982500,rows=[dict(user_id=10)])
        with connect_sqlite(self.ledger.path) as db:
            db.execute('INSERT INTO hybrid_plans VALUES(?,?,?,?,?,?,?,?,?)',(1,'base',99,100,json.dumps(baseline),'d','applied','p','s'))
        self.replay=dict(algorithm='net-shared-cooldown-v1',evidence_digest='a'*64,policy=dict(baseline='base',cutoff=1786982500,users=[10],cooldown=60),
            users={10:dict(base_xp=5,combined=15,text_only=10,game_accepted=7)})
        self.manifest=prepare(self.ledger,1,99,'job',1786982400,self.replay,{10})
    def tearDown(self):self.temp.cleanup()
    def commit(self,manifest=None,**extra):
        return apply(self.ledger,manifest or self.manifest,self.root/'backup',300,actor=99,current_users={10},accept_base_only=True,**extra)
    def test_atomic_once_preserves_current_week_and_cooldown_and_restores(self):
        self.ledger.configure(1,mode='off')
        with connect_sqlite(self.ledger.path) as db:
            before={table:db.execute(f'SELECT * FROM {table}').fetchall() for table in ('periods','cooldowns','receipts','xp_events')}
        result=self.commit();self.assertEqual(self.ledger.profile(1,10)['total'],6)
        self.assertTrue(self.commit()['already_applied'])
        with connect_sqlite(self.ledger.path) as db:
            for table,rows in before.items():self.assertEqual(rows,db.execute(f'SELECT * FROM {table}').fetchall())
            self.assertEqual(db.execute('SELECT count(*) FROM adjustments').fetchone()[0],1)
        restore_backup(self.ledger,self.root/'backup',expected_sha=result['backup_sha'],guild=1,checkpoint_path=self.root/'checkpoint')
        self.assertEqual(self.ledger.profile(1,10)['total'],1)
        self.assertNotIn('historical_bonus',self.ledger.settings(1))
    def test_policy_mode_and_actor_guards(self):
        with self.assertRaises(ValueError):self.commit()
        self.ledger.configure(1,mode='off')
        with self.assertRaises(ValueError):apply(self.ledger,self.manifest,self.root/'backup',300,actor=99,current_users={10})
        with self.assertRaises(ValueError):apply(self.ledger,self.manifest,self.root/'backup',300,actor=98,current_users={10},accept_base_only=True)
        self.assertFalse((self.root/'backup').exists())
    def test_overlapping_second_batch_rejected(self):
        self.ledger.configure(1,mode='off');self.commit()
        other=dict(self.manifest,job='different')
        with self.assertRaises(ValueError):self.commit(other)
    def test_plan_rejects_unverified_member_or_wrong_cutoff(self):
        with self.assertRaises(ValueError):prepare(self.ledger,1,99,'job',1786982400,self.replay,set())
        self.replay['policy']['cutoff']=101
        with self.assertRaises(ValueError):prepare(self.ledger,1,99,'job',1786982400,self.replay,{10})

    def test_second_member_failure_rolls_back_first_and_metadata(self):
        self.ledger.configure(1,mode='off')
        with connect_sqlite(self.ledger.path) as db:
            body=json.loads(db.execute("SELECT manifest FROM hybrid_plans WHERE plan='base'").fetchone()[0])
            body['rows'].append(dict(user_id=11))
            db.execute("UPDATE hybrid_plans SET manifest=? WHERE plan='base'",(json.dumps(body),))
            tables=('xp','adjustments','notice_state','settings')
            before={table:db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        manifest=dict(self.manifest,users=self.manifest['users']+[dict(user=11,amount=1)])
        with self.assertRaises(ValueError):apply(self.ledger,manifest,self.root/'backup',300,actor=99,current_users={10,11},accept_base_only=True)
        with connect_sqlite(self.ledger.path) as db:
            for table,rows in before.items():self.assertEqual(rows,db.execute(f'SELECT * FROM {table}').fetchall())

class BonusReleaseGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_flag_cannot_bypass_unselected_policy(self):
        import types
        from unittest.mock import MagicMock,AsyncMock
        from cogs.community_levels import CommunityLevels
        from features.level_history import HistoryAudit
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ledger=Ledger(root/'live');audit=HistoryAudit(root/'audit')
            start=1786982400;cutoff=start+500
            ledger.configure(1,mode='preview');ledger.adjust(1,10,99,100,'fixture',start)
            baseline=dict(cutover=cutoff,rows=[dict(user_id=10)])
            with connect_sqlite(ledger.path) as db:
                db.execute('INSERT INTO hybrid_plans VALUES(?,?,?,?,?,?,?,?,?)',(1,'base',99,cutoff,json.dumps(baseline),'d','applied','p','s'))
            job=audit.start(1,start,cutoff,[{'bot':2,'channel':3}])
            audit.record(job,message=4,channel=3,bot=2,stamp=start+100,edited=None,user=10,name='name',kind='normal',reason='candidate',payload={})
            audit.state(job,'complete');audit.start_text(job,1,[3],dict(baseline='base',cutoff=cutoff,cooldown=60,users=[10]))
            audit.text_checkpoint(job,3,4,[],True);audit.text_state(job,'complete')
            admin=types.SimpleNamespace(id=99,guild_permissions=types.SimpleNamespace(administrator=True))
            guild=types.SimpleNamespace(id=1,me=admin,members=[types.SimpleNamespace(id=10,bot=False)],fetch_member=AsyncMock())
            inter=types.SimpleNamespace(guild_id=1,guild=guild,user=admin,followup=types.SimpleNamespace(send=AsyncMock()))
            cog=CommunityLevels(MagicMock());cog.ledger=ledger;cog.history_audit=audit;cog.cfg=ledger.settings(1);cog.guard=AsyncMock(return_value=True)
            await cog.history_bonus_command.callback(cog,inter,commit=True,base_only=True,digest='irrelevant')
            self.assertIn('未選定',inter.followup.send.call_args.args[0])
            guild.fetch_member.assert_not_awaited()
            self.assertEqual(ledger.settings(1)['mode'],'preview');self.assertEqual(ledger.profile(1,10)['total'],100)
