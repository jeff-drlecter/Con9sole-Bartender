import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import unittest
import discord
from features.permission_audit import permissions
from features.verified_access_preview import preview


def role(rid,name=None,managed=False,bot=False,**kw):
    return dict(id=str(rid),name=name or str(rid),managed=managed,bot_managed=bot,permissions=permissions(discord.Permissions(**kw).value))


def ow(rid,allow=None,deny=None,kind='role'):
    return dict(id=str(rid),type=kind,allow=permissions(discord.Permissions(**(allow or {})).value),deny=permissions(discord.Permissions(**(deny or {})).value))


def snapshot():
    return dict(captured_at='now',guild=dict(id='1'),roles=[role(1),role(2,'off-topic'),role(3,'PGA',attach_files=True,embed_links=True),role(10,'Verified',attach_files=True,embed_links=True)],
        channels=[dict(id='20',name='public',type='text',overwrites=[ow(1,deny=dict(view_channel=True,send_messages=True)),ow(2,allow=dict(view_channel=True,send_messages=True))])],onboarding=dict(status='unavailable'))


class PreviewTests(unittest.TestCase):
    def test_pair_witness_and_only_capability_bits_proposed(self):
        s=snapshot();original=copy.deepcopy(s);result=preview(s,10)
        witness=result['findings'][0]['witnesses']['attach_files']
        self.assertEqual(set(witness['role_ids']),{'2','3'})
        self.assertEqual(witness['base_grant_roles'],['3'])
        self.assertEqual(s,original)
        mask=discord.Permissions(attach_files=True,embed_links=True).value
        for op in result['proposals'][0]['operations']:
            a,b=map(int,op['before']);c,d=map(int,op['after'])
            self.assertEqual(((a^c)|(b^d)) & ~mask,0)
        self.assertFalse(result['proposals'][0]['apply_supported'])

    def test_explicit_verified_deny_stays_manual(self):
        s=snapshot();s['channels'][0]['overwrites'].append(ow(10,deny=dict(attach_files=True)))
        result=preview(s,10)
        self.assertFalse(result['proposals'])
        self.assertEqual(result['exceptions'][0]['kind'],'verified_explicit_deny_preserved')

    def test_managed_humans_included_bots_and_staff_excluded(self):
        s=snapshot();s['roles'][2]['managed']=True
        s['roles'] += [role(4,managed=True,bot=True,attach_files=True),role(5,manage_guild=True,attach_files=True)]
        result=preview(s,10)
        self.assertEqual(result['ordinary_role_count'],2)
        self.assertTrue(result['findings'])

    def test_readonly_no_false_channel_send_witness(self):
        s=snapshot();s['channels'][0]['overwrites'][1]['allow']=permissions(discord.Permissions(view_channel=True).value)
        self.assertFalse(preview(s,10)['findings'])
        s['roles'][1]['permissions']=permissions(discord.Permissions(send_messages_in_threads=True).value)
        result=preview(s,10)
        self.assertEqual(result['findings'][0]['witnesses']['attach_files']['surface'],'thread_reply_candidate')

    def test_member_overwrites_do_not_become_role_witnesses(self):
        s=snapshot();s['channels'][0]['overwrites'].append(ow(7,allow=dict(attach_files=True),kind='member'))
        result=preview(s,10)
        self.assertEqual(result['exceptions'][0]['kind'],'member_overwrite_requires_membership_review')
        self.assertNotIn('7',result['findings'][0]['witnesses']['attach_files']['role_ids'])


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_actor_does_not_collect(self):
        from cogs.permission_audit import PermissionAudit
        cog=PermissionAudit(None);inter=NS(response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        with patch.object(cog,'authorized',AsyncMock(return_value=False)),patch('cogs.permission_audit.collect',AsyncMock()) as read:
            await PermissionAudit.verified_preview.callback(cog,inter)
        read.assert_not_awaited()

    async def test_revocation_prevents_attachment_delivery(self):
        from cogs.permission_audit import PermissionAudit
        cog=PermissionAudit(None);inter=NS(guild=NS(),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        with patch.object(cog,'authorized',AsyncMock(side_effect=[True,False])),patch('cogs.permission_audit.collect',AsyncMock(return_value=snapshot())):
            await PermissionAudit.verified_preview.callback(cog,inter)
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)
