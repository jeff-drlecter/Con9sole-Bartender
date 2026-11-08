import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock,patch
from features import squad_interest as interests
from features import notification_review as review
from features.community_levels import Ledger
from features.notification_review_views import ResolveModal,ReviewList,permitted


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(interests,'STATS_DB',Path(self.temp.name)/'stats')
        self.dbpatch.start()
        self.ledger=Ledger(Path(self.temp.name)/'levels')
        self.ledger.configure(1,mode='active')
        self.topic=interests.topic(1,'Game');interests.remember(self.topic)
        interests.toggle(self.topic['id'],1,10)
        interests.reserve('session',self.topic['id'],[10])
        interests.delivery_context('session',self.topic['id'],dict(channel=30,card=40,guild=1))

    def tearDown(self):self.dbpatch.stop();self.temp.cleanup()

    def row(self):return review.subscription_rows(1)[0]

    async def test_retry_rotates_revision_and_rejects_old_panel_and_ack(self):
        revision=interests.claim_delivery('session',self.topic['id'],0)
        row=self.row()
        self.assertTrue(review.resolve(self.ledger,1,row,'retry',20,'checked original channel'))
        self.assertFalse(review.resolve(self.ledger,1,row,'retry',20,'stale click'))
        new=interests.claim_delivery('session',self.topic['id'],0)
        interests.finish_delivery('session',self.topic['id'],0,message_id=999,expected_revision=revision)
        self.assertEqual(self.row()['revision'],new)
        interests.finish_delivery('session',self.topic['id'],0,message_id=1000,expected_revision=new)
        self.assertEqual(review.subscription_rows(1),[])

    async def test_scope_and_sent_record_cannot_be_rearmed(self):
        row=self.row()
        self.assertEqual(review.subscription_rows(2),[])
        self.assertFalse(review.resolve(self.ledger,2,row,'retry',20,'wrong guild'))
        self.assertTrue(review.resolve(self.ledger,1,row,'sent',20,'verified proof',100))
        self.assertFalse(review.resolve(self.ledger,1,row,'retry',20,'stale panel'))
        forged={**row,'state':'sent'}
        self.assertFalse(review.resolve(self.ledger,1,forged,'retry',20,'invalid transition'))

    async def test_resolution_audit_is_durable(self):
        row=self.row()
        with self.assertRaises(ValueError):review.resolve(self.ledger,1,row,'sent',20,'proof missing')
        with self.assertRaises(ValueError):review.resolve(self.ledger,1,row,'retry',20,'')
        self.assertTrue(review.resolve(self.ledger,1,row,'sent',20,'checked link',123))
        from core.sqlite_storage import connect_sqlite
        with connect_sqlite(interests.STATS_DB) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notification_reviews WHERE guild=1').fetchone()[0],1)

    async def test_weekly_resolution_fences_old_ack_and_preserves_other_settings(self):
        old=self.ledger.begin_weekly_publication(1,'2026-W45')
        self.ledger.finish_weekly_publication(1,'2026-W45',old['attempt'],'uncertain')
        row=review.weekly_rows(self.ledger,1)[0]
        self.assertTrue(review.resolve(self.ledger,1,row,'retry',20,'confirmed no publication'))
        current=self.ledger.begin_weekly_publication(1,'2026-W45')
        self.ledger.finish_weekly_publication(1,'2026-W45',old['attempt'],'sent',100)
        self.assertEqual(self.ledger.settings(1)['weekly_publications']['2026-W45']['attempt'],current['attempt'])
        self.assertEqual(self.ledger.settings(1)['mode'],'active')
        self.assertFalse(review.resolve(self.ledger,1,row,'retry',20,'old panel'))

    async def test_modal_rechecks_permission_before_any_write(self):
        modal=ResolveModal(20,self.row(),'retry')
        inter=types.SimpleNamespace(user=types.SimpleNamespace(id=21),guild_id=1,guild=None,response=types.SimpleNamespace(send_message=AsyncMock()))
        with patch('features.notification_review_views.store.resolve') as mutate:
            await modal.on_submit(inter)
        mutate.assert_not_called();inter.response.send_message.assert_awaited_once()

    async def test_stopped_session_does_not_rearm_subscription(self):
        modal=ResolveModal(20,self.row(),'retry');modal.reason=types.SimpleNamespace(value='checked')
        levels=types.SimpleNamespace(ledger=self.ledger)
        inter=MagicMock();inter.guild_id=1;inter.user.id=20
        inter.client.get_cog.side_effect=lambda name:levels if name=='CommunityLevels' else types.SimpleNamespace(state={'sessions':{}})
        with patch('features.notification_review_views.permitted',AsyncMock(return_value=True)):
            with self.assertRaisesRegex(ValueError,'已結束'):
                await modal.apply(inter)
        self.assertEqual(self.row()['state'],'pending')

    async def test_proof_rejects_other_guild_or_other_bot_message(self):
        modal=ResolveModal(20,self.row(),'sent')
        inter=MagicMock();inter.guild_id=1
        modal.link=types.SimpleNamespace(value='https://discord.com/channels/2/30/100')
        with self.assertRaisesRegex(ValueError,'本伺服器'):await modal.proof(inter,None)
        modal.link=types.SimpleNamespace(value='https://discord.com/channels/1/30/100')
        channel=MagicMock();channel.permissions_for.return_value.view_channel=True
        channel.fetch_message=AsyncMock(return_value=types.SimpleNamespace(author=types.SimpleNamespace(id=200)))
        inter.guild.get_channel_or_thread.return_value=channel;inter.client.user.id=201
        with self.assertRaisesRegex(ValueError,'本 Bot'):await modal.proof(inter,None)

    async def test_empty_and_paginated_views_fit_mobile_rows(self):
        for rows in ([],[self.row() for _ in range(25)]):
            view=ReviewList(20,rows)
            self.assertLessEqual(len(view.children),5)
            for item in view.children:
                if isinstance(item, __import__('discord').ui.Select):self.assertLessEqual(len(item.options),10)
            view.stop()

    async def test_proof_checks_the_actual_recipient_batch(self):
        modal=ResolveModal(20,self.row(),'sent')
        modal.link=types.SimpleNamespace(value='https://discord.com/channels/1/30/100')
        message=types.SimpleNamespace(id=100,author=types.SimpleNamespace(id=201),
            content='https://discord.com/channels/1/30/40',mentions=[types.SimpleNamespace(id=11)])
        channel=MagicMock();channel.id=30;channel.permissions_for.return_value.view_channel=True
        channel.fetch_message=AsyncMock(return_value=message)
        inter=MagicMock();inter.guild_id=1;inter.client.user.id=201
        inter.guild.get_channel_or_thread.return_value=channel
        with self.assertRaisesRegex(ValueError,'收件名單'):await modal.proof(inter,None)
        message.mentions=[types.SimpleNamespace(id=10)]
        self.assertEqual(await modal.proof(inter,None),100)

    async def test_old_weekly_claim_can_be_reviewed_without_resending(self):
        self.ledger.claim_weekly_notice(1,'2026-W44')
        row=review.weekly_rows(self.ledger,1)[0]
        self.assertEqual(row['revision'],'legacy')
        self.assertTrue(review.resolve(self.ledger,1,row,'sent',20,'checked actual message',123))
        self.assertEqual(review.weekly_rows(self.ledger,1),[])

    async def test_cancelled_notification_is_not_marked_sent_or_rearmed(self):
        row=self.row()
        self.assertTrue(review.resolve(self.ledger,1,row,'cancel',20,'session ended'))
        self.assertEqual(review.subscription_rows(1),[])
        self.assertIsNone(interests.claim_delivery('session',self.topic['id'],0))
        self.assertFalse(review.resolve(self.ledger,1,row,'retry',20,'stale panel'))

    async def test_review_waits_for_existing_subscription_delivery(self):
        from core.action_guard import shared_async_lock
        modal=ResolveModal(20,self.row(),'retry');modal.reason=types.SimpleNamespace(value='checked')
        channel=types.SimpleNamespace(id=50,members=[types.SimpleNamespace(bot=False)])
        session={'id':'session','destination':30}
        squad=types.SimpleNamespace(state={'sessions':{'50':session}},_notify_interested_locked=AsyncMock())
        levels=types.SimpleNamespace(ledger=self.ledger)
        inter=MagicMock();inter.guild_id=1;inter.user.id=20
        inter.followup.send=AsyncMock();inter.guild.get_channel.return_value=channel
        inter.client.get_cog.side_effect=lambda name:levels if name=='CommunityLevels' else squad
        lock=shared_async_lock('subscription-delivery',1,'session')
        await lock.acquire()
        with patch('features.notification_review_views.permitted',AsyncMock(return_value=True)),patch('cogs.squad_cards.interest_topic',return_value={'id':self.topic['id']}),patch('features.notification_review_views.store.resolve',return_value=True) as mutate:
            task=asyncio.create_task(modal.apply(inter))
            await asyncio.sleep(0)
            mutate.assert_not_called()
            lock.release()
            await task
            mutate.assert_called_once()
        squad._notify_interested_locked.assert_awaited_once_with(channel,session,retry_batch=0)
