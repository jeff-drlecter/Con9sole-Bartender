"""Authorization boundary and zero-publishing regression coverage."""
import asyncio
import copy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock
import discord
import config
from cogs.helper_sandbox import HelperSandbox, HelperPanel, ROOM_ID
from core.helper_access import member_for, source_for, DEMO_ROOM_ID
from core.helper_detection import DetectionStore
from core.helper_detection_ui import DetectionView, visible_candidates
from core.helper_plans import public_source, show_plans
from core.newcomer_routes import support_destination, show_route
from scripts.audit_helper_entry import report, VIEW_HISTORY


def setup():
    member=N(id=42,bot=False,roles=[N(id=config.HELPER_ROLE_IDS[0])],guild_permissions=N(administrator=False))
    guild=N(id=config.GUILD_ID,default_role=N(id=config.GUILD_ID),fetch_member=AsyncMock(return_value=member))
    def channel(cid):
        c=MagicMock(spec=discord.TextChannel)
        c.id=cid;c.guild=guild;c.nsfw=False;c.overwrites={};c.name='可見討論';c.mention=f'<#{cid}>'
        c.permissions_for.return_value=discord.Permissions(view_channel=True,read_message_history=True,send_messages=True)
        return c
    board,source,demo=map(channel,(ROOM_ID,100,DEMO_ROOM_ID))
    channels={c.id:c for c in (board,source,demo)}
    guild.fetch_roles=AsyncMock(return_value=[])
    guild.fetch_channel=AsyncMock(side_effect=lambda cid:channels[cid])
    cog=HelperSandbox(N(get_cog=lambda _:None))
    cog.enabled=True;cog.channel=board;cog.tester_id=55
    cog.can_read_source=lambda ch,m:ch.permissions_for(m).view_channel and ch.permissions_for(m).read_message_history
    i=N(user=member,guild=guild,guild_id=config.GUILD_ID,channel_id=ROOM_ID,
        response=N(defer=AsyncMock(),send_message=AsyncMock(),edit_message=AsyncMock(),is_done=lambda:False),
        followup=N(send=AsyncMock()),edit_original_response=AsyncMock(),message=N(flags=N(ephemeral=True)))
    return cog,i,member,source,demo,channels


