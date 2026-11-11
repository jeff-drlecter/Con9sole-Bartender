import tempfile
import unittest
from pathlib import Path
from core.helper_pulse import PulseStore,summarize,fragments


class PulseTests(unittest.TestCase):
    def test_batch_dedup_counts_no_empty_or_restart_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pulse.db'
            store=PulseStore(path)
            for key,user in [('chat:1',1),('chat:2',1),('chat:3',2),('chat:1',1)]:
                store.record(key,125,10,100,'chat',user,int(key.split(':')[1]))
            store.record('help:1',130,10,100,'help',1,1)
            store.record('v1',140,10,0,'voice',value={'rooms':1,'people':2})
            store.record('v2',150,10,0,'voice',value={'rooms':1,'people':4})
            self.assertIsNone(store.claim(239))
            batch=store.claim(241)
            group=summarize(batch['events'])[0][1]
            self.assertEqual(group['chat'],3)
            self.assertEqual(len(group['people']),2)
            self.assertEqual(group['voice']['people'],4)
            self.assertIn('🆘 1 則疑似求助',fragments(group))
            self.assertIsNone(PulseStore(path).claim(242))
            store.finish(batch['bucket'],'sent',123)
            self.assertIsNone(store.claim(243))
            with store.connect() as db:
                columns={r[1] for r in db.execute('PRAGMA table_info(pulse_events)')}
            self.assertFalse({'content','body','title','name'} & columns)

    def test_deleted_events_and_downtime_are_not_dumped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PulseStore(Path(tmp)/'pulse.db')
            store.record('chat:1',125,10,100,'chat',1,1)
            store.withdraw(1)
            self.assertIsNone(store.claim(241))
            store.record('chat:2',125,10,100,'chat',1,2)
            self.assertIsNone(store.claim(2000))
            store.record('chat:3',2001,10,100,'chat',1,3)
            self.assertIsNotNone(store.claim(2041))

    def test_shared_log_contains_only_eligible_game_metadata(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio,tempfile,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import config
from cogs.helper_sandbox import HelperSandbox
from core.helper_pulse import PulseStore
from core.helper_detection import DetectionStore
class Text:
    def __init__(self,id,name,category,guild):
        self.id,self.name,self.category,self.guild=id,name,category,guild
        self.category_id=category.id
async def main():
 with tempfile.TemporaryDirectory() as tmp:
  with patch.dict(os.environ,{'HELPER_SANDBOX':''}): cog=HelperSandbox(SimpleNamespace())
  cog.pulse=PulseStore(Path(tmp)/'pulse.db');cog.store=DetectionStore(Path(tmp)/'helper.db')
  cat=SimpleNamespace(id=10,name='MH')
  guild=SimpleNamespace(id=config.GUILD_ID,default_role=object(),get_thread=lambda cid:None)
  source=Text(11,'mh-吹水組隊',cat,guild)
  private=Text(12,'private-討論',cat,guild)
  channels={10:cat,11:source,12:private}
  guild.get_channel=lambda cid:channels.get(cid)
  cog.bot.get_channel=guild.get_channel
  cog.game_categories=lambda guild:{10}
  cog.channel=SimpleNamespace(guild=guild,send=AsyncMock(return_value=SimpleNamespace(id=555)),id=123,permissions_for=lambda role:SimpleNamespace(view_channel=False))
  with patch('cogs.helper_sandbox.discord.TextChannel',Text),patch('cogs.helper_sandbox.time.time',return_value=241):
   assert cog.pulse_source(source)
   assert not cog.pulse_source(private)
   cog.pulse.record('chat:1',125,10,11,'chat',1,1)
   cog.pulse.record('chat:2',126,10,12,'chat',2,2)
   cog.pulse.record('help:3',130,10,11,'help',1,3)
   cog.store.observe(3,11,1,130,'求助',130)
   cog.pulse.record('voice:1',140,10,0,'voice',value=dict(rooms=1,people=4))
   await cog.publish_pulse()
   sent=cog.channel.send.call_args
   assert '💬 1 人、1 則' in sent.args[0]
   assert '🆘 1 則疑似求助' in sent.args[0]
   assert '🎙️ 1 個 call、4 人' in sent.args[0]
   assert 'private' not in sent.args[0] and '<@' not in sent.args[0]
   assert sent.kwargs['allowed_mentions'].everyone is False
   await cog.publish_pulse()
   assert cog.channel.send.await_count==1
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
