import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from cogs.community_audit import CommunityAudit
from cogs.audit_monitor import AuditMonitor
from core.audit_monitor import IncidentCard, WriteFailures, findings
from core.audit_privacy import require_private_audit_channel
from features.audit_review import MonitorConfirmation


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'monitor.json'
        self.channel=NS(send=AsyncMock(side_effect=TimeoutError()),get_partial_message=MagicMock(return_value=NS(edit=AsyncMock())))

    async def uncertain_card(self):
        card=IncidentCard(self.path)
        with self.assertRaises(TimeoutError):
            await card.publish(self.channel,['first'],demo=True,now=100)
        return card

    async def test_explicit_rebuild_survives_restart_and_preserves_no_auto_resend(self):
        await self.uncertain_card()
        card=IncidentCard(self.path)
        token=card.state['recovery_token']
        self.assertEqual(await card.publish(self.channel,['second'],demo=True,now=300),'uncertain')
        self.assertEqual(self.channel.send.await_count,1)
        self.assertFalse(card.allow_rebuild('stale',77))
        self.assertTrue(card.allow_rebuild(token,77))
        self.assertFalse(card.allow_rebuild(token,77))
        card=IncidentCard(self.path)
        self.assertEqual(card.state['reviews'][-1]['actor'],77)
        self.channel.send.side_effect=None; self.channel.send.return_value=NS(id=123)
        self.assertEqual(await card.publish(self.channel,['second'],demo=True,now=400),'sent')
        self.assertEqual(await card.publish(self.channel,[],demo=True,now=500),'updated')
        self.assertEqual(self.channel.send.await_count,2)

    async def test_legacy_uncertain_gets_recovery_token_and_failed_save_stays_blocked(self):
        card=IncidentCard(self.path); card.state={'delivery':'sending','since':100}; card.save()
        card=IncidentCard(self.path)
        token=card.state['recovery_token']
        with patch.object(card,'save',side_effect=OSError()):
            with self.assertRaises(OSError): card.allow_rebuild(token,77)
        self.assertEqual(card.state['delivery'],'uncertain')

    async def test_lost_write_stays_latched_through_success_and_restart(self):
        path=Path(self.tmp.name)/'writes.json'
        cog=CommunityAudit(NS()); cog.write_failures=WriteFailures(path)
        cog.store=NS(append=MagicMock(side_effect=[OSError('disk'),'ok','receipt']))
        with self.assertLogs('cogs.community_audit',level='ERROR'):
            await cog.emit('server','lost','event')
        await cog.emit('server','successful','event')
        self.assertTrue(cog.write_failed)
        self.assertTrue(WriteFailures(path).pending)
        self.assertTrue(findings({'states':{}},sender_running=True,heartbeat=500,write_failed=cog.write_failed,now=500))
        self.assertTrue(await cog.acknowledge_write_failures(1,77))
        self.assertFalse(WriteFailures(path).pending)
        self.assertFalse(cog.write_failed)
        cog.write_failures.record(); cog.write_failed=True
        self.assertFalse(await cog.acknowledge_write_failures(1,77))
        self.assertTrue(cog.write_failed)

    def test_counter_save_failure_keeps_in_memory_warning_and_ack_is_atomic(self):
        failures=WriteFailures()
        with patch.object(failures,'save',side_effect=OSError()):
            with self.assertRaises(OSError): failures.record()
            self.assertTrue(failures.pending)
            with self.assertRaises(OSError): failures.acknowledge(1,77)
            self.assertTrue(failures.pending)

    async def test_monitor_exposes_uncertain_card_as_error(self):
        card=await self.uncertain_card()
        monitor=object.__new__(AuditMonitor)
        audit=NS(store=NS(health=lambda:{'states':{'uncertain':1}}),deliver=NS(is_running=lambda:True),
                 heartbeat=500,write_failed=False,destination=lambda _:None)
        monitor.bot=NS(get_cog=lambda _:audit,is_ready=lambda:True)
        monitor.lock=asyncio.Lock(); monitor.card=card; monitor.destination=lambda:self.channel
        await AuditMonitor.watch.coro(monitor)
        self.assertIn('結果未明',monitor.last_error)

    async def test_confirmation_rechecks_authority_and_stale_failure_count(self):
        cog=NS(authorized=AsyncMock(return_value=False),acknowledge_write_failures=AsyncMock(return_value=False),emit=AsyncMock())
        inter=NS(user=NS(id=77),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        view=MonitorConfirmation(cog,77,'loss',None,1)
        await view.confirm.callback(inter)
        cog.acknowledge_write_failures.assert_not_awaited()
        cog.authorized.return_value=True
        await view.confirm.callback(inter)
        cog.emit.assert_not_awaited()
        view.stop()


class PrivacyTests(unittest.TestCase):
    def role(self,id,*,admin=False,bot=False):
        role=MagicMock(spec=discord.Role)
        role.id=id; role.permissions=NS(administrator=admin,manage_guild=False)
        role.is_bot_managed.return_value=bot
        return role

    def setUp(self):
        self.everyone=self.role(1); self.ordinary=self.role(2)
        self.helper=self.role(config.HELPER_ROLE_IDS[0]); self.admin=self.role(3,admin=True)
        self.bot=self.role(4,bot=True)
        self.guild=NS(roles=[self.everyone,self.ordinary,self.helper,self.admin,self.bot],members=[],owner_id=99,get_member=lambda _:None)
        self.visible=set()
        self.channel=NS(guild=self.guild,overwrites={},permissions_for=lambda t:NS(view_channel=t.id in self.visible))

    def test_non_everyone_role_allow_is_blocked_but_staff_is_allowed(self):
        self.visible={self.helper.id,self.admin.id,self.bot.id}
        require_private_audit_channel(self.channel)
        self.visible.add(self.ordinary.id)
        with self.assertRaises(RuntimeError): require_private_audit_channel(self.channel)

    def test_maintenance_does_not_inherit_helper_exception(self):
        self.visible={self.helper.id}
        with self.assertRaises(RuntimeError): require_private_audit_channel(self.channel,admin_only=True)

    def test_individual_allow_and_effective_member_permissions_are_checked(self):
        member=NS(id=77,bot=False,roles=[self.everyone,self.ordinary])
        self.guild.get_member=lambda _:member
        self.channel.overwrites={MagicMock(id=77):NS(view_channel=True)}
        with self.assertRaises(RuntimeError): require_private_audit_channel(self.channel)
        self.channel.overwrites={}; self.guild.members=[member]; self.visible={77}
        with self.assertRaises(RuntimeError): require_private_audit_channel(self.channel)
        member.roles.append(self.admin)
        require_private_audit_channel(self.channel)
