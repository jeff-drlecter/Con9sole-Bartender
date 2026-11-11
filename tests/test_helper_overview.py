import subprocess
import sys
import unittest
from core.helper_sandbox import ActivityWindow


class OverviewTests(unittest.TestCase):
    def test_attention_dedup_reply_and_delete(self):
        window=ActivityWindow(0)
        window.note_attention(1,10,20,100,newcomer=True,lfg=True)
        window.note_attention(1,10,20,101,newcomer=True,lfg=True)
        window.note_attention(2,10,20,102,newcomer=True)
        self.assertEqual(len(window.attention),2)
        window.attention_reply(1,20)
        self.assertFalse(any(r['replied'] for r in window.attention))
        window.attention_reply(1,21)
        self.assertTrue(all(r['replied'] for r in window.attention))
        window.attention_delete(1)
        self.assertFalse(window.attention)
        window.note_attention(3,10,22,200,newcomer=True)
        window.note_attention(4,10,23,2100,newcomer=True)
        self.assertEqual(len(window.attention),1)
        self.assertNotIn('content',window.attention[0])

    def test_mobile_render_navigation_refresh_and_private_attention(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio,os,time
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import discord
from core.helper_overview import render_overview,example_overview,OverviewView,BackToOverview,show_overview
from cogs.helper_sandbox import HelperSandbox
async def main():
    now=time.time()
    row=dict(state='open',owner=None,replied=False,created=now-600)
    message=SimpleNamespace(content='*'*1000,channel=SimpleNamespace(name='MH'),jump_url='https://discord.com/channels/1/2/3')
    activity=discord.Embed()
    activity.add_field(name='💬 活躍遊戲區',value='\n'.join(['activity '*40]*8))
    activity.add_field(name='🎙️ 而家開緊 call',value='\n'.join(['voice '*40]*8))
    card=render_overview([(row,message)]*8,activity,['new '*100]*8,now,now)
    assert len(card.fields)==4 and all(not f.inline and len(f.value)<=1024 for f in card.fields)
    assert len(card)<6000
    assert [f.name for f in card.fields][0]=='🆘 需要接應'
    assert '虛構示例' in example_overview(now).title
    cog=SimpleNamespace(window=SimpleNamespace(started=now),live_embed=lambda member:activity,attention_lines=lambda member,now:[],access=AsyncMock(return_value=True))
    view=OverviewView(cog,1)
    i=SimpleNamespace(user=SimpleNamespace(id=1),response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()),edit_original_response=AsyncMock())
    assert await view.interaction_check(i)
    i.user.id=2
    assert not await view.interaction_check(i)
    i.user.id=1
    with patch('core.helper_detection_ui.visible_candidates',AsyncMock(return_value=[])):
        await show_overview(cog,i)
        assert i.followup.send.call_args.kwargs['ephemeral'] is True
        before=i.followup.send.await_count
        await show_overview(cog,i,edit=True)
        assert i.followup.send.await_count==before and i.edit_original_response.await_count==1
    with patch.dict(os.environ,{'HELPER_SANDBOX':''}): real=HelperSandbox(SimpleNamespace())
    visible=SimpleNamespace(name='visible')
    hidden=SimpleNamespace(name='hidden')
    real.bot.get_channel=lambda cid:visible if cid==1 else hidden
    real.can_read_source=lambda channel,user:channel is visible
    real.window.note_attention(1,1,20,now,newcomer=True,lfg=True)
    real.window.note_attention(2,2,21,now,newcomer=True,lfg=True)
    lines=real.attention_lines(SimpleNamespace(),now)
    assert len(lines)==2 and all('hidden' not in line for line in lines)
    real.window.attention_reply(1,99)
    assert len(real.attention_lines(SimpleNamespace(),now))==1
    assert real.attention_lines(SimpleNamespace(),now+1801)==[]
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
