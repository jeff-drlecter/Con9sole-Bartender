import asyncio
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from cogs.squad_cards import SquadCards
from features import squad_interest as store
from features.squad_subscription_views import SubscriptionView
from quick_bar_fakes import interaction


class SquadIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(store,'STATS_DB',Path(self.temp.name)/'stats.sqlite3');self.db.start()
        self.topic=store.topic(1,'EA FC');store.remember(self.topic)
        self.scope=self.topic['id']
        self.cfg=patch('config.GUILD_ID',1);self.cfg.start()

    def tearDown(self):
        self.cfg.stop();self.db.stop();self.temp.cleanup()

    def reserve(self,kind='once'):
        store.toggle(self.scope,1,10,kind)
        store.reserve('s',self.scope,[10],now=100)
        store.delivery_context('s',self.scope,dict(guild=1,channel=30,card=99,voice=20))

    async def test_once_reserved_is_visible_and_cancel_blocks_retry_even_after_restart(self):
        self.reserve()
        self.assertEqual(store.preferences(self.scope),{})
        self.assertEqual(store.own_preferences(1,10)[0]['kind'],'pending')
        store.cancel(self.scope,1,10)
        revision=store.claim_delivery('s',self.scope,0)
        self.assertEqual(store.delivery_users('s',self.scope,0,revision),[])
        self.assertEqual(store.own_preferences(1,10),[])
        store.finish_delivery('s',self.scope,0,retry=True,now=200,expected_revision=revision)
        newer=store.claim_delivery('s',self.scope,0)
        self.assertEqual(store.delivery_users('s',self.scope,0,newer),[])
        self.assertEqual(store.own_preferences(2,10),[])
        with self.assertRaises(ValueError):store.cancel(self.scope,2,10)

    async def test_recurring_cancel_then_resubscribe_does_not_restore_old_delivery(self):
        self.reserve('always')
        store.toggle(self.scope,1,10,'always') # source card cancellation
        revision=store.claim_delivery('s',self.scope,0)
        self.assertEqual(store.delivery_users('s',self.scope,0,revision),[])
        store.toggle(self.scope,1,10,'always')
        self.assertEqual(store.delivery_users('s',self.scope,0,revision),[])
        self.assertEqual(store.reserve('next',self.scope,[10]),[10])
        next_revision=store.claim_delivery('next',self.scope,0)
        self.assertEqual(store.delivery_users('next',self.scope,0,next_revision),[10])

    async def test_end_marker_closes_late_success_and_prevents_new_claims(self):
        self.reserve('always')
        revision=store.claim_delivery('s',self.scope,0)
        store.end_session('s')
        self.assertEqual(store.delivery_users('s',self.scope,0,revision),[])
        store.finish_delivery('s',self.scope,0,message_id=500,expected_revision=revision)
        row=store.closing_notices()[0]
        self.assertEqual(row['message_id'],500)
        self.assertEqual(store.reserve('s',self.scope,[10]),[])
        self.assertEqual(store.pending_deliveries('s',self.scope),[])
        store.notice_closed(row)
        self.assertEqual(store.closing_notices(),[])

    async def test_pending_end_is_terminal_and_definitive_failure_does_not_requeue(self):
        self.reserve()
        revision=store.claim_delivery('s',self.scope,0)
        store.end_session('s')
        store.finish_delivery('s',self.scope,0,retry=True,expected_revision=revision)
        self.assertIsNone(store.claim_delivery('s',self.scope,0))
        self.assertEqual(store.pending_deliveries('s',self.scope),[])

    async def test_uncertain_card_journal_survives_end_and_known_success_recoverable(self):
        attempt=store.begin_card_post('s',30,20)
        store.end_session('s')
        self.assertEqual(store.uncertain_card('s')['attempt'],attempt)
        with self.assertRaises(RuntimeError):store.begin_card_post('s',30,20)
        store.finish_card_post(attempt,message_id=501)
        self.assertEqual(store.latest_card_post('s'),dict(state='sent',message_id=501))
        replacement=store.begin_card_post('s',30,20)
        store.finish_card_post(replacement,rejected=True)
        self.assertIsNone(store.uncertain_card('s'))

    def cog(self):
        cog=object.__new__(SquadCards);cog.lock=asyncio.Lock();cog.state={'settings':{},'sessions':{}}
        cog.bot=MagicMock();cog.save=MagicMock();cog.interest_baseline=set()
        return cog

    async def test_close_known_notice_removes_join_and_never_mentions(self):
        self.reserve();revision=store.claim_delivery('s',self.scope,0)
        store.finish_delivery('s',self.scope,0,message_id=500,expected_revision=revision);store.end_session('s')
        message=types.SimpleNamespace(id=500,author=types.SimpleNamespace(id=42),content='[查看召人卡](https://discord.com/channels/1/30/99)',edit=AsyncMock())
        channel=types.SimpleNamespace(id=30,fetch_message=AsyncMock(return_value=message))
        cog=self.cog();cog.bot.user.id=42;cog.bot.get_channel.return_value=channel
        await cog.close_finished_notices()
        sent=message.edit.call_args.kwargs
        self.assertEqual(sent['allowed_mentions'].to_dict(),{'parse':[]})
        self.assertIsNone(sent['view'])
        self.assertEqual(sent['content'], '本局已結束 · [查看足跡](https://discord.com/channels/1/30/99)')
        self.assertEqual(store.closing_notices(),[])
        self.assertEqual(store.card_session(500),'')

    async def test_legacy_closed_notice_loses_duplicate_controls_once(self):
        self.reserve();revision=store.claim_delivery('s',self.scope,0)
        store.finish_delivery('s',self.scope,0,message_id=500,expected_revision=revision)
        store.end_session('s')
        with store.connect_sqlite(store.STATS_DB) as conn:
            conn.execute('INSERT INTO squad_closed_notices(session_id,scope,batch,message_id) VALUES(?,?,?,?)',('s',self.scope,0,500))
        # Startup may already have forgotten the old text-only notice.
        self.assertEqual(store.cards(self.scope),[])
        store.track_card(self.scope,30,99)
        message=types.SimpleNamespace(id=500,author=types.SimpleNamespace(id=42),
            content='🏁 本局已結束。[查看足跡](https://discord.com/channels/1/30/99)，可登記下次通知。',edit=AsyncMock())
        channel=types.SimpleNamespace(id=30,fetch_message=AsyncMock(return_value=message))
        cog=self.cog();cog.bot.user.id=42;cog.bot.get_channel.return_value=channel
        await cog.close_finished_notices()
        self.assertIsNone(message.edit.call_args.kwargs['view'])
        self.assertEqual([c['message_id'] for c in store.cards(self.scope)],[99])
        await cog.close_finished_notices()
        message.edit.assert_awaited_once()

    async def test_close_failure_backoff_retains_evidence_then_retries(self):
        self.reserve();r=store.claim_delivery('s',self.scope,0)
        store.finish_delivery('s',self.scope,0,message_id=500,expected_revision=r);store.end_session('s')
        row=store.closing_notices()[0]
        store.notice_close_failed(row)
        self.assertEqual(store.closing_notices(),[])
        with patch('features.squad_interest.time.time',return_value=10**12):
            self.assertEqual(store.closing_notices()[0]['message_id'],500)

    async def test_disconnected_reconcile_does_not_end_cached_sessions_and_resets_timer(self):
        cog=self.cog();cog.state['sessions']={'20':dict(id='s',qualified=100)}
        cog.bot.is_ready.return_value=False
        await cog.reconcile()
        self.assertIn('20',cog.state['sessions'])
        cog.bot.get_guild.assert_not_called()
        await cog.on_disconnect()
        self.assertIsNone(cog.state['sessions']['20']['qualified'])
        cog.save.assert_called_once()

    async def test_private_overview_checks_owner_and_only_cancels_that_owner(self):
        store.toggle(self.scope,1,10,'always');store.toggle(self.scope,1,11,'always')
        cog=self.cog();cog.menu_entry=AsyncMock()
        view=SubscriptionView(cog,1,10,store.own_preferences(1,10))
        inter=interaction();inter.user.id=11
        self.assertFalse(await view.interaction_check(inter))
        inter.user.id=10;self.assertTrue(await view.interaction_check(inter))
        select=next(c for c in view.children if isinstance(c,discord.ui.Select))
        select._values=[self.scope]
        await select.callback(inter)
        self.assertEqual(store.preferences(self.scope),{11:'always'})
        inter.client.dispatch.assert_not_called()
        view.stop()

    async def test_timeout_post_is_not_replayed_after_restart_or_empty_room(self):
        cog=self.cog();cog.state['settings']={'routes':{'40':30}}
        member=types.SimpleNamespace(id=10,display_name='A',bot=False)
        guild=types.SimpleNamespace(id=1,voice_channels=[],afk_channel=None,get_member=lambda _:None)
        channel=types.SimpleNamespace(id=20,category_id=40,category=None,guild=guild,members=[member])
        guild.voice_channels=[channel]
        destination=types.SimpleNamespace(id=30,send=AsyncMock(side_effect=TimeoutError('unknown result')),permissions_for=lambda _:types.SimpleNamespace(view_channel=True))
        cog.bot.get_channel.side_effect=lambda uid: destination if uid==30 else channel
        cog.bot.get_guild.return_value=guild
        session=dict(id='s',destination=30,started=100,qualified=100,participants={'10':'A'},interest_topic=self.topic)
        cog.state['sessions']['20']=session
        with self.assertRaises(TimeoutError):await cog.render(channel,session)
        self.assertIsNotNone(store.uncertain_card('s'))
        # A fresh cog/process sees the same independent uncertainty evidence.
        again=self.cog();again.bot=cog.bot;again.state=cog.state
        with self.assertRaises(RuntimeError):await again.render(channel,session)
        self.assertEqual(destination.send.await_count,1)
        channel.members=[]
        await again.reconcile()
        self.assertNotIn('20',again.state['sessions'])
        self.assertIsNotNone(store.uncertain_card('s'))

    async def test_restart_adopts_acknowledged_card_before_empty_room_finalization(self):
        cog=self.cog();cog.state['settings']={'routes':{'40':30}}
        guild=types.SimpleNamespace(id=1,voice_channels=[],afk_channel=None)
        cog.bot.get_guild.return_value=guild
        cog.state['sessions']['20']=dict(id='s',destination=30,started=100,participants={})
        post=store.begin_card_post('s',30,20);store.finish_card_post(post,message_id=500)
        cog.render=AsyncMock()
        await cog.reconcile()
        cog.render.assert_awaited_once()
        self.assertEqual(cog.render.call_args.args[1]['message'],500)
        self.assertTrue(cog.render.call_args.kwargs['ended'])
        self.assertNotIn('20',cog.state['sessions'])

    async def test_manual_recovery_refuses_compact_notice_then_adopts_exact_session_card(self):
        cog=self.cog();channel=types.SimpleNamespace(id=20,members=[types.SimpleNamespace(bot=False)])
        session=dict(id='s',destination=30,participants={},started=100)
        cog.state['sessions']['20']=session;cog.render=AsyncMock()
        post=store.begin_card_post('s',30,20)
        message=types.SimpleNamespace(id=500,author=types.SimpleNamespace(id=42),created_at=datetime.now(timezone.utc),embeds=[discord.Embed(title='開緊團')],
            components=[types.SimpleNamespace(children=[types.SimpleNamespace(url='https://discord.com/channels/1/20',custom_id=None)])])
        destination=types.SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        cog.bot.get_channel.return_value=destination;cog.bot.user.id=42
        inter=interaction();inter.user.guild_permissions=discord.Permissions(manage_guild=True)
        await SquadCards.squad_recover.callback(cog,inter,channel,'500')
        self.assertIsNotNone(store.uncertain_card('s'));cog.render.assert_not_awaited()
        message.components[0].children.append(types.SimpleNamespace(custom_id='squad:s',url=None))
        accepted=interaction();accepted.user.guild_permissions=discord.Permissions(manage_guild=True)
        await SquadCards.squad_recover.callback(cog,accepted,channel,'500')
        self.assertIsNone(store.uncertain_card('s'));self.assertEqual(session['message'],500)
        cog.render.assert_awaited_once()

    async def test_cancel_acknowledges_before_waiting_for_reconcile_lock(self):
        store.toggle(self.scope,1,10,'always')
        cog=self.cog();cog.menu_entry=AsyncMock()
        view=SubscriptionView(cog,1,10,store.own_preferences(1,10))
        select=next(c for c in view.children if isinstance(c,discord.ui.Select));select._values=[self.scope]
        inter=interaction()
        async with cog.lock:
            pending=asyncio.create_task(select.callback(inter))
            await asyncio.sleep(0)
            inter.response.defer.assert_awaited_once()
            self.assertFalse(pending.done())
        await pending
        self.assertEqual(store.preferences(self.scope),{})
        view.stop()


    async def test_failed_footprint_finalization_does_not_revive_ended_session(self):
        cog=self.cog();cog.state['settings']={'routes':{'40':30}}
        member=types.SimpleNamespace(id=10,display_name='A',bot=False)
        channel=types.SimpleNamespace(id=20,category_id=40,members=[])
        guild=types.SimpleNamespace(id=1,voice_channels=[channel],afk_channel=None)
        cog.bot.get_guild.return_value=guild
        old=dict(id='old',destination=30,message=500,started=100,empty_since=0,participants={'10':'A'})
        cog.state['sessions']['20']=old
        cog.render=AsyncMock(side_effect=RuntimeError('temporary footprint failure'))
        with self.assertLogs('cogs.squad_cards',level='ERROR'):
            await cog.reconcile()
        self.assertIn('ended',old)
        channel.members=[member]
        cog.render=AsyncMock()
        await cog.reconcile()
        self.assertTrue(cog.render.call_args.kwargs['ended'])
        self.assertNotIn('20',cog.state['sessions'])
        await cog.reconcile()
        self.assertNotEqual(cog.state['sessions']['20']['id'],'old')
        self.assertNotIn('message',cog.state['sessions']['20'])


    async def test_ended_state_is_durable_before_failed_render_and_restart(self):
        import json
        cog=self.cog();cog.state['settings']={'routes':{'40':30}}
        channel=types.SimpleNamespace(id=20,category_id=40,members=[])
        guild=types.SimpleNamespace(id=1,voice_channels=[channel],afk_channel=None)
        cog.bot.get_guild.return_value=guild
        cog.state['sessions']['20']=dict(id='old',destination=30,message=500,started=100,empty_since=0,participants={})
        snapshots=[]
        cog.save.side_effect=lambda:snapshots.append(json.loads(json.dumps(cog.state)))
        cog.render=AsyncMock(side_effect=RuntimeError('failed edit'))
        with self.assertLogs('cogs.squad_cards',level='ERROR'):await cog.reconcile()
        self.assertIn('ended',snapshots[-1]['sessions']['20'])
        restarted=self.cog();restarted.bot=cog.bot;restarted.state=snapshots[-1];restarted.render=AsyncMock()
        channel.members=[types.SimpleNamespace(id=10,display_name='A',bot=False)]
        await restarted.reconcile()
        self.assertTrue(restarted.render.call_args.kwargs['ended'])
        self.assertNotIn('20',restarted.state['sessions'])

    def footprint_fixture(self):
        cog=self.cog()
        original=types.SimpleNamespace(id=99,edit=AsyncMock())
        destination=types.SimpleNamespace(id=30,send=AsyncMock(return_value=types.SimpleNamespace(id=501)))
        session=dict(id='s',destination=30,message=99,started=100,ended=200,
                     participants={'10':'A','11':'B'})
        return cog,original,destination,session

    async def test_separate_footprint_retry_reuses_post_and_redirects_notice(self):
        self.reserve();rev=store.claim_delivery('s',self.scope,0)
        store.finish_delivery('s',self.scope,0,message_id=500,expected_revision=rev)
        store.end_session('s')
        cog,original,destination,session=self.footprint_fixture()
        embed=discord.Embed(title='本局已結束')
        from cogs.squad_cards import FootprintView
        view=FootprintView(cog,self.topic)
        await cog.finish_footprint(destination,original,session,embed,view,self.topic)
        await cog.finish_footprint(destination,original,session,embed,view,self.topic)
        destination.send.assert_awaited_once()
        self.assertEqual(session['message'],99)
        self.assertEqual(session['footprint'],501)
        self.assertEqual(original.edit.call_args.kwargs['content'],
                         '本局已結束 · [查看足跡](https://discord.com/channels/1/30/501)')
        self.assertIsNone(original.edit.call_args.kwargs['view'])
        self.assertEqual(destination.send.call_args.kwargs['allowed_mentions'].to_dict(),{'parse':[]})
        self.assertEqual([r['message_id'] for r in store.cards(self.scope)],[501])
        notice=types.SimpleNamespace(id=500,author=types.SimpleNamespace(id=42),
            content='[查看召人卡](https://discord.com/channels/1/30/99)',edit=AsyncMock())
        cog.bot.user.id=42
        cog.bot.get_channel.return_value=types.SimpleNamespace(id=30,fetch_message=AsyncMock(return_value=notice))
        await cog.close_finished_notices()
        self.assertIn('/501)',notice.edit.call_args.kwargs['content'])
        self.assertIsNone(notice.edit.call_args.kwargs['view'])
        view.stop()

    async def test_uncertain_footprint_send_is_not_replayed(self):
        cog,original,destination,session=self.footprint_fixture()
        destination.send.side_effect=TimeoutError('unknown result')
        with self.assertRaises(TimeoutError):
            await cog.finish_footprint(destination,original,session,discord.Embed(),None,None)
        with self.assertRaises(RuntimeError):
            await cog.finish_footprint(destination,original,session,discord.Embed(),None,None)
        destination.send.assert_awaited_once()
        self.assertIsNotNone(store.uncertain_card('s:footprint'))
        self.assertIsNone(original.edit.call_args.kwargs['view'])

    async def test_solo_or_brief_visit_does_not_post_footprint(self):
        cog,original,destination,session=self.footprint_fixture()
        session['participants']={'10':'A'}
        await cog.finish_footprint(destination,original,session,discord.Embed(),None,None)
        destination.send.assert_not_awaited()
        session['participants']['11']='B';session['ended']=120
        await cog.finish_footprint(destination,original,session,discord.Embed(),None,None)
        destination.send.assert_not_awaited()

    async def test_empty_room_grace_resets_on_rejoin(self):
        cog=self.cog();cog.state['settings']={'routes':{'40':30}}
        member=types.SimpleNamespace(id=10,display_name='A',bot=False)
        channel=types.SimpleNamespace(id=20,category_id=40,members=[])
        cog.bot.get_guild.return_value=types.SimpleNamespace(id=1,voice_channels=[channel],afk_channel=None)
        session=dict(id='s',destination=30,message=99,started=100,participants={'10':'A'})
        cog.state['sessions']['20']=session;cog.render=AsyncMock();cog.notify_interested=AsyncMock()
        with patch('cogs.squad_cards.time.time',return_value=200):await cog.reconcile()
        self.assertNotIn('ended',session)
        with patch('cogs.squad_cards.time.time',return_value=229):await cog.reconcile()
        cog.render.assert_not_awaited()
        channel.members=[member]
        with patch('cogs.squad_cards.time.time',return_value=229):await cog.reconcile()
        self.assertNotIn('empty_since',session)
        channel.members=[];cog.render.reset_mock()
        with patch('cogs.squad_cards.time.time',return_value=250):await cog.reconcile()
        with patch('cogs.squad_cards.time.time',return_value=280):await cog.reconcile()
        cog.render.assert_awaited_once()
        self.assertTrue(cog.render.call_args.kwargs['ended'])

    async def test_sandbox_command_refuses_normal_channel(self):
        cog=self.cog();inter=interaction()
        inter.user.guild_permissions=discord.Permissions(manage_guild=True)
        inter.channel=types.SimpleNamespace(category=types.SimpleNamespace(name='正式組隊區'))
        await SquadCards.test_entry(cog,inter)
        inter.response.send_message.assert_awaited_once()
        inter.response.defer.assert_not_awaited()

    async def test_subscription_window_routes_reservation_to_existing_plans(self):
        cog=self.cog()
        view=SubscriptionView(cog,1,10,[])
        button=next(b for b in view.children if b.label=='發起預約')
        self.assertEqual((button.cog_name,button.method),('SquadPlans','menu_entry'))
        feature=types.SimpleNamespace(menu_entry=AsyncMock())
        inter=interaction();inter.client.get_cog.return_value=feature
        await button.callback(inter)
        feature.menu_entry.assert_awaited_once_with(inter)
        self.assertEqual(store.preferences(self.scope),{})
        view.stop()

    def test_test_entry_uses_existing_admin_registry_and_denies_helpers(self):
        from data.menu_registry import ADMIN_MENU_ITEMS
        from core.permissions import can_use_staff_tool
        item=next(i for i in ADMIN_MENU_ITEMS if i.id=='squad_test')
        self.assertEqual((item.cog,item.method,item.admin_only),('SquadCards','test_entry',True))
        helper=MagicMock(spec=discord.Member)
        helper.guild_permissions=discord.Permissions.none()
        helper.roles=[types.SimpleNamespace(id=123,name='Helpers')]
        self.assertFalse(can_use_staff_tool(helper,'squad_test'))

    async def test_footprint_next_plan_prefills_game_mode_without_posting(self):
        from cogs.squad_cards import FootprintView
        from cogs.squad_plans import PlanForm
        cog=self.cog();view=FootprintView(cog,self.topic)
        inter=interaction();inter.permissions=discord.Permissions(view_channel=True)
        inter.message.embeds=[discord.Embed(description='🎮 EA FC · Clubs 球會\n👥 參與成員 · A、B')]
        inter.channel=MagicMock(spec=discord.TextChannel)
        inter.channel.id=30;inter.channel.category=None
        plans=types.SimpleNamespace(menu_entry=AsyncMock())
        inter.client.get_cog.return_value=plans
        with patch('cogs.squad_plans.allowed',return_value=True), patch('cogs.squad_plans.squad_channel',return_value=True):
            await view.create_next(inter)
        form=inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(form,PlanForm)
        self.assertEqual(form.game.default,'EA FC')
        self.assertEqual(form.mode.default,'Clubs 球會')
        self.assertFalse(form.start.default)
        inter.channel.send.assert_not_called()
        plans.menu_entry.assert_not_awaited()
        self.assertEqual(store.preferences(self.scope),{})
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children),4)
        view.stop()

    async def test_footprint_next_plan_rechecks_destination_permission(self):
        from cogs.squad_cards import FootprintView
        cog=self.cog();view=FootprintView(cog,self.topic)
        inter=interaction();inter.permissions=discord.Permissions(view_channel=True)
        plans=types.SimpleNamespace(menu_entry=AsyncMock())
        inter.client.get_cog.return_value=plans
        with patch('cogs.squad_plans.squad_channel',return_value=True), patch('cogs.squad_plans.allowed',return_value=False):
            await view.create_next(inter)
        inter.response.send_modal.assert_not_awaited()
        plans.menu_entry.assert_awaited_once_with(inter)
        view.stop()
