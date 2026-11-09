from types import SimpleNamespace as NS
from unittest.mock import MagicMock,AsyncMock,patch
import unittest
import discord
import config
from cogs.tempvc import user_can_run_tempvc
from features import participation_fix as f


class VoiceAccessTests(unittest.TestCase):
    def make(self):
        self.member=MagicMock(spec=discord.Member)
        self.member.id=7;self.member.bot=False;self.member.pending=False;self.member.is_timed_out.return_value=False
        self.member.guild_permissions=discord.Permissions.none();self.member.roles=[]
        self.category=MagicMock(spec=discord.CategoryChannel);self.category.id=123
        self.category.permissions_for.return_value=discord.Permissions(view_channel=True,connect=True,speak=True)
        self.hub=MagicMock(spec=discord.VoiceChannel);self.hub.name=config.TEMP_VC_HUB_NAME
        self.hub.permissions_for.return_value=discord.Permissions(view_channel=True,connect=True,speak=True)
        self.category.voice_channels=[self.hub]
        self.source=MagicMock(spec=discord.TextChannel);self.source.category=self.category
        self.source.permissions_for.return_value=discord.Permissions(view_channel=True)
        self.guild=NS(get_member=lambda uid:self.member)
        return NS(guild=self.guild,guild_id=config.GUILD_ID,user=self.member,channel=self.source)

    def test_unverified_can_create_in_accessible_hub_category(self):
        self.assertTrue(user_can_run_tempvc(self.make()))

    def test_denied_hub_or_category_not_bypassed_by_verified(self):
        inter=self.make();self.member.roles=[NS(id=config.VERIFIED_ROLE_ID)]
        self.hub.permissions_for.return_value=discord.Permissions.none()
        self.assertFalse(user_can_run_tempvc(inter))
        self.hub.permissions_for.return_value=discord.Permissions(view_channel=True,connect=True,speak=True)
        self.category.permissions_for.return_value=discord.Permissions.none()
        self.assertFalse(user_can_run_tempvc(inter))

    def test_no_hub_or_no_category_denied(self):
        inter=self.make();self.category.voice_channels=[]
        self.assertFalse(user_can_run_tempvc(inter))
        self.source.category=None
        self.assertFalse(user_can_run_tempvc(inter))

    def test_timeout_pending_stale_actor_and_wrong_guild_denied(self):
        inter=self.make();self.member.is_timed_out.return_value=True
        self.assertFalse(user_can_run_tempvc(inter))
        self.member.is_timed_out.return_value=False;self.member.pending=True
        self.assertFalse(user_can_run_tempvc(inter))
        self.member.pending=False;self.guild.get_member=lambda uid:None
        self.assertFalse(user_can_run_tempvc(inter))
        inter.guild_id=0;self.assertFalse(user_can_run_tempvc(inter))


class PublicPlanTests(unittest.TestCase):
    def channel(self,cid,deny=False):
        role=discord.Object(f.OFF_TOPIC,type=discord.Role)
        ow=discord.PermissionOverwrite(view_channel=True,send_messages=False if deny else None,embed_links=False)
        c=MagicMock(spec=discord.TextChannel);c.id=cid;c.category_id=f.PUBLIC_CATEGORY;c.name='public'
        c.overwrites_for.side_effect=lambda target:discord.PermissionOverwrite.from_pair(*ow.pair())
        return c

    def test_only_two_public_targets_and_only_message_bits(self):
        channels=[self.channel(cid) for cid in f.TARGETS]+[self.channel(999)]
        plan=f.build([NS(id=f.OFF_TOPIC,managed=False)],channels,1,7)
        self.assertEqual(len(plan['ops']),2)
        mask=discord.Permissions(send_messages=True,send_messages_in_threads=True).value
        for op in plan['ops']:
            self.assertEqual(op['before'][1],op['after'][1])
            self.assertEqual(op['before'][0]^op['after'][0],mask)

    def test_explicit_readonly_channel_preserved(self):
        channels=[self.channel(cid,deny=True) for cid in f.TARGETS]
        plan=f.build([NS(id=f.OFF_TOPIC,managed=False)],channels,1,7)
        self.assertFalse(plan['ops']);self.assertEqual(len(plan['skipped']),2)

    def test_missing_moved_or_hidden_channel_stops(self):
        role=[NS(id=f.OFF_TOPIC,managed=False)]
        with self.assertRaises(ValueError):f.build(role,[],1,7)
        channels=[self.channel(cid) for cid in f.TARGETS];channels[0].category_id=999
        with self.assertRaises(ValueError):f.build(role,channels,1,7)


class ExecutionRechecks(unittest.IsolatedAsyncioTestCase):
    async def test_moved_channel_after_preview_never_written(self):
        import time
        op=dict(kind='overwrite',target=f.OFF_TOPIC,channel=next(iter(f.TARGETS)),before=[0,0],after=[2048,0],state='prepared')
        plan=dict(id='x',guild=1,actor=7,stamp=time.time(),ops=[op])
        channel=MagicMock(spec=discord.TextChannel);channel.category_id=999
        channel.set_permissions=AsyncMock()
        with patch('features.anti_scam_fix.current',AsyncMock(return_value=([0,0],NS(),channel))):
            with self.assertRaises(ValueError):await f.execute(NS(),plan,AsyncMock(return_value=True))
        channel.set_permissions.assert_not_awaited()

    async def test_revocation_during_room_lookup_prevents_create(self):
        from cogs.tempvc import TempVC
        from quick_bar_fakes import interaction
        cog=TempVC(MagicMock());inter=interaction()
        cog._find_owned_room=AsyncMock(return_value=None);cog._create_manual_temp_vc=AsyncMock()
        try:
            with patch('cogs.tempvc.user_can_run_tempvc',side_effect=[True,False]):
                await cog._create_default_room(inter)
            cog._create_manual_temp_vc.assert_not_awaited()
        finally:await cog.cog_unload()
