import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from features import anti_scam_monitor as m


def rule(payload,rid=12):
    raw=copy.deepcopy(payload)
    return NS(id=rid,name=raw['name'],enabled=raw['enabled'],creator_id=99,
        trigger=NS(type=NS(value=raw['trigger_type'])),to_dict=lambda:raw)


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(m,'PATH',Path(self.tmp.name)/'monitor.db');p.start();self.addCleanup(p.stop)
        self.guild=NS(id=1,me=NS(id=99),fetch_roles=AsyncMock(return_value=[NS(id=10)]),fetch_channels=AsyncMock(return_value=[]),fetch_automod_rules=AsyncMock(),create_automod_rule=AsyncMock())

    async def test_enable_creates_alert_only_and_repeated_enable_no_duplicate(self):
        rules=[]
        async def fetch():return list(rules)
        async def create(**kwargs):
            payload=next(p for p in m.desired(10) if p['name']==kwargs['name'])
            self.assertEqual([a.to_dict()['type'] for a in kwargs['actions']],[2])
            r=rule(payload,12+len(rules));rules.append(r);return r
        self.guild.fetch_automod_rules.side_effect=fetch;self.guild.create_automod_rule.side_effect=create
        with patch.object(m,'private_alert'):
            result=await m.run(self.guild,10,AsyncMock(return_value=True),'enable')
            await m.run(self.guild,10,AsyncMock(return_value=True),'enable')
        self.assertEqual(len(result),2);self.assertEqual(self.guild.create_automod_rule.await_count,2)
        self.assertTrue(all(m.receipt(1,p['name'])['state']=='enabled' for p in m.desired(10)))

    async def test_timeout_never_blindly_recreates(self):
        self.guild.fetch_automod_rules.return_value=[]
        self.guild.create_automod_rule.side_effect=RuntimeError('timeout')
        with patch.object(m,'private_alert'):
            with self.assertRaises(RuntimeError):await m.run(self.guild,10,AsyncMock(return_value=True),'enable')
            with self.assertRaises(ValueError):await m.run(self.guild,10,AsyncMock(return_value=True),'enable')
        self.assertEqual(self.guild.create_automod_rule.await_count,1)

    async def test_same_name_without_receipt_not_adopted(self):
        self.guild.fetch_automod_rules.return_value=[rule(m.desired(10)[0])]
        with patch.object(m,'private_alert'):
            with self.assertRaises(ValueError):await m.run(self.guild,10,AsyncMock(return_value=True),'enable')
        self.guild.create_automod_rule.assert_not_awaited()

    async def test_permission_revoked_before_create(self):
        self.guild.fetch_automod_rules.return_value=[]
        with patch.object(m,'private_alert'):
            with self.assertRaises(ValueError):await m.run(self.guild,10,AsyncMock(return_value=False),'enable')
        self.guild.create_automod_rule.assert_not_awaited()

    def test_block_action_or_verified_spam_exemption_rejected(self):
        p=m.desired(10)[1];bad=copy.deepcopy(p);bad['actions']=[dict(type=1)]
        self.assertFalse(m.matches(rule(bad),p))
        bad=copy.deepcopy(p);bad['exempt_roles']=['10']
        self.assertFalse(m.matches(rule(bad),p))

    def test_public_alert_destination_rejected(self):
        roles=[NS(id=1,managed=False,permissions=discord.Permissions(view_channel=True))]
        channel=discord.TextChannel(state=MagicMock(),guild=NS(id=1),data=dict(id=str(m.ALERT_CHANNEL),type=0,name='public',position=0,permission_overwrites=[]))
        with self.assertRaises(ValueError):m.private_alert(1,roles,channel)

    async def test_status_has_no_create_or_edit(self):
        self.guild.fetch_automod_rules.return_value=[]
        rows=await m.run(self.guild,10,AsyncMock(return_value=True),'status')
        self.assertEqual(len(rows),2);self.guild.create_automod_rule.assert_not_awaited()


    def test_real_discord_spam_rule_has_null_metadata(self):
        payload=m.desired(10)[1]
        raw={**payload,'id':'12','creator_id':'99','guild_id':'1','trigger_metadata':None}
        real=discord.AutoModRule(data=raw,guild=NS(id=1),state=MagicMock())
        self.assertIsNone(real.to_dict()['trigger_metadata'])
        self.assertTrue(m.matches(real,payload))


    def test_managed_human_role_is_not_privacy_exempt(self):
        roles=[NS(id=1,managed=False,permissions=discord.Permissions.none()),NS(id=7,managed=True,is_bot_managed=lambda:False,permissions=discord.Permissions(view_channel=True))]
        channel=discord.TextChannel(state=MagicMock(),guild=NS(id=1),data=dict(id=str(m.ALERT_CHANNEL),type=0,name='staff',position=0,permission_overwrites=[]))
        with self.assertRaises(ValueError):m.private_alert(1,roles,channel)
