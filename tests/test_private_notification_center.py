"""02 security/UI contract tests. Fake 03 service is NOT 03 integration evidence."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import config
from cogs.squad_cards import FootprintView, ParticipantPages, InterestRosterPages
from core.private_source import Source, SourceUnavailable
from core.newcomer_routes import show_next_steps, show_route
from features import squad_interest as interest, squad_participants as participants
from features.notification_center import show_center, CenterView
from features.plan_reminder_client import query, ReminderUnavailable
from features.notification_words import text, COPY


class Fake03:
    version=1
    def __init__(self,rows):self.rows=rows;self.writes=[]
    async def list_for_member(self,guild,actor):
        assert actor==10 and guild.id==config.GUILD_ID
        return {'rows':copy.deepcopy(self.rows),'complete':True}
    async def set_for_member(self,guild,actor,key,*,enabled,expected_version):
        self.writes.append((actor,key,enabled,expected_version))
        row=next(r for r in self.rows if r['id']==key)
        if row['version']!=expected_version:return {'status':'conflict'}
        row.update(enabled=enabled,version=row['version']+'x')
        return {'status':'updated'}


class PrivateCenterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();db=Path(self.tmp.name)/'test.db'
        self.patches=[patch.object(interest,'STATS_DB',db),patch.object(participants,'STATS_DB',db)]
        for p in self.patches:p.start()
        self.members={uid:N(id=uid,bot=False,display_name=f'User {uid}',roles=[]) for uid in range(10,61)}
        self.guild=N(id=config.GUILD_ID)
        self.permissions={uid:discord.Permissions(view_channel=True,read_message_history=True,send_messages=False) for uid in self.members}
        self.channel=MagicMock(spec=discord.TextChannel);self.channel.id=100;self.channel.guild=self.guild;self.channel.nsfw=False
        self.channel.permissions_for.side_effect=lambda m:self.permissions[m.id]
        self.message=N(id=500,author=N(id=99),channel=self.channel,embeds=[])
        self.channel.fetch_message=AsyncMock(return_value=self.message)
        self.guild.fetch_roles=AsyncMock(return_value=[])
        self.guild.fetch_channel=AsyncMock(return_value=self.channel)
        async def fetch(uid):
            if uid not in self.members:raise discord.NotFound(N(status=404,reason='gone'),{'message':'gone'})
            return self.members[uid]
        self.guild.fetch_member=AsyncMock(side_effect=fetch)
        self.api=Fake03([])
        self.client=N(user=N(id=99),get_cog=lambda name:N(personal_reminders_v1=self.api) if name=='SquadPlans' else None)
        self.cog=N(lock=asyncio.Lock())
        self.topic=interest.topic(self.guild.id,'Game @everyone 原名');interest.remember(self.topic)
        interest.track_card(self.topic['id'],100,500)

    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()

    def i(self):
        return N(user=self.members[10],guild=self.guild,guild_id=self.guild.id,channel=self.channel,channel_id=100,message=self.message,client=self.client,
            response=N(is_done=lambda:False,defer=AsyncMock(),send_message=AsyncMock(),edit_message=AsyncMock()),
            followup=N(send=AsyncMock()),edit_original_response=AsyncMock(),permissions=self.permissions[10])

    def plan(self):
        return dict(id='p',game='Game 03 原名',start=2000000000,status='due',enabled=True,can_enable=False,can_disable=True,version='registration-1:revision-0',url=f'https://discord.com/channels/{self.guild.id}/100/500')

    async def test_both_rosters_revoke_then_move_and_refresh_never_emit_old_snapshot(self):
        for uid in self.members:interest.toggle(self.topic['id'],self.guild.id,uid)
        participants.save(500,self.guild.id,100,{str(uid):'old' for uid in self.members})
        i=self.i();footprint=FootprintView(None,self.topic)
        for pages in [ParticipantPages(i),InterestRosterPages(10,[],self.topic['label'],source_view=footprint,source_message=self.message)]:
            self.permissions[10].view_channel=True
            await pages.load(i);self.assertIn('<@10>',pages.embed().description)
            self.permissions[10].view_channel=False
            await pages.move(i,1)
            kw=i.edit_original_response.call_args.kwargs
            self.assertIsNone(kw['embed']);self.assertIsNone(kw['view']);self.assertEqual(pages.pages,[''])
            await pages.move(i,0);self.assertIsNone(i.edit_original_response.call_args.kwargs['embed'])

    async def test_membership_and_source_changes_are_refiltered_not_cached(self):
        participants.save(500,self.guild.id,100,{'10':'old','11':'left','12':'hidden','13':'bot'})
        i=self.i();pages=ParticipantPages(i);await pages.load(i)
        del self.members[11];self.permissions[12].view_channel=False;self.members[13].bot=True
        self.members[10].display_name='Changed @everyone'
        await pages.move(i,0)
        body=i.edit_original_response.call_args.kwargs['embed'].description
        self.assertIn('Changed',body);self.assertNotIn('@everyone',body)
        for uid in (11,12,13):self.assertNotIn(f'<@{uid}>',body)
        self.channel.fetch_message.side_effect=discord.NotFound(N(status=404,reason='gone'),{'message':'gone'})
        await pages.move(i,0);self.assertIsNone(i.edit_original_response.call_args.kwargs['embed'])

    async def test_roster_toggle_denies_before_store_write_after_revocation(self):
        i=self.i();view=FootprintView(None,self.topic)
        pages=InterestRosterPages(10,[],self.topic['label'],source_view=view,source_message=self.message)
        await pages.load(i);self.permissions[10].read_message_history=False
        await pages.children[-1].callback(i)
        self.assertEqual(interest.preferences(self.topic['id']),{})
        self.assertIsNone(i.edit_original_response.call_args.kwargs['embed'])

    async def test_four_consent_combinations_and_missing_service_are_distinct(self):
        for has_plan,has_game in [(False,False),(True,False),(False,True),(True,True)]:
            self.api.rows=[self.plan()] if has_plan else []
            interest.cancel(self.topic['id'],self.guild.id,10)
            if has_game:interest.toggle(self.topic['id'],self.guild.id,10)
            i=self.i();await show_center(self.cog,i)
            fields=i.followup.send.call_args.kwargs['embed'].fields
            self.assertEqual([f.value for f in fields],[str(int(has_plan)),str(int(has_game))])
        self.client.get_cog=lambda _:None
        i=self.i();await show_center(self.cog,i)
        self.assertIn('不代表',i.followup.send.call_args.kwargs['embed'].fields[0].value)

    async def test_mutations_are_separate_and_stale_03_version_is_forwarded_unchanged(self):
        self.api.rows=[self.plan()];interest.toggle(self.topic['id'],self.guild.id,10,'always')
        i=self.i();await show_center(self.cog,i,section='detail',key='p')
        view=i.followup.send.call_args.kwargs['view']
        self.api.rows[0].update(version='rejoined:revision-1',enabled=False)
        await view.set_plan(i,True)
        self.assertEqual(self.api.writes[-1][-1],'registration-1:revision-0')
        self.assertFalse(self.api.rows[0]['enabled']);self.assertEqual(interest.preferences(self.topic['id']),{10:'always'})
        await view.cancel_game(i,self.topic['id'])
        self.assertFalse(self.api.rows[0]['enabled']);self.assertEqual(interest.preferences(self.topic['id']),{})
        self.assertEqual(len(self.api.writes),1)

    async def test_hidden_game_label_redacted_cancel_still_only_withdraws_own_consent(self):
        interest.toggle(self.topic['id'],self.guild.id,10);interest.toggle(self.topic['id'],self.guild.id,11)
        hidden=MagicMock(spec=discord.TextChannel);hidden.guild=self.guild
        hidden.permissions_for.return_value=discord.Permissions.none()
        # Source panel remains visible; tracked card channel loses access.
        interest.track_card(self.topic['id'],200,500)
        self.guild.fetch_channel.side_effect=lambda cid:self.channel if cid==100 else hidden
        i=self.i();await show_center(self.cog,i,section='games')
        view=i.followup.send.call_args.kwargs['view']
        self.assertNotIn('Game',view.embed().description)
        await view.cancel_game(i,self.topic['id'])
        self.assertEqual(interest.preferences(self.topic['id']),{11:'once'})

    async def test_no_role_bypass_and_errors_do_not_return_empty_success(self):
        for role in ('Member','Helpers','Tester'):
            self.members[10].roles=[N(name=role,managed=True)]
            self.permissions[10].read_message_history=False
            i=self.i();await show_center(self.cog,i)
            self.assertIsNone(i.followup.send.call_args.kwargs['embed'])
        self.permissions[10].read_message_history=True
        self.guild.fetch_member.side_effect=OSError('offline')
        i=self.i();await show_center(self.cog,i)
        self.assertIsNone(i.followup.send.call_args.kwargs['embed'])

    async def test_next_steps_owner_bound_no_hidden_help_and_return_callback(self):
        self.permissions[10].send_messages=False
        i=self.i();back=AsyncMock();await show_next_steps(i,return_to=back)
        view=i.followup.send.call_args.kwargs['view']
        self.assertEqual([b.label for b in view.children],['選擇遊戲','找 Helper','先觀望','返回'])
        await view.children[1].callback(i)
        self.assertNotIn('<#',i.edit_original_response.call_args.kwargs['content'])
        await view.back(i);back.assert_awaited_once()
        i.user=self.members[11];self.assertFalse(await view.interaction_check(i))

    async def test_language_matrix_only_translates_bot_copy_and_failure_is_private(self):
        for code,name in [('neutral',None),('hk','語境偏好｜香港'),('tw','語境偏好｜台灣')]:
            m=self.members[10];m.roles=[] if not name else [N(name=name,managed=False,permissions=discord.Permissions.none())]
            for key in COPY:self.assertTrue(text(m,key,page=1,total=2))
            self.api.rows=[self.plan()]
            i=self.i();await show_center(self.cog,i,section='plans')
            self.assertIn('Game 03 原名',i.followup.send.call_args.kwargs['embed'].description)
            self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
            await show_route(i,'games')
            content=i.followup.send.call_args.kwargs['content']
            self.assertIn('揀遊戲' if code=='hk' else '選擇遊戲',content)

    async def test_pending_game_is_reported_without_creating_plan_consent(self):
        interest.toggle(self.topic['id'],self.guild.id,10,'always')
        interest.reserve('s',self.topic['id'],[10])
        i=self.i();await show_center(self.cog,i,section='games')
        self.assertIn('待處理',i.followup.send.call_args.kwargs['embed'].description)
        self.assertEqual(self.api.writes,[])

    async def test_reserved_plan_only_game_only_both_and_neither_are_separate(self):
        for session,plan,game in [('plan',True,False),('game',False,True),('both',True,True),('neither',False,False)]:
            interest.cancel(self.topic['id'],self.guild.id,10)
            if game:interest.toggle(self.topic['id'],self.guild.id,10)
            self.api.rows=[self.plan()] if plan else []
            interest.reserve(session,self.topic['id'],[10],plan_users={10} if plan else set())
            i=self.i();await show_center(self.cog,i)
            self.assertEqual([f.value for f in i.followup.send.call_args.kwargs['embed'].fields],
                             [str(int(plan)),str(int(game))])
            interest.end_session(session)

    async def test_game_withdrawal_retains_independent_plan_receipt_across_retry(self):
        interest.toggle(self.topic['id'],self.guild.id,10)
        interest.reserve('both',self.topic['id'],[10],plan_users={10})
        interest.cancel(self.topic['id'],self.guild.id,10)
        rev=interest.claim_delivery('both',self.topic['id'],0)
        # This is receipt provenance, NOT a substitute for 03's current consent check.
        self.assertEqual(interest.delivery_users('both',self.topic['id'],0,rev),[10])
        self.assertEqual(interest.own_preferences(self.guild.id,10),[])
        interest.finish_delivery('both',self.topic['id'],0,retry=True,expected_revision=rev)
        rev=interest.claim_delivery('both',self.topic['id'],0)
        self.assertEqual(interest.delivery_users('both',self.topic['id'],0,rev),[10])
        interest.end_session('both')
        self.assertEqual(interest.delivery_users('both',self.topic['id'],0,rev),[])

    async def test_legacy_receipts_are_unknown_not_game_subscriptions_or_empty_success(self):
        interest.reserve('legacy',self.topic['id'],[10],plan_users={10})
        from core.sqlite_storage import connect_sqlite
        with connect_sqlite(interest.STATS_DB) as conn:
            conn.execute("UPDATE squad_interest_delivery SET origins='{}'")
        i=self.i();await show_center(self.cog,i,section='games')
        e=i.followup.send.call_args.kwargs['embed']
        self.assertIn('未能確認',e.description);self.assertNotIn('目前沒有',e.description)
        self.assertEqual(interest.own_preferences(self.guild.id,10),[])
        self.assertEqual(interest.unattributed_deliveries(self.guild.id,10),1)

    async def test_uncertain_game_receipt_never_claims_pending_success(self):
        interest.toggle(self.topic['id'],self.guild.id,10)
        interest.reserve('uncertain',self.topic['id'],[10])
        interest.claim_delivery('uncertain',self.topic['id'],0)
        i=self.i();await show_center(self.cog,i,section='games')
        self.assertIn('結果未確認',i.followup.send.call_args.kwargs['embed'].description)
        self.assertEqual(interest.pending_deliveries('uncertain',self.topic['id']),[])

    async def test_wrong_owner_guild_channel_and_private_thread_membership_fail_closed(self):
        source=Source(10,self.guild.id,100,500)
        for attr,value in [('user',self.members[11]),('guild_id',0),('channel_id',200)]:
            i=self.i();setattr(i,attr,value)
            with self.assertRaises(SourceUnavailable):await source.resolve(i)
        thread=MagicMock(spec=discord.Thread);thread.id=100;thread.guild=self.guild;thread.parent_id=200
        thread.permissions_for.side_effect=self.channel.permissions_for.side_effect
        thread.is_private.return_value=True
        thread.fetch_member=AsyncMock(side_effect=discord.NotFound(N(status=404,reason='gone'),{'message':'gone'}))
        self.guild.fetch_channel.side_effect=lambda cid:thread if cid==100 else self.channel
        with self.assertRaises(SourceUnavailable):await source.resolve(self.i())

    async def test_rest_role_revocation_wins_over_stale_gateway_permissions(self):
        client=discord.Client(intents=discord.Intents.none())
        state=client._connection
        gid=self.guild.id
        allowed=discord.Permissions(view_channel=True,read_message_history=True).value
        data={'id':str(gid),'name':'fixture','owner_id':'999','roles':[
            {'id':str(gid),'name':'@everyone','permissions':'0'},
            {'id':'77','name':'Member','permissions':str(allowed)}]}
        guild=discord.Guild(data=data,state=state)
        member=discord.Member(data={'user':{'id':'10','username':'member','discriminator':'0','avatar':None},'roles':['77'],'joined_at':None,'flags':0},guild=guild,state=state)
        channel=discord.TextChannel(state=state,guild=guild,data={'id':'100','name':'private','type':0,'position':0,'permission_overwrites':[]})
        self.assertTrue(channel.permissions_for(member).view_channel)
        revoked=discord.Role(guild=guild,state=state,data={'id':'77','name':'Member','permissions':'0'})
        i=self.i();i.guild=guild
        with patch.object(discord.Guild,'fetch_member',AsyncMock(return_value=member)), \
             patch.object(discord.Guild,'fetch_channel',AsyncMock(return_value=channel)), \
             patch.object(discord.Guild,'fetch_roles',AsyncMock(return_value=[guild.default_role,revoked])):
            with self.assertRaises(SourceUnavailable):await Source(10,gid,100).resolve(i)
        # The permission snapshot never mutates the shared gateway objects.
        self.assertTrue(channel.permissions_for(member).view_channel)

    async def test_paused_squad_feature_offers_checked_next_steps(self):
        from features.drink_views import FeatureButton
        self.client.get_cog=lambda _:None
        for name in ('SquadCards','SquadPlans'):
            i=self.i()
            await FeatureButton(label='entry',emoji='🎮',cog=name,method='menu_entry',row=0).callback(i)
            result=i.followup.send.call_args.kwargs
            self.assertIn('暫時',result['content'])
            self.assertEqual([b.label for b in result['view'].children],['選擇遊戲','找 Helper','先觀望','返回'])
