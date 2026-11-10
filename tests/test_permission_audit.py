import io
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
import zipfile
import discord
from features.permission_audit import permissions,role_permissions,collect,archive,overwrite_rows,analyze
from cogs.permission_audit import PermissionAudit


def role(rid,**flags):
    return {'id':str(rid),'name':str(rid),'permissions':permissions(discord.Permissions(**flags).value)}


def ow(rid,kind='role',allow=None,deny=None):
    return {'id':str(rid),'type':kind,'allow':permissions(discord.Permissions(**(allow or {})).value),'deny':permissions(discord.Permissions(**(deny or {})).value)}


class Calculations(unittest.TestCase):
    def test_role_allow_wins_over_other_role_deny_but_member_not_assumed(self):
        roles=[role(1,view_channel=True),role(2),role(3)]
        channel={'overwrites':[ow(2,deny={'send_messages':True}),ow(3,allow={'send_messages':True}),ow(9,'member',deny={'send_messages':True})]}
        self.assertTrue(role_permissions(roles,channel,1,[2,3]).send_messages)
        self.assertFalse(role_permissions(roles,channel,1,[2]).send_messages)

    def test_admin_bypasses_overwrites(self):
        p=role_permissions([role(1),role(2,administrator=True)],{'overwrites':[ow(1,deny={'view_channel':True})]},1,[2])
        self.assertTrue(p.view_channel)

    def test_uncached_member_and_role_overwrites_preserved(self):
        channel=NS(overwrites={discord.Object(10,type=discord.Role):discord.PermissionOverwrite(view_channel=True),discord.Object(20,type=discord.User):discord.PermissionOverwrite(send_messages=False)})
        self.assertEqual([(r['type'],r['id']) for r in overwrite_rows(channel)],[('member','20'),('role','10')])

    def test_ptt_is_policy_difference_not_security_bug(self):
        s={'guild':{'id':'1'},'roles':[role(1,view_channel=True,connect=True,speak=True),role(2)],'channels':[dict(id='3',category_id=None,type='voice',name='vc',overwrites=[])],'onboarding':{'status':'unavailable'}}
        findings=analyze(s,2)
        self.assertEqual([(r['code'],r['severity']) for r in findings],[('UNVERIFIED_PTT','policy')])


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_and_archive_with_missing_optional_endpoints(self):
        state=MagicMock()
        guild=NS(id=1,name='test',owner_id=7,verification_level=discord.VerificationLevel.low,
            features=[],mfa_level=discord.MFALevel.disabled,explicit_content_filter=discord.ContentFilter.disabled,
            members=[],member_count=4)
        r=discord.Role(guild=guild,state=state,data={'id':'1','name':'@everyone','permissions':'0','position':0,'color':0})
        vc=discord.VoiceChannel(state=state,guild=guild,data={'id':'3','name':'vc','type':2,'position':0,'permission_overwrites':[],'bitrate':64000,'user_limit':0,'video_quality_mode':1})
        guild.fetch_roles=AsyncMock(return_value=[r]);guild.fetch_channels=AsyncMock(return_value=[vc])
        s=await collect(guild,2)
        self.assertEqual(s['onboarding']['status'],'unsupported')
        self.assertEqual(s['channels'][0]['video_quality_mode'],1)
        with zipfile.ZipFile(archive(s)) as z:
            decoded=json.loads(z.read('permission-audit.json'))
            self.assertEqual(decoded['channels'][0]['id'],'3')
            self.assertIn('threads',decoded['coverage'])
        guild.fetch_roles.assert_awaited_once();guild.fetch_channels.assert_awaited_once()

    async def test_forbidden_optional_endpoint_keeps_core_snapshot(self):
        guild=NS(id=1,name='g',owner_id=7,verification_level=0,features=[],mfa_level=0,
            explicit_content_filter=0,members=[],member_count=0,
            fetch_roles=AsyncMock(return_value=[]),fetch_channels=AsyncMock(return_value=[]),
            onboarding=AsyncMock(side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),{'message':'Denied','code':0})))
        s=await collect(guild,2)
        self.assertEqual(s['onboarding'],{'status':'unavailable','http_status':403})

    async def test_denied_actor_cannot_collect(self):
        inter=NS(response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        cog=PermissionAudit(None)
        with patch.object(cog,'authorized',AsyncMock(return_value=False)),patch('cogs.permission_audit.collect',AsyncMock()) as read:
            await cog.menu_entry(inter)
            read.assert_not_awaited()
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])

    async def test_revoked_actor_does_not_receive_archive(self):
        inter=NS(response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()),guild=NS(filesize_limit=1000000))
        cog=PermissionAudit(None)
        with patch.object(cog,'authorized',AsyncMock(side_effect=[True,False])),patch('cogs.permission_audit.collect',AsyncMock(return_value={})),patch('cogs.permission_audit.archive',return_value=io.BytesIO(b'zip')):
            await cog.menu_entry(inter)
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)


    async def test_onboarding_preserves_option_ids_and_snowflakes(self):
        guild=NS(id=1,name='g',owner_id=7,verification_level=0,features=[],mfa_level=0,
            explicit_content_filter=0,members=[],member_count=0,
            fetch_roles=AsyncMock(return_value=[]),fetch_channels=AsyncMock(return_value=[]))
        option=discord.OnboardingPromptOption.from_dict(data=dict(id='123456789012345678',description='',title='FC',role_ids=['987654321012345678'],channel_ids=['555555555555555555']),state=MagicMock(),guild=guild)
        prompt=discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice,title='Games',options=[option])
        prompt.id=444444444444444444
        guild.onboarding=AsyncMock(return_value=NS(enabled=True,mode=discord.OnboardingMode.default,default_channel_ids=set(),prompts=[prompt]))
        s=await collect(guild,2)
        result=s['onboarding']['data']['prompts'][0]
        self.assertEqual(result['id'],'444444444444444444')
        self.assertEqual(result['options'][0]['id'],'123456789012345678')
        self.assertEqual(result['options'][0]['role_ids'],['987654321012345678'])
        archive(s)


    async def test_stage1_status_reads_receipts_while_mutation_locked(self):
        inter=NS(response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()),guild_id=1,user=NS(id=7))
        cog=PermissionAudit(None)
        await cog.lock.acquire()
        try:
            with patch.object(cog,'authorized',AsyncMock(return_value=True)),patch('features.anti_scam_fix.load',return_value=dict(id='p',scope='stage1_caps',ops=[dict(state='verified'),dict(state='prepared')])),patch('cogs.permission_audit.collect',AsyncMock()) as read:
                await cog.stage1.callback(cog,inter,action='status',plan_id='p')
                read.assert_not_awaited()
            self.assertIn('verified 1',inter.followup.send.call_args.args[0])
        finally:cog.lock.release()
