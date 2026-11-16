import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
import discord
import config
from features.squad_plans import PlanBook
from features.plan_services import PersonalReminders, query, AccessError, contract
from features.plan_browse_ui import InstantDraft, browse
from cogs.squad_plans import SquadPlans

class Services(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.book=PlanBook(Path(self.tmp.name)/'p.json',clock=lambda:10000)
        self.cog=N(book=self.book,lock=asyncio.Lock(),bot=N(user=N(id=9),get_cog=lambda _:None))
        self.guild=N(id=config.GUILD_ID,fetch_member=AsyncMock(return_value=N(id=2,bot=False)))
        self.api=PersonalReminders(self.cog)
        self.src=patch('features.plan_services.source',new=AsyncMock(return_value=(N(id=2),N(id=30))))
        self.source=self.src.start();self.addCleanup(self.src.stop)
    def create(self,owner=1):
        p=self.book.create(guild=self.guild.id,channel=30,owner=owner,game='FC',mode='PC',start=10100,party=1,capacity=2)
        self.book.publish(p['id'],99);return p['id']
    async def test_consent_idempotent_stale_epoch_restart_and_withdrawal(self):
        k=self.create();self.book.act(k,2,'join')
        row=(await self.api.read_for_member(self.guild,2,k))['row']
        r=await self.api.set_for_member(self.guild,2,k,enabled=True,expected_version=row['version'])
        self.assertEqual(r['status'],'updated')
        r2=await self.api.set_for_member(self.guild,2,k,enabled=True,expected_version=r['version'])
        self.assertEqual(r2['reason'],'unchanged')
        self.book.act(k,2,'leave');self.book.act(k,2,'join')
        self.cog.book=PlanBook(self.book.path,clock=lambda:10000)
        self.assertEqual((await self.api.set_for_member(self.guild,2,k,enabled=True,expected_version=r['version']))['status'],'conflict')
        self.source.side_effect=AccessError('denied')
        self.assertEqual((await self.api.list_for_member(self.guild,2))['rows'],[])
    async def test_pages_over_twenty_full_and_revoked(self):
        for uid in range(1,26):self.create(uid)
        rows=await query(self.cog,self.guild,2)
        self.assertEqual(len(rows),25)
        self.book.act(rows[0]['id'],2,'join')
        self.assertEqual((await query(self.cog,self.guild,2))[0]['remaining'],0)
        i=N(guild=self.guild,guild_id=self.guild.id,user=N(id=2,roles=[]),response=N(is_done=lambda:False,defer=AsyncMock()),edit_original_response=AsyncMock())
        await browse(self.cog,i,page=2)
        self.assertEqual(len(i.edit_original_response.await_args.kwargs['embed'].fields),5)
        view=i.edit_original_response.await_args.kwargs['view']
        self.source.side_effect=AccessError('denied')
        await view.children[0].callback(i)
        self.assertEqual(len(i.edit_original_response.await_args.kwargs['embed'].fields),0)
    async def test_concurrent_last_slot(self):
        k=self.create()
        async def join(uid):
            async with self.cog.lock:
                try:self.book.act(k,uid,'join');return True
                except ValueError:return False
        self.assertEqual(sum(await asyncio.gather(join(2),join(3))),1)
    async def test_cancel_draft_no_write(self):
        draft=InstantDraft(self.cog,N(id=30),2,dict(game='FC',mode='',party=1,missing=2))
        i=N(user=N(id=2),response=N(edit_message=AsyncMock(),send_message=AsyncMock()))
        await draft.cancel.callback(i)
        self.assertEqual(self.book.all(),[])
        self.assertFalse(await draft.interaction_check(i))
    async def test_deleted_forbidden_temporary_unknown_keep_lifecycle(self):
        k=self.create();p=self.book.get(k)
        for exc,expected in [(discord.NotFound(N(status=404,reason='missing'),''),'card_deleted'),(discord.Forbidden(N(status=403,reason='denied'),''),'denied'),(discord.HTTPException(N(status=500,reason='fail'),''),'temporary_failure'),(TimeoutError(),'unknown_result')]:
            ch=N(fetch_message=AsyncMock(side_effect=exc))
            self.cog.bot.get_channel=lambda _:ch
            self.assertFalse(await SquadPlans.refresh(self.cog,p))
            self.assertEqual(self.book.get(k)['availability'],expected)
            self.assertEqual(self.book.get(k)['status'],'open')
        self.assertEqual(contract(self.book.get(k))['origin'],'scheduled')
    async def test_source_errors_and_latest_role_snapshot(self):
        from features.plan_services import fresh_source,source
        channel=N(id=30,guild=self.guild,permissions_for=lambda m:N(view_channel=True,read_message_history=True))
        self.guild.fetch_channel=AsyncMock(return_value=channel)
        self.guild.fetch_roles=AsyncMock(return_value=[N(id=1)])
        with patch('cogs.squad_plans.can_read',return_value=True):
            member,fresh=await fresh_source(self.guild,2,30)
            self.assertIsNot(fresh,channel)
            self.assertEqual(set(member.guild._roles),{1})
        with patch('cogs.squad_plans.can_read',return_value=False):
            with self.assertRaises(AccessError):await fresh_source(self.guild,2,30)
        self.guild.fetch_channel.side_effect=discord.NotFound(N(status=404,reason='missing'),'')
        with self.assertRaises(AccessError) as caught:await fresh_source(self.guild,2,30)
        self.assertEqual(caught.exception.reason,'source_deleted')
    async def test_partial_list_failure_is_not_empty_success(self):
        k=self.create();self.book.act(k,2,'join')
        self.source.side_effect=AccessError('temporary_failure')
        self.assertFalse((await self.api.list_for_member(self.guild,2))['complete'])
    async def test_original_button_and_center_share_revision(self):
        from cogs.squad_plans import ReminderView
        k=self.create();self.book.act(k,2,'join')
        user=N(id=2,roles=[])
        view=ReminderView(self.cog,k,user)
        row=(await self.api.read_for_member(self.guild,2,k))['row']
        i=N(user=user,guild=self.guild,response=N(edit_message=AsyncMock(),send_message=AsyncMock()))
        await view.children[0].callback(i)
        self.assertIn(2,self.book.get(k)['reminders'])
        result=await self.api.set_for_member(self.guild,2,k,enabled=False,expected_version=row['version'])
        self.assertEqual(result['status'],'conflict')
        row=(await self.api.read_for_member(self.guild,2,k))['row']
        self.assertEqual((await self.api.set_for_member(self.guild,2,k,enabled=False,expected_version=row['version']))['status'],'updated')
        await view.children[0].callback(i)
        self.assertNotIn(2,self.book.get(k)['reminders'])
