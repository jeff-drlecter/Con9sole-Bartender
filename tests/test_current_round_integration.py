"""Real cross-module contracts; Discord transport alone is simulated, no login."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import config
from features import squad_interest as interest, plan_reminder_client
from features.squad_plans import PlanBook
from features.plan_services import PersonalReminders
from features.notification_center import show_center
from cogs.squad_plans import ReminderView


class Integration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name)
        p=patch.object(interest,'STATS_DB',path/'stats.db');p.start();self.addCleanup(p.stop)
        self.user=N(id=10,bot=False,roles=[])
        self.guild=N(id=config.GUILD_ID,fetch_member=AsyncMock(return_value=self.user),fetch_roles=AsyncMock(return_value=[]))
        self.channel=MagicMock(spec=discord.TextChannel)
        self.channel.id=100;self.channel.guild=self.guild;self.channel.nsfw=False
        self.channel.permissions_for.return_value=discord.Permissions(view_channel=True,read_message_history=True,send_messages=False)
        self.channel.fetch_message=AsyncMock(return_value=N(id=500,author=N(id=99)))
        self.guild.fetch_channel=AsyncMock(return_value=self.channel)
        self.book=PlanBook(path/'plans.json',clock=lambda:10000)
        self.plans=N(book=self.book,lock=asyncio.Lock())
        self.plans.personal_reminders_v1=PersonalReminders(self.plans)
        self.bot=N(user=N(id=99),get_cog=lambda key:self.plans if key=='SquadPlans' else None)
        self.plans.bot=self.bot
        self.cards=N(lock=asyncio.Lock())
        self.key=self.book.create(guild=self.guild.id,channel=100,owner=1,game='Any game',mode='PC',start=10100,party=1,capacity=3)['id']
        self.book.publish(self.key,500);self.book.act(self.key,10,'join')
        self.scope=interest.topic(self.guild.id,'Any game')['id'];interest.remember(interest.topic(self.guild.id,'Any game'))
        self.i=N(user=self.user,guild=self.guild,guild_id=self.guild.id,channel=self.channel,channel_id=100,client=self.bot,
            response=N(is_done=lambda:False,defer=AsyncMock(),send_message=AsyncMock(),edit_message=AsyncMock()),
            edit_original_response=AsyncMock(),followup=N(send=AsyncMock()))
        p=patch('cogs.squad_plans.is_verified_member',return_value=True);p.start();self.addCleanup(p.stop)

    async def test_real_center_original_card_stale_revision_and_restart(self):
        interest.toggle(self.scope,self.guild.id,10,'always')
        original=ReminderView(self.plans,self.key,self.user)
        await show_center(self.cards,self.i,section='detail',key=self.key)
        center=self.i.followup.send.await_args.kwargs['view']
        self.assertIsNotNone(center.selected)
        await center.set_plan(self.i,True)
        self.assertEqual(self.book.get(self.key)['reminders'],[10])
        # Old original-card token cannot undo the fresh center write.
        await original.children[1].callback(self.i)
        self.assertEqual(self.book.get(self.key)['reminders'],[10])
        original=ReminderView(self.plans,self.key,self.user)
        await original.children[1].callback(self.i)
        self.assertEqual(self.book.get(self.key)['reminders'],[])
        self.assertEqual(interest.preferences(self.scope),{10:'always'})
        self.plans.book=PlanBook(self.book.path,clock=lambda:10000)
        row=(await plan_reminder_client.query(self.bot,self.guild,10))[0]
        self.assertFalse(row['enabled'])
        # Leave/rejoin permanently changes the consent epoch.
        self.plans.book.act(self.key,10,'leave');self.plans.book.act(self.key,10,'join')
        result=await plan_reminder_client.set_choice(self.bot,self.guild,10,self.key,True,row['version'])
        self.assertEqual(result['status'],'conflict')

    async def test_real_source_failure_never_empty_success(self):
        self.channel.fetch_message.side_effect=discord.NotFound(N(status=404,reason='gone'),'')
        with self.assertRaises(plan_reminder_client.ReminderUnavailable):
            await plan_reminder_client.query(self.bot,self.guild,10)
        self.channel.fetch_message.side_effect=None
        self.guild.fetch_roles.side_effect=OSError('offline')
        await show_center(self.cards,self.i)
        self.assertIsNone(self.i.followup.send.await_args.kwargs['embed'])

    async def test_concurrent_center_writes_only_one_revision_wins(self):
        row=(await plan_reminder_client.query(self.bot,self.guild,10))[0]
        result=await asyncio.gather(*[plan_reminder_client.set_choice(self.bot,self.guild,10,self.key,True,row['version']) for _ in range(2)])
        self.assertEqual(sorted(r['status'] for r in result),['conflict','updated'])
        self.assertEqual(self.book.get(self.key)['reminders'],[10])

    async def test_receipt_origins_each_direction_and_legacy_preservation(self):
        for uid in (10,11):interest.toggle(self.scope,self.guild.id,uid)
        interest.reserve('both',self.scope,[10,11,12],plan_users={10,12})
        interest.cancel(self.scope,self.guild.id,10)
        rev=interest.claim_delivery('both',self.scope,0,require_origins=True)
        self.assertEqual(interest.delivery_users('both',self.scope,0,rev,plan_users={10}),[10,11])
        # Plan-only 12 was withdrawn; game 11 still eligible, consumed once 10 stays off.
        self.assertEqual(interest.delivery_users('both',self.scope,0,rev,plan_users=set()),[11])
        interest.reserve('legacy',self.scope,[12],plan_users={12})
        with interest.connect_sqlite(interest.STATS_DB) as db:
            db.execute("UPDATE squad_interest_delivery SET origins='{}' WHERE session_id='legacy'")
            before=tuple(db.execute("SELECT * FROM squad_interest_delivery WHERE session_id='legacy'").fetchone())
        self.assertIsNone(interest.claim_delivery('legacy',self.scope,0,require_origins=True))
        with interest.connect_sqlite(interest.STATS_DB) as db:
            after=tuple(db.execute("SELECT * FROM squad_interest_delivery WHERE session_id='legacy'").fetchone())
        self.assertEqual(before,after)
        self.assertEqual(interest.unattributed_deliveries(self.guild.id,12),1)

    async def test_dispatcher_rechecks_both_consents_and_quarantines_legacy(self):
        from cogs.squad_cards import SquadCards
        self.book.act(self.key,11,'join')
        for uid in (10,11):self.book.act(self.key,uid,'remind_on')
        for uid in (10,12):interest.toggle(self.scope,self.guild.id,uid)
        interest.reserve('dispatch',self.scope,[10,11,12],plan_users={10,11})
        self.book.act(self.key,10,'remind_off');self.book.act(self.key,11,'remind_off')
        interest.cancel(self.scope,self.guild.id,10)
        self.book.link_voice(self.key,1,20);self.book.sync_session(self.key,20,'dispatch')
        people={uid:N(id=uid,bot=False) for uid in (1,10,11,12)}
        self.guild.fetch_member=AsyncMock(side_effect=lambda uid:people[uid])
        voice=N(id=20,guild=self.guild,members=[people[1]],permissions_for=lambda _:N(view_channel=True,connect=True))
        self.channel.send=AsyncMock(return_value=N(id=900))
        self.bot.get_channel=lambda _:self.channel
        cards=object.__new__(SquadCards);cards.bot=self.bot;cards.interest_baseline=set();cards.refresh_interest_cards=AsyncMock()
        session=dict(id='dispatch',destination=100,message=500,interest_topic=interest.topic(self.guild.id,'Any game'),plan_id=self.key)
        await cards.notify_interested(voice,session)
        self.assertEqual(self.channel.send.await_args.kwargs['allowed_mentions'].to_dict(),{'users':[12],'parse':[]})
        await cards.notify_interested(voice,session)
        self.assertEqual(self.channel.send.await_count,1)
        interest.reserve('legacy-dispatch',self.scope,[11],plan_users={11})
        with interest.connect_sqlite(interest.STATS_DB) as db:
            db.execute("UPDATE squad_interest_delivery SET origins='{}' WHERE session_id='legacy-dispatch'")
        session=dict(id='legacy-dispatch',destination=100,message=500,interest_topic=interest.topic(self.guild.id,'Any game'))
        await cards.notify_interested(voice,session)
        self.assertEqual(self.channel.send.await_count,1)
        self.assertEqual(interest.pending_deliveries('legacy-dispatch',self.scope),[(0,[11])])

    async def test_browse_temporary_error_clears_details_and_retains_back(self):
        from features.plan_browse_ui import browse
        self.guild.fetch_roles.side_effect=OSError('offline')
        await browse(self.plans,self.i)
        result=self.i.edit_original_response.await_args.kwargs
        self.assertIn('不代表沒有',result['embed'].description)
        self.assertEqual(len(result['embed'].fields),0)
        self.assertIn('返回主選單',[b.label for b in result['view'].children])


class Authority(unittest.IsolatedAsyncioTestCase):
    def setup_roles(self):
        client=discord.Client(intents=discord.Intents.none());state=client._connection;gid=config.GUILD_ID
        guild=discord.Guild(state=state,data={'id':str(gid),'name':'fixture','owner_id':'999','roles':[
            {'id':str(gid),'name':'@everyone','permissions':'0'},
            {'id':'77','name':'Admin','permissions':str(discord.Permissions(administrator=True).value)}]})
        member=discord.Member(data={'user':{'id':'10','username':'fixture','discriminator':'0','avatar':None},'roles':['77'],'joined_at':None,'flags':0},guild=guild,state=state)
        revoked=discord.Role(guild=guild,state=state,data={'id':'77','name':'Admin','permissions':'0'})
        return guild,member,revoked

    async def test_admin_report_and_roster_filter_use_latest_role_definition(self):
        from core.private_source import fresh_member, visible_people
        from cogs.community_outcomes import CommunityOutcomes
        guild,member,revoked=self.setup_roles()
        inter=N(guild_id=guild.id,guild=guild,user=member)
        with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)),patch.object(discord.Guild,'fetch_roles',AsyncMock(return_value=[guild.default_role,revoked])):
            current=await fresh_member(guild,member.id)
            self.assertFalse(current.guild_permissions.administrator)
            self.assertFalse(await CommunityOutcomes.authorized(N(),inter))
            channel=discord.TextChannel(state=guild._state,guild=current.guild,data={'id':'100','name':'source','type':0,'position':0,'permission_overwrites':[]})
            self.assertEqual(await visible_people(guild,channel,[10]),[])
        self.assertTrue(member.guild_permissions.administrator)

    async def test_health_revocation_during_read_and_embed_limits(self):
        from cogs.bot_health import BotHealth
        guild,member,revoked=self.setup_roles()
        def cog(name):
            if name=='CommunityOutcomes':return N(health_status=lambda:dict(available=True,heartbeat=1,error='PRIVATE RAW ERROR'))
            if name in ('RSSDelivery','StreamAlerts'):return N(health_snapshot=lambda:dict(observations={str(n):dict(pending=True,result='uncertain',attempt=1) for n in range(100)}))
            return None
        bot=N(get_cog=cog)
        i=N(guild_id=guild.id,guild=guild,user=member,response=N(defer=AsyncMock()),edit_original_response=AsyncMock(),followup=N(send=AsyncMock()))
        with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)),patch.object(discord.Guild,'fetch_roles',AsyncMock(return_value=list(guild.roles))),patch('cogs.bot_health.storage_health',return_value={}):
            await BotHealth(bot).menu_entry(i)
            e=i.followup.send.await_args.kwargs['embed']
            self.assertNotIn('PRIVATE RAW ERROR',str(e.to_dict()))
            self.assertLessEqual(len(e.fields),25);self.assertLessEqual(len(e),6000)
            self.assertTrue(all(len(f.value)<=1024 for f in e.fields))
        i.followup.send.reset_mock()
        with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)),patch.object(discord.Guild,'fetch_roles',AsyncMock(side_effect=[list(guild.roles),[guild.default_role,revoked]])),patch('cogs.bot_health.storage_health',return_value={}):
            await BotHealth(bot).menu_entry(i)
            i.followup.send.assert_not_awaited()
            self.assertIsNone(i.edit_original_response.await_args.kwargs['embed'])
