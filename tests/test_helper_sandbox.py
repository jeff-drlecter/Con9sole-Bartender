import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from core.helper_sandbox import HelperStore,ActivityWindow


class HelperStoreTests(unittest.TestCase):
    def test_claim_race_owner_handoff_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'helper.db'
            store=HelperStore(path)
            key,created=store.create(9,100)
            self.assertTrue(created)
            self.assertEqual(store.create(9,101),(key,False))
            def claim(user):
                try: store.transition(key,user,'claim',102); return user
                except ValueError: return None
            with ThreadPoolExecutor(2) as pool: claimed=list(pool.map(claim,[1,2]))
            owners=[x for x in claimed if x]
            self.assertEqual(len(owners),1)
            owner=owners[0]
            with self.assertRaises(ValueError): store.transition(key,8,'done',103)
            store.transition(key,owner,'handoff',104)
            self.assertIsNone(store.active()[0]['owner'])
            store.transition(key,8,'claim',105)
            store.transition(key,8,'done',106)
            self.assertEqual(store.active(),[])
            with self.assertRaises(ValueError): store.transition(key,1,'claim',107)
            self.assertEqual(len(HelperStore(path).history()),5)
            self.assertTrue(store.toggle_duty(1))
            self.assertFalse(HelperStore(path).toggle_duty(1))
            self.assertTrue(store.reserve('channel'))
            self.assertFalse(store.reserve('channel'))

    def test_metadata_window_bounds(self):
        window=ActivityWindow(0,limit=3)
        for at,user in [(1,1),(2,1),(3,2),(4,3)]: window.add(100,user,at)
        self.assertEqual(window.counts(4)[100]['messages'],3)
        self.assertEqual(len(window.counts(4)[100]['users']),3)
        self.assertEqual(window.counts(1900),{})
        self.assertGreater(window.truncated_until,4)

    def test_disabled_lifecycle_and_permission_filtered_live_view(self):
        result=subprocess.run([sys.executable,'-c',r'''
import asyncio,os,time,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import discord,config
from cogs.helper_sandbox import HelperSandbox,HelperPanel,RequestView
from core.helper_sandbox import HelperStore
async def main():
    with patch.dict(os.environ,{'HELPER_SANDBOX':''}): cog=HelperSandbox(SimpleNamespace())
    await cog.cog_load()
    assert cog.store is None and not cog.tick.is_running()
    await cog.cog_unload()
    with tempfile.TemporaryDirectory() as tmp:
        cog.store=HelperStore(Path(tmp)/'helper.db')
        cog.enabled=True
        cog.tester_id=55
        cog.channel=SimpleNamespace(id=123,permissions_for=lambda member:SimpleNamespace(view_channel=True))
        member=SimpleNamespace(id=1,guild_permissions=SimpleNamespace(administrator=False),roles=[SimpleNamespace(id=55)])
        i=SimpleNamespace(user=member,guild_id=config.GUILD_ID,channel_id=123,response=SimpleNamespace(send_message=AsyncMock()))
        with patch('cogs.helper_sandbox.discord.Member',SimpleNamespace):
            assert await cog.access(i)
            member.roles=[]
            assert not await cog.access(i)
            member.roles=[SimpleNamespace(id=55)]
            i.channel_id=999
            assert not await cog.access(i)
            i.channel_id=123
        panel=HelperPanel(cog)
        assert panel.is_persistent() and len(panel.children)==5
        for n in range(20): cog.store.create(n,time.time())
        embed=await cog.demo_embed()
        assert len(embed)<6000 and all(len(f.value)<=1024 for f in embed.fields)
        view=RequestView(cog,1,cog.store.active())
        assert len(view.children)==4
        category=SimpleNamespace(id=10,name='Game')
        def channel(id,visible,history=True,connect=True):
            return SimpleNamespace(id=id,category_id=10,category=category,name='room',jump_url=f'https://discord.com/channels/1/{id}',members=[SimpleNamespace(bot=False)],
                permissions_for=lambda _:SimpleNamespace(view_channel=visible,read_message_history=history,connect=connect))
        visible=channel(11,True)
        hidden=channel(12,False)
        nohistory=channel(13,True,False)
        noconn=channel(14,True,True,False)
        channels={10:category,11:visible,12:hidden,13:nohistory,14:noconn}
        guild=SimpleNamespace(voice_channels=[visible,hidden,noconn],get_channel=lambda id:channels.get(id))
        member.guild=guild
        cog.game_categories=lambda guild:{10}
        for cid in [11,12,13]: cog.window.add(cid,cid,time.time())
        output=cog.live_embed(member).to_dict()
        import json
        text=json.dumps(output)
        assert '/1/11' in text and '/1/12' not in text and '/1/13' not in text and '/1/14' not in text
        assert '1 人／1 則' in str(output)
        member.bot=False
        guild.id=config.GUILD_ID
        cog.is_game=lambda ch:True
        visible.members=[SimpleNamespace(bot=False),SimpleNamespace(bot=False)]
        await cog.on_voice_state_update(member,SimpleNamespace(channel=None),SimpleNamespace(channel=visible))
        assert visible.id not in cog.window.voice_started
        visible.members=[member]
        await cog.on_voice_state_update(member,SimpleNamespace(channel=None),SimpleNamespace(channel=visible))
        assert visible.id in cog.window.voice_started
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
