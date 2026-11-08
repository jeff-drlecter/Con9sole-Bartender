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
        self.assertFalse(any(getattr(b,'url',None) for b in sent['view'].children))
        self.assertEqual(store.closing_notices(),[])
        self.assertEqual(store.card_session(500),'')

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