class Round2AccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_matrix_uses_fresh_member_and_demo_never_expands_formal_access(self):
        cog,i,m,source,demo,channels=setup()
        for roles,admin,expected in [([],False,False),([55],False,False),
             ([config.HELPER_ROLE_IDS[0]],False,True),([55,config.HELPER_ROLE_IDS[0]],False,True),([],True,True)]:
            m.roles=[N(id=r) for r in roles];m.guild_permissions.administrator=admin
            self.assertEqual(await member_for(cog,i) is not None,expected)
        m.guild_permissions.administrator=False;m.roles=[N(id=55)]
        i.channel_id=DEMO_ROOM_ID
        self.assertIs(await member_for(cog,i,demo=True),m)
        self.assertIsNone(await member_for(cog,i))
        i.data={'custom_id':'helper:sandbox:create:v1'}
        panel=HelperPanel(cog)
        self.assertTrue(await panel.interaction_check(i))
        for key in ('live','manage','duty','history'):
            i.data={'custom_id':f'helper:sandbox:{key}:v1'}
            self.assertFalse(await panel.interaction_check(i))
        # Old signed interaction carries Helper, but fresh member is now only Tester.
        i.user=N(id=42,roles=[N(id=config.HELPER_ROLE_IDS[0])]);i.channel_id=ROOM_ID
        self.assertFalse(await cog.access(i))
        self.assertIsNone(i.response.edit_message.call_args.kwargs['embed'])
        self.assertIsNone(i.response.edit_message.call_args.kwargs['view'])
        await show_plans(cog,i)
        self.assertIn('無法查看',i.followup.send.call_args.kwargs['content'])
        m.roles=[N(id=config.HELPER_ROLE_IDS[0])]
        cog.channel.permissions_for.return_value.read_message_history=False
        self.assertIsNone(await member_for(cog,i))

    async def test_source_revocation_after_message_fetch_blocks_action_and_clears_old_card(self):
        cog,i,m,source,demo,channels=setup()
        with tempfile.TemporaryDirectory() as tmp:
            cog.store=DetectionStore(Path(tmp)/'helper.db')
            cog.store.observe(200,100,9,time.time(),'求助',time.time())
            msg=N(id=200,channel=source,content='請問點樣配裝？',jump_url='https://discord.com/channels/1/100/200')
            async def fetch(mid):
                source.permissions_for.return_value.view_channel=False
                return msg
            source.fetch_message=AsyncMock(side_effect=fetch)
            view=DetectionView(cog,42,[]);view.selected=200
            await view.act(i,'claim')
            self.assertEqual(cog.store.detection(200)['state'],'open')
            self.assertIn('未作更改',i.edit_original_response.call_args.kwargs['content'])
            self.assertIsNone(i.edit_original_response.call_args.kwargs['embed'])
            source.fetch_message.reset_mock()
            self.assertEqual(await visible_candidates(cog,i),[])
            source.fetch_message.assert_not_awaited()

    async def test_private_thread_and_age_gate_are_not_carried_into_dashboard(self):
        cog,i,m,source,demo,channels=setup()
        self.assertTrue(public_source(source))
        source.nsfw=True
        self.assertFalse(public_source(source))
        self.assertIsNone(await source_for(cog,i.guild,m,100))
        source.nsfw=False
        thread=MagicMock(spec=discord.Thread)
        thread.id=101;thread.guild=i.guild;thread.type=discord.ChannelType.private_thread
        channels[101]=thread
        self.assertIsNone(await source_for(cog,i.guild,m,101))

    async def test_private_activity_ignores_stale_cached_permissions(self):
        cog,i,m,source,demo,channels=setup()
        source.category_id=10
        category=N(id=10,name='測試用遊戲')
        cached=MagicMock(spec=discord.TextChannel)
        cached.id=100;cached.category_id=10;cached.permissions_for.return_value=discord.Permissions.all()
        cached.category=category;cached.nsfw=False
        i.guild.get_channel=lambda cid:category if cid==10 else cached
        i.guild.voice_channels=[]
        i.guild.fetch_channels=AsyncMock(return_value=[source])
        m.guild=i.guild
        cog.game_categories=lambda guild:{10}
        cog.window.add(100,7,time.time())
        source.permissions_for.return_value.view_channel=False
        card,attention=await cog.private_activity(i)
        self.assertNotIn('1 人／1 則',str(card.to_dict()))
        self.assertEqual(attention,[])

    async def test_existing_support_requires_fresh_read_write_and_non_age_gated_channel(self):
        cog,i,m,source,demo,channels=setup()
        channels[config.SUPPORT_CHANNEL_ID]=source
        self.assertEqual((await support_destination(i)).id,source.id)
        for bit in ('view_channel','read_message_history','send_messages'):
            setattr(source.permissions_for.return_value,bit,False)
            self.assertIsNone(await support_destination(i))
            setattr(source.permissions_for.return_value,bit,True)
        source.nsfw=True
        await show_route(i,'help')
        self.assertNotIn(source.mention,i.followup.send.call_args.kwargs['content'])
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        source.edit.assert_not_called();source.send.assert_not_called()
        source.nsfw=False
        await show_route(i,'observe')
        self.assertIn('<id:customize>',i.followup.send.call_args.kwargs['content'])
        self.assertIn('日後',i.followup.send.call_args.kwargs['content'])

    async def test_disabled_pulse_is_not_started_and_preserves_database(self):
        cog,i,m,source,demo,channels=setup()
        cog.store=N();cog.bot.add_view=MagicMock()
        # Explicit calls from old scheduled handlers also remain harmless.
        cog.pulse=N(record=MagicMock(),claim=MagicMock(),finish=MagicMock())
        await cog.publish_pulse();await cog.record_pulse(N(),'chat');await cog.record_voice_pulse(i.guild,10)
        cog.channel.send.assert_not_called();cog.pulse.record.assert_not_called();cog.pulse.claim.assert_not_called()


class AuditTests(unittest.TestCase):
    def test_exact_diff_preserves_other_bits_and_age_patch_is_separate(self):
        snapshot=dict(guild=dict(id=str(config.GUILD_ID)),roles=[
            dict(id=str(config.GUILD_ID),name='@everyone',permissions='0'),
            dict(id='55',name='🧪 Tester',permissions='0')],channels=[
            dict(id=str(ROOM_ID),name='社群動態',permission_overwrites=[
                dict(id='55',type=0,allow=str(VIEW_HISTORY|2048),deny='8192')]),
            dict(id='99',name='問題回報',nsfw=True,permission_overwrites=[])])
        before=copy.deepcopy(snapshot)
        result=report(snapshot)
        self.assertEqual(snapshot,before)
        change=result['proposed_changes'][0]
        self.assertEqual(change['after'],dict(id='55',type=0,allow='2048',deny='8192'))
        self.assertEqual(result['age_review']['proposed_patch'],{'nsfw':False})
        self.assertEqual(result['age_review']['channel'],'99')
        snapshot['channels'].append(dict(id='98',name='其他問題回報'))
        self.assertIn('blocked',report(snapshot)['age_review'])
        snapshot['guild']['id']='123'
        with self.assertRaises(ValueError): report(snapshot)
