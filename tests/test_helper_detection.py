import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from core.helper_detection import detect_help,DetectionStore


class DetectionTests(unittest.TestCase):
    def test_cantonese_english_help_vs_chatter_and_quotes(self):
        for text in ['MH 連唔到朋友個場，有冇人知點搞？','請問點樣配裝？','求助 PS5 開唔到','need help with this boss','How do I join my friend?','唔識搞，幫幫手','個game不停閃退','點配裝？','有冇人可以幫手？','help pls','隻boss打唔過']:
            self.assertIsNotNone(detect_help(text),text)
        for text in ['有冇人今晚打機？','有人開call嗎？','我可以幫你','搞掂咗，唔使幫啦','fixed it thanks','> 求助 點樣配裝\n我可以幫你','```need help```','https://example.com/how-to-play','呢個好好玩？']:
            self.assertIsNone(detect_help(text),text)

    def test_reference_lifecycle_reply_claim_dismiss_edit_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DetectionStore(Path(tmp)/'helper.db')
            store.observe(1,10,20,100,'疑似求助',100)
            store.observe(1,10,20,100,'詢問方法',101)
            self.assertEqual(len(store.candidates(101)),1)
            store.reply(1,20)
            self.assertEqual(store.detection(1)['replied'],0)
            store.reply(1,21)
            self.assertEqual(store.detection(1)['replied'],1)
            store.act(1,30,'claim',102)
            with self.assertRaises(ValueError): store.act(1,31,'claim',103)
            with self.assertRaises(ValueError): store.act(1,31,'done',103)
            store.act(1,30,'handoff',104)
            store.act(1,31,'claim',105)
            store.act(1,31,'done',106)
            store.observe(1,10,20,100,'求助',107)
            self.assertEqual(store.candidates(107),[])
            self.assertEqual(len(store.candidates(107,closed=True)),1)
            store.observe(2,10,20,100,'求助',108)
            store.withdraw(2,109)
            self.assertEqual(store.candidates(109),[])
            store.observe(2,10,20,100,'求助',110)
            self.assertEqual(store.detection(2)['state'],'open')
            store.act(2,30,'dismiss',111)
            store.observe(2,10,20,100,'求助',112)
            self.assertEqual(store.detection(2)['state'],'dismissed')
            store.prune(100+7*86400+1)
            self.assertIsNone(store.detection(1))
            with store.connect() as db:
                columns={r[1] for r in db.execute('PRAGMA table_info(detected_help)')}
            self.assertFalse({'content','body','excerpt'} & columns)

    def test_live_ingestion_scope_and_forum_thread_title(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio,os,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import discord,config
from cogs.helper_sandbox import HelperSandbox
from core.helper_detection import DetectionStore
from core.helper_detection_ui import show_pending
class Text:
    def __init__(self,name): self.name=name; self.id=10; self.guild=SimpleNamespace(id=config.GUILD_ID); self.category_id=5
    def permissions_for(self,member): return SimpleNamespace(view_channel=member.visible,read_message_history=member.history)
class Forum(Text): pass
class Thread:
    def __init__(self,parent,private=False):
        self.parent=parent; self.name='請問點樣配裝'; self.id=100; self.guild=parent.guild
        self.type=discord.ChannelType.private_thread if private else discord.ChannelType.public_thread
    def permissions_for(self,member): return self.parent.permissions_for(member)
async def main():
 with tempfile.TemporaryDirectory() as tmp:
  with patch.dict(os.environ,{'HELPER_SANDBOX':''}): cog=HelperSandbox(SimpleNamespace())
  cog.enabled=True; cog.store=DetectionStore(Path(tmp)/'helper.db'); cog.game_categories=lambda guild:{5}
  with patch('cogs.helper_sandbox.discord.TextChannel',Text),patch('cogs.helper_sandbox.discord.ForumChannel',Forum),patch('cogs.helper_sandbox.discord.Thread',Thread):
   ch=Text('mh-吹水組隊'); forum=Forum('攻略庫'); thread=Thread(forum)
   assert cog.help_source(ch) and cog.help_source(thread)
   assert not cog.help_source(Text('官方更新'))
   assert not cog.help_source(Thread(forum,True))
   assert not cog.can_read_source(ch,SimpleNamespace(visible=False,history=True))
   assert not cog.can_read_source(ch,SimpleNamespace(visible=True,history=False))
   message=SimpleNamespace(id=100,channel=thread,guild=thread.guild,content='如圖',author=SimpleNamespace(id=1,bot=False),reference=None,created_at=datetime.now(timezone.utc))
   await cog.on_message(message)
   assert len(cog.store.candidates(time.time()))==1
   message.id=101;message.content='你可以試另一套';message.author.id=2
   await cog.on_message(message)
   assert len(cog.store.candidates(time.time()))==1
   assert cog.store.detection(100)['replied']==1
   message.channel=Thread(forum,True);message.content='求助';message.id=102
   await cog.on_message(message)
   assert cog.store.detection(102) is None
   await cog.on_raw_message_delete(SimpleNamespace(guild_id=config.GUILD_ID,message_id=100))
   assert cog.store.candidates(time.time())==[]
   message.channel=ch;message.id=200;message.content='請問點樣配裝？'
   ch.fetch_message=AsyncMock(return_value=message)
   await cog.on_message(message)
   cog.bot.get_channel=lambda cid:ch
   i=SimpleNamespace(user=SimpleNamespace(visible=False,history=True,id=8),guild=SimpleNamespace(get_thread=lambda cid:None),response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
   await show_pending(cog,i)
   ch.fetch_message.assert_not_awaited()
   assert len(i.followup.send.call_args.kwargs['embed'].fields)==0
   i.user.visible=True
   message.jump_url='https://discord.com/channels/1/10/200'
   await show_pending(cog,i)
   assert i.followup.send.call_args.kwargs['ephemeral'] is True
   assert len(i.followup.send.call_args.kwargs['embed'].fields)==1
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
