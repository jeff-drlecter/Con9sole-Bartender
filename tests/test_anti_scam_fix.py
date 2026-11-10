import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,patch,MagicMock
import discord
from features import anti_scam_fix as f


class FixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patcher=patch.object(f,'PATH',Path(self.tmp.name)/'fix.db');self.patcher.start();self.addCleanup(self.patcher.stop)

    def plan(self):
        return dict(id='test',guild=1,actor=7,stamp=f.time.time(),ops=[dict(kind='role',target=1,name='r',before=0,after=1,state='prepared')])

    def test_build_only_narrow_role_scope_and_keeps_other_bits(self):
        ordinary=next(iter(f.ORDINARY))
        roles=[NS(id=1,name='@everyone',permissions=discord.Permissions(view_channel=True)),NS(id=ordinary,name='game',managed=False,permissions=discord.Permissions(mention_everyone=True,send_messages=True)),NS(id=99,name='other',managed=False,permissions=discord.Permissions(mention_everyone=True))]
        plan=f.build(roles,[],1,7,10)
        change=next(o for o in plan['ops'] if o['target']==ordinary)
        self.assertTrue(discord.Permissions(change['after']).send_messages)
        self.assertFalse(discord.Permissions(change['after']).mention_everyone)
        self.assertNotIn(99,[o['target'] for o in plan['ops']])
        self.assertTrue(discord.Permissions(next(o for o in plan['ops'] if o['target']==1)['after']).use_voice_activation)

    def test_plan_bound_to_actor_and_guild(self):
        p=self.plan();f.save(p)
        self.assertEqual(f.load('test',1,7),p)
        with self.assertRaises(ValueError):f.load('test',1,8)
        with self.assertRaises(ValueError):f.load('test',2,7)

    async def test_conflict_stops_without_write(self):
        p=self.plan();role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(return_value=(9,role,None))):
            await f.execute(NS(),p,AsyncMock(return_value=True))
        role.edit.assert_not_awaited();self.assertEqual(p['ops'][0]['state'],'conflict')

    async def test_verified_apply_then_restore(self):
        p=self.plan();role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(side_effect=[(0,role,None),(1,role,None)])):
            await f.execute(NS(),p,AsyncMock(return_value=True))
        self.assertEqual(p['ops'][0]['state'],'verified')
        with patch.object(f,'current',AsyncMock(side_effect=[(1,role,None),(0,role,None)])):
            await f.execute(NS(),p,AsyncMock(return_value=True),restore=True)
        self.assertEqual(p['ops'][0]['state'],'restored')

    async def test_unknown_write_is_journalled_and_not_replayed(self):
        p=self.plan();role=NS(edit=AsyncMock(side_effect=RuntimeError('timeout')))
        with patch.object(f,'current',AsyncMock(return_value=(0,role,None))):
            with self.assertRaises(RuntimeError):await f.execute(NS(),p,AsyncMock(return_value=True))
        self.assertEqual(f.load('test',1,7)['ops'][0]['state'],'uncertain')
        with self.assertRaises(ValueError):await f.execute(NS(),p,AsyncMock(return_value=True))
        self.assertEqual(role.edit.await_count,1)

    async def test_revocation_after_read_prevents_write(self):
        p=self.plan();role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(return_value=(0,role,None))):
            with self.assertRaises(ValueError):await f.execute(NS(),p,AsyncMock(side_effect=[True,False]))
        role.edit.assert_not_awaited()


    async def test_already_desired_no_write_must_not_be_restored(self):
        p=self.plan();role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(return_value=(1,role,None))) as read:
            await f.execute(NS(),p,AsyncMock(return_value=True))
            await f.execute(NS(),p,AsyncMock(return_value=True),restore=True)
        self.assertEqual(read.await_count,1)
        role.edit.assert_not_awaited()
        self.assertFalse(p['ops'][0].get('attempted',False))

    async def test_prewrite_conflict_must_not_be_restored(self):
        p=self.plan();role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(return_value=(9,role,None))) as read:
            await f.execute(NS(),p,AsyncMock(return_value=True))
            await f.execute(NS(),p,AsyncMock(return_value=True),restore=True)
        self.assertEqual(read.await_count,1)
        role.edit.assert_not_awaited()


    async def test_batch_limit_leaves_remaining_prepared(self):
        p=self.plan();p['ops']*=3
        p['ops']=[dict(op) for op in p['ops']]
        role=NS(edit=AsyncMock())
        with patch.object(f,'current',AsyncMock(return_value=(1,role,None))):
            await f.execute(NS(),p,AsyncMock(return_value=True),max_ops=1)
        self.assertEqual([o['state'] for o in p['ops']],['verified','prepared','prepared'])

    async def test_cancelled_write_keeps_uncertain_receipt(self):
        import asyncio
        p=self.plan();role=NS(edit=AsyncMock(side_effect=asyncio.CancelledError()))
        with patch.object(f,'current',AsyncMock(return_value=(0,role,None))):
            with self.assertRaises(asyncio.CancelledError):
                await f.execute(NS(),p,AsyncMock(return_value=True))
        self.assertEqual(f.load('test',1,7)['ops'][0]['state'],'uncertain')
        with self.assertRaises(ValueError):
            await f.execute(NS(),p,AsyncMock(return_value=True))
