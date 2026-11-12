import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from core.audit_monitor import IncidentCard, findings
from core.community_audit import AuditStore
from core.sqlite_storage import connect_sqlite
from features.audit_review import AuditView, RetryConfirmation, apply_review, open_reviews
from cogs.community_audit import CommunityAudit


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'card.json'
        self.channel=NS(send=AsyncMock(return_value=NS(id=123)),get_partial_message=MagicMock(return_value=NS(edit=AsyncMock())))

    async def test_grace_single_alert_restart_update_and_recovery(self):
        card=IncidentCard(self.path)
        self.assertEqual(await card.publish(self.channel,['fault'],now=100),'grace')
        self.channel.send.assert_not_awaited()
        self.assertEqual(await card.publish(self.channel,['fault'],now=191),'sent')
        card=IncidentCard(self.path)
        self.assertEqual(await card.publish(self.channel,['fault'],now=220),'unchanged')
        self.assertEqual(await card.publish(self.channel,[],now=250),'updated')
        self.assertEqual(await card.publish(self.channel,[],now=280),'healthy')
        self.assertEqual(self.channel.send.await_count,1)
        self.channel.get_partial_message.assert_called_once_with(123)
        self.assertTrue(self.channel.send.await_args.kwargs['silent'])
        self.assertEqual(self.channel.send.await_args.kwargs['allowed_mentions'].to_dict()['parse'],[])

    async def test_transient_failure_does_not_send_recovery_only_card(self):
        card=IncidentCard(self.path)
        await card.publish(self.channel,['fault'],now=100)
        self.assertEqual(await card.publish(self.channel,[],now=120),'resolved_during_grace')
        self.channel.send.assert_not_awaited()
        self.assertIsNone(card.state['since'])

    async def test_uncertain_alert_is_not_sent_twice_after_restart(self):
        card=IncidentCard(self.path); self.channel.send.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError): await card.publish(self.channel,['fault'],demo=True,now=100)
        card=IncidentCard(self.path)
        self.assertEqual(await card.publish(self.channel,['fault'],demo=True,now=200),'uncertain')
        self.assertEqual(self.channel.send.await_count,1)

    async def test_alert_content_is_updated_on_same_card_for_new_incident(self):
        card=IncidentCard(self.path)
        await card.publish(self.channel,['first'],demo=True,now=100)
        await card.publish(self.channel,[],demo=True,now=110)
        await card.publish(self.channel,['second'],demo=True,now=200)
        self.assertEqual(self.channel.send.await_count,1)
        self.assertEqual(self.channel.get_partial_message.return_value.edit.await_count,2)

    def test_health_thresholds(self):
        health={'states':{'pending':101,'uncertain':1},'oldest_pending':1,'oldest_sending':2}
        self.assertEqual(len(findings(health,sender_running=False,heartbeat=0,write_failed=True,now=500)),6)
        self.assertEqual(findings({'states':{},'oldest_pending':None,'oldest_sending':None},sender_running=True,heartbeat=400,write_failed=False,now=500),[])


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=AuditStore(Path(self.tmp.name)/'audit.sqlite3')
        self.store.append('voice',{'title':'test','description':'body'},key='test')
        self.store.claim(['test']); self.store.finish(['test'],'uncertain',error='timeout')
        self.cog=NS(store=self.store,authorized=AsyncMock(return_value=True),emit=AsyncMock())
        self.inter=NS(user=NS(id=77),response=NS(defer=AsyncMock(),send_message=AsyncMock(),edit_message=AsyncMock()),followup=NS(send=AsyncMock()))

    async def test_atomic_receipt_stale_button_and_owner_access(self):
        await apply_review(self.cog,self.inter,'test','ack')
        await apply_review(self.cog,self.inter,'test','retry')
        with connect_sqlite(self.store.path) as db:
            self.assertEqual(db.execute('SELECT event,actor,action FROM audit_reviews').fetchall(),[('test',77,'ack')])
        self.assertEqual(self.cog.emit.await_count,1)
        view=AuditView(self.cog,77)
        self.inter.guild=NS(get_member=lambda _:object()); self.inter.guild_id=config.GUILD_ID
        with patch('features.audit_review.is_server_admin',return_value=True):
            self.assertTrue(await view.interaction_check(self.inter))
            self.inter.user.id=88
            self.assertFalse(await view.interaction_check(self.inter))
        view.stop()

    async def test_revoked_admin_cannot_resolve(self):
        self.cog.authorized.return_value=False
        await apply_review(self.cog,self.inter,'test','ack')
        self.assertIsNotNone(self.store.get_review('test'))
        self.inter.response.defer.assert_not_awaited()

    async def test_review_select_and_retry_requires_second_button(self):
        await open_reviews(self.cog,self.inter)
        view=self.inter.followup.send.await_args.kwargs['view']
        self.assertEqual(view.children[0].options[0].value,'test')
        self.assertIsNotNone(self.store.get_review('test'))
        view.stop()
        confirm=RetryConfirmation(self.cog,77,'test')
        self.assertIn('確認重試',confirm.children[0].label)
        await confirm.children[1].callback(self.inter)
        self.assertIsNotNone(self.store.get_review('test'))
        confirm.stop()

    def test_sending_age_uses_claim_time_and_schema_migration(self):
        self.store.append('voice',{'title':'a'},key='old',now=time.time()-500)
        self.store.claim(['old'])
        self.assertLess(time.time()-self.store.health()['oldest_sending'],10)
        AuditStore(self.store.path)
        self.assertEqual(len(self.store.review_rows()),2)


class EventCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_transitions_duration_and_self_mute_noise(self):
        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        member=NS(id=77,bot=False,guild=NS(id=config.GUILD_ID))
        room=NS(id=1,name='one'); other=NS(id=2,name='two')
        def state(channel,**kw):return NS(channel=channel,mute=False,deaf=False,self_stream=False,self_video=False,**kw)
        await cog.on_voice_state_update(member,state(None),state(room))
        await cog.on_voice_state_update(member,state(room),state(other))
        await cog.on_voice_state_update(member,state(other),state(None))
        self.assertEqual([a.args[1] for a in cog.emit.await_args_list],['加入語音','切換語音','離開語音'])
        self.assertIn('停留約',cog.emit.await_args_list[1].args[2])
        await cog.on_voice_state_update(member,state(None),state(None,self_mute=True))
        self.assertEqual(cog.emit.await_count,3)

    async def test_member_role_and_nickname_change_are_one_event(self):
        cog=CommunityAudit(NS()); cog.emit=AsyncMock(); guild=NS(id=config.GUILD_ID)
        before=NS(id=77,guild=guild,nick='before',roles=[NS(id=1,name='one')],pending=False,timed_out_until=None)
        after=NS(id=77,guild=guild,nick='after',roles=[NS(id=2,name='two')],pending=False,timed_out_until=None)
        await cog.on_member_update(before,after)
        self.assertEqual(cog.emit.await_count,1)
        text=cog.emit.await_args.args[2]
        self.assertIn('新增身份組',text); self.assertIn('移除身份組',text); self.assertIn('暱稱',text)
