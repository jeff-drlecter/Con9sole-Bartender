import subprocess
import sys
import unittest


class NewsHelperAccessTests(unittest.TestCase):
    def test_news_permission_matrix_and_legacy_dependencies(self):
        from features.news_access_audit import audit, permissions, access
        from features.news_channel_categories import CHANNELS, ROLE_NAMES
        import config
        view, history, send = 1<<10, 1<<16, 1<<11
        roles = [dict(id=str(config.GUILD_ID), name='@everyone', permissions=str(view|history|send)),
                 dict(id=str(config.VERIFIED_ROLE_ID), name='Verified', permissions='0'),
                 dict(id=str(config.HELPER_ROLE_IDS[0]), name='Helpers', permissions='0'),
                 dict(id='20',name='no-news-sub',permissions='0'),
                 dict(id='21',name='news-sub',permissions='0'),
                 dict(id='22',name='Admin',permissions='8')]
        ids = dict(zip(CHANNELS, ['11','12','13']))
        roles += [dict(id=ids[k],name=ROLE_NAMES[k],permissions='0',managed=False) for k in CHANNELS]
        channels = [dict(id=str(cid),name=key,permission_overwrites=[
            dict(id=str(config.GUILD_ID),type=0,deny=str(view|send),allow='0'),
            dict(id=ids[key],type=0,deny='0',allow=str(view)),
            dict(id='20',type=0,deny=str(view),allow='0')]) for key,cid in CHANNELS.items()]
        snapshot=dict(guild=dict(id=str(config.GUILD_ID),owner_id='999'),roles=roles,channels=channels,
                      onboarding=dict(prompts=[dict(id='old',options=[dict(id='off',title='off',role_ids=['20'])])]))
        result=audit(snapshot)
        self.assertEqual(len(result['matrix']),64)
        for row in result['matrix']:
            for key, p in row['channels'].items():
                self.assertEqual(p['summary_visible'],key in row['selected'])
                self.assertEqual(p['button_prerequisites'],key in row['selected'])
                self.assertFalse(p['send'])
        self.assertTrue(any(d['kind']=='onboarding' and d['role']=='20' for d in result['dependencies']))
        self.assertFalse(result['changes_applied'])
        member=dict(user=dict(id='1'),roles=['11','20'])
        # A member-specific deny overrides all role allows.
        channel=dict(channels[0],permission_overwrites=channels[0]['permission_overwrites']+[dict(id='1',type=1,deny=str(view),allow='0')])
        self.assertFalse(access(permissions(config.GUILD_ID,roles,member,channel))['view'])
        # Legacy denies on OTHER bits can still block history, even if View works.
        channel=dict(channels[0],permission_overwrites=channels[0]['permission_overwrites']+[dict(id='21',type=0,deny=str(history),allow='0')])
        member['roles'].append('21')
        p=access(permissions(config.GUILD_ID,roles,member,channel))
        self.assertTrue(p['view']); self.assertFalse(p['summary_visible'])
        member['roles']=['22']
        self.assertTrue(access(permissions(config.GUILD_ID,roles,member,channel))['summary_visible'])

    def test_helper_privacy_refresh_missing_dependency_and_revocation(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio, time
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, MagicMock, patch
import discord, config
from core.helper_plans import public_source, shared_counts, authorized_status, show_plans, HelperPlansView
from cogs.helper_sandbox import HelperSandbox
from core.helper_dashboard import dashboard_embed

def summary(p):
    return dict(id=p['id'],status=p['status'],game=p['game'],mode=p['mode'],start=p['start'],
                registered=len(p['members']),party=1,capacity=p['capacity'],attendance=None,revision=0,
                permissions=dict(read=True,join=True,edit=False,cancel=False))
async def main():
    now=time.time()
    def plan(key,channel=10,status='due',capacity=4):
        return dict(id=key,guild=config.GUILD_ID,channel=channel,message=99,status=status,start=now,
                    game='visible game' if channel==10 else 'SECRET GAME',mode='test',capacity=capacity,
                    party=1,members=[987654321],owner=456,reminders=[987654321])
    rows={'a':plan('a'), 'hidden':plan('hidden',20), 'full':plan('full',status='live',capacity=2),
          'expired':dict(plan('expired'),start=now-7201), 'cancelled':plan('cancelled',status='cancelled')}
    member=S(id=7,roles=[S(id=config.HELPER_ROLE_IDS[0])],guild_permissions=S(administrator=False))
    guild=S(id=config.GUILD_ID,default_role=S(id=1),fetch_member=AsyncMock(return_value=member))
    def channel(cid,visible):
        ch=MagicMock(spec=discord.TextChannel)
        ch.id=cid;ch.guild=guild;ch.overwrites={};ch.nsfw=False
        ch.permissions_for=lambda who:S(view_channel=visible,read_message_history=True)
        return ch
    source=channel(10,True);hidden=channel(20,False);board=channel(30,True)
    guild.fetch_channel=AsyncMock(side_effect=lambda cid:{10:source,20:hidden,30:board}[cid])
    async def status(g,uid,key):
        return summary(rows[key]) if rows[key]['channel']==10 else None
    plans=S(book=S(all=lambda:list(rows.values()),get=lambda key:rows.get(key)),member_status=AsyncMock(side_effect=status))
    cog=S(bot=S(get_cog=lambda name:plans),channel=board,enabled=True,tester_id=55)
    with patch('features.squad_plans.public_status',summary,create=True):
        assert await shared_counts(cog)==(1,1) # hidden, full, expired and cancelled do not add counts
    assert public_source(source) and not public_source(hidden)
    source.overwrites={1:discord.PermissionOverwrite(view_channel=False)}
    assert not public_source(source) # default-role access alone cannot overrule a member/role deny
    source.overwrites={}
    assert await authorized_status(plans,guild,7,'hidden') is None
    i=S(user=member,guild=guild,guild_id=config.GUILD_ID,channel_id=30,
        response=S(defer=AsyncMock(),send_message=AsyncMock()),followup=S(send=AsyncMock()),edit_original_response=AsyncMock())
    await show_plans(cog,i)
    kwargs=i.followup.send.call_args.kwargs
    assert kwargs['ephemeral'] and not kwargs['allowed_mentions'].everyone
    text=str(kwargs['embed'].to_dict())
    assert 'visible game' in text and 'SECRET' not in text and '987654321' not in text and 'reminders' not in text
    assert '不代表已到場' in text
    assert plans.member_status.await_count>=2
    view=kwargs['view'];i.user=S(id=8)
    assert not await view.interaction_check(i)
    i.user=member
    assert await view.interaction_check(i)
    # Source revoked after selection: replace private response, clear old embed/view options.
    plans.member_status.side_effect=lambda *args:None
    await show_plans(cog,i,key='a',edit=True)
    assert i.edit_original_response.call_args.kwargs['embed'] is None
    assert '<id:customize>' in i.edit_original_response.call_args.kwargs['content']
    assert i.followup.send.await_count==1
    # Helper role removed: no source lookup and no leftover details.
    member.roles=[];plans.member_status.reset_mock()
    await show_plans(cog,i,edit=True)
    plans.member_status.assert_not_awaited()
    assert i.edit_original_response.call_args.kwargs['view'] is None
    # Admin passes Dashboard access but still must use the 03 source interface.
    member.guild_permissions.administrator=True
    await show_plans(cog,i,key='a',edit=True)
    plans.member_status.assert_awaited_once()
    # Old deployment with no Part 2 interface fails closed.
    cog.bot.get_cog=lambda name:S(book=plans.book)
    await show_plans(cog,i,edit=True)
    assert '暫未就緒' in i.edit_original_response.call_args.kwargs['content']
    assert await shared_counts(cog) is None
    # Concurrent edit/move during authorization invalidates the old summary.
    async def move(g,uid,key):
        previous=summary(rows[key]);rows[key]=dict(rows[key],channel=20);return previous
    plans.member_status.side_effect=move
    assert await authorized_status(plans,guild,7,'a') is None
    # Existing dashboard refresh edits its owned message; never sends a report.
    real=HelperSandbox(S())
    real.store=S(prune=lambda now:None,get=lambda key:'999')
    message=S(edit=AsyncMock())
    real.channel=S(fetch_message=AsyncMock(return_value=message),send=AsyncMock())
    real.demo_embed=AsyncMock(return_value=discord.Embed(title='summary'))
    await real.refresh();await real.refresh()
    assert message.edit.await_count==2
    real.channel.send.assert_not_awaited()
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_clear_all_keeps_native_recovery_and_only_mutates_category_roles(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock,patch
import config
from core.news_channel_ui import NewsChannelSelect,open_news_channels
from data.menu_registry import get_menu_items
async def main():
    roles={k:S(id=n) for k,n in [('ps',11),('xbox',12),('pc',13)]}
    legacy=S(id=20); game=S(id=21)
    member=S(id=7,roles=[*roles.values(),legacy,game],add_roles=AsyncMock(),remove_roles=AsyncMock())
    fresh=S(id=7,roles=[legacy,game])
    guild=S(fetch_member=AsyncMock(side_effect=[member,fresh,fresh]))
    i=S(user=S(id=7),guild=guild,guild_id=config.GUILD_ID,response=S(defer=AsyncMock(),send_message=AsyncMock()),followup=S(send=AsyncMock()))
    with patch('core.news_channel_ui.safe_roles',AsyncMock(return_value=roles)):
        await NewsChannelSelect.callback(S(values=[]),i)
        assert member.remove_roles.await_count==3
        member.add_roles.assert_not_awaited()
        assert all(call.args[0] in roles.values() for call in member.remove_roles.call_args_list)
        assert '<id:customize>' in i.followup.send.call_args.args[0]
        # Reopen from an accessible NON-news entry, with no news/game role prerequisite.
        await open_news_channels(i)
        assert i.followup.send.call_args.kwargs['ephemeral']
        assert not any(o.default for o in i.followup.send.call_args.kwargs['view'].children[0].options)
    assert any(x.id=='news_channels' for x in get_menu_items('info'))
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_part2_real_contract_when_integrated(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio,time
from types import SimpleNamespace as S
from unittest.mock import AsyncMock,MagicMock
import discord,config
from cogs.squad_plans import SquadPlans
from core.helper_plans import authorized_status
if not hasattr(SquadPlans,'member_status'):
    print('PART2_NOT_IN_BASE');raise SystemExit(0)
async def main():
    p=dict(id='real',guild=config.GUILD_ID,channel=10,message=99,status='due',start=time.time(),
           game='test',mode='test',party=1,capacity=3,members=[2],owner=1,revision=0)
    cog=object.__new__(SquadPlans);cog.book=S(get=lambda key:dict(p))
    member=MagicMock(spec=discord.Member)
    member.id=2;member.roles=[S(id=config.VERIFIED_ROLE_ID),S(id=config.HELPER_ROLE_IDS[0])]
    member.guild_permissions=discord.Permissions.none()
    channel=MagicMock(spec=discord.TextChannel)
    channel.permissions_for=lambda m:discord.Permissions(view_channel=True,read_message_history=True,send_messages=False)
    guild=S(id=config.GUILD_ID,fetch_member=AsyncMock(return_value=member),fetch_channel=AsyncMock(return_value=channel))
    channel.guild=guild;channel.nsfw=False
    row=await authorized_status(cog,guild,2,'real')
    assert row and row[0]['permissions']['read'] and not row[0]['permissions']['join']
    assert not row[0]['permissions']['cancel'] and 'members' not in row[0]
    channel.nsfw=True
    assert await authorized_status(cog,guild,2,'real') is None
    channel.nsfw=False
    channel.permissions_for=lambda m:discord.Permissions(view_channel=False,read_message_history=True)
    assert await authorized_status(cog,guild,2,'real') is None
    channel.permissions_for=lambda m:discord.Permissions(view_channel=True,read_message_history=False)
    assert await authorized_status(cog,guild,2,'real') is None
    channel.permissions_for=lambda m:discord.Permissions(view_channel=True,read_message_history=True)
    member.roles=[S(id=config.HELPER_ROLE_IDS[0])] # Helper is not a substitute for verification/game access
    assert await authorized_status(cog,guild,2,'real') is None
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        if 'PART2_NOT_IN_BASE' in result.stdout:
            self.skipTest('Part 2 #166 is intentionally not merged into this independent branch')
