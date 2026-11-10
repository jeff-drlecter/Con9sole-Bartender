import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import discord
from features import service_access as s

class Channel:
    def __init__(self,identity,kind='text',parent=None,synced=False):
        self.id=identity;self.name=str(identity);self.type=kind;self.category_id=parent;self.permissions_synced=synced
        self.ow=discord.PermissionOverwrite(send_tts_messages=False)
    def overwrites_for(self,target):return self.ow if target.id==s.SERVICES['carl'] else discord.PermissionOverwrite()

class AccessTests(unittest.IsolatedAsyncioTestCase):
    def inventory(self,channels,admin=True):
        role=NS(id=s.SERVICES['carl'],name='carl',permissions=discord.Permissions(administrator=admin))
        return role,NS(id=42),channels
    async def test_preparation_is_only_the_named_bot_and_preserves_other_bits(self):
        c=Channel(50)
        with patch.object(s,'inventory',AsyncMock(return_value=self.inventory([c]))):p=await s.plan(NS(id=1),'carl',7)
        op=p['ops'][0]
        self.assertEqual(op['target'],s.SERVICES['carl'])
        self.assertEqual(op['before'][1]&~op['mask'],op['after'][1]&~op['mask'])
        self.assertEqual(op['before'][0]&~op['mask'],op['after'][0]&~op['mask'])
        self.assertEqual(p['actor'],7)
    async def test_each_plan_contains_at_most_twenty_entries(self):
        with patch.object(s,'inventory',AsyncMock(return_value=self.inventory([Channel(i) for i in range(60)]))):p=await s.plan(NS(id=1),'carl',7)
        self.assertEqual(len(p['ops']),20);self.assertEqual(p['remaining'],60)
    async def test_synced_child_is_skipped_but_log_output_is_not(self):
        output=next(iter(s.CARL_OUTPUT))
        channels=[Channel(8,'category'),Channel(10,parent=8,synced=True),Channel(output,parent=8,synced=True)]
        with patch.object(s,'inventory',AsyncMock(return_value=self.inventory(channels))):p=await s.plan(NS(id=1),'carl',7)
        self.assertEqual({o['channel'] for o in p['ops']},{8,output})
    async def test_nonadmin_preparation_is_rejected(self):
        with patch.object(s,'inventory',AsyncMock(return_value=self.inventory([],False))):
            with self.assertRaises(ValueError):await s.plan(NS(id=1),'carl',7)
    def test_profiles_have_no_administrator_or_webhook_power(self):
        for key in s.SERVICES:
            perms=s.role_permissions(key)
            self.assertFalse(perms.administrator);self.assertFalse(perms.manage_webhooks)
        self.assertFalse(s.role_permissions('bartender').ban_members)
        self.assertFalse(s.role_permissions('bartender').kick_members)
    async def test_forged_scope_never_executes(self):
        with patch('features.anti_scam_fix.execute',AsyncMock()) as execute:
            with self.assertRaises(ValueError):await s.execute(NS(),dict(service='carl',scope='other'),AsyncMock())
        execute.assert_not_awaited()
    async def test_role_changed_after_preview_stops_before_write(self):
        p=dict(service='carl',scope='service_access',role_before=0)
        with patch.object(s,'inventory',AsyncMock(return_value=self.inventory([]))),patch('features.anti_scam_fix.execute',AsyncMock()) as execute:
            with self.assertRaises(ValueError):await s.execute(NS(),p,AsyncMock())
        execute.assert_not_awaited()
    async def test_member_deny_is_not_silently_removed(self):
        role=NS(id=s.SERVICES['carl'],tags=NS(bot_id=42),is_bot_managed=lambda:True)
        channel=Channel(50)
        channel.overwrites_for=lambda target:discord.PermissionOverwrite(view_channel=False)
        guild=NS(fetch_roles=AsyncMock(return_value=[role]),fetch_member=AsyncMock(return_value=NS(id=42)),fetch_channels=AsyncMock(return_value=[channel]))
        with self.assertRaises(ValueError):await s.inventory(guild,'carl')
