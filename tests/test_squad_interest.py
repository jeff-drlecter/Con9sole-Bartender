import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs.squad_cards import SquadCards, FootprintView, interest_topic
from features import squad_interest as storage
from quick_bar_fakes import interaction


class InterestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = patch.object(storage, 'STATS_DB', Path(self.folder.name)/'interest.sqlite3')
        self.patch.start()
        self.topic = storage.topic(1, 'NBA 2K27', 'REC')
        storage.remember(self.topic)

    def tearDown(self):
        self.patch.stop(); self.folder.cleanup()

    async def test_toggle_persists_and_topic_identity_is_normalized(self):
        self.assertTrue(storage.toggle(self.topic['id'],1,10))
        storage.initialize()
        self.assertEqual(storage.members(self.topic['id']),[10])
        self.assertEqual(storage.topic(1,' nba  2k27 ','rec')['id'],self.topic['id'])
        self.assertNotEqual(storage.topic(1,'NBA 2K27','Park')['id'],self.topic['id'])
        self.assertNotEqual(storage.topic(2,'NBA 2K27','REC')['id'],self.topic['id'])
        self.assertFalse(storage.toggle(self.topic['id'],1,10))
        self.assertEqual(storage.members(self.topic['id']),[])
        with self.assertRaises(ValueError): storage.toggle(self.topic['id'],2,10)

    async def test_once_per_session_cooldown_and_cancel_recheck(self):
        storage.toggle(self.topic['id'],1,10)
        self.assertEqual(storage.reserve('first',self.topic['id'],[10],now=10000),[10])
        self.assertEqual(storage.reserve('first',self.topic['id'],[10],now=20000),[])
        self.assertEqual(storage.reserve('second',self.topic['id'],[10],now=10001),[])
        self.assertEqual(storage.reserve('third',self.topic['id'],[10],now=11801),[10])
        storage.toggle(self.topic['id'],1,10)
        self.assertEqual(storage.reserve('fourth',self.topic['id'],[10],now=15000),[])

    async def test_simultaneous_workers_cannot_double_claim(self):
        storage.toggle(self.topic['id'],1,10)
        results=await asyncio.gather(*[asyncio.to_thread(storage.reserve,'session',self.topic['id'],[10],now=10000) for _ in range(4)])
        self.assertEqual(sum(len(r) for r in results),1)

    async def test_notifications_filter_users_and_only_allow_consented_mentions(self):
        permitted=types.SimpleNamespace(view_channel=True,connect=True)
        denied=types.SimpleNamespace(view_channel=False,connect=False)
        people={uid:types.SimpleNamespace(id=uid,bot=uid==13) for uid in range(10,15)}
        for uid in people: storage.toggle(self.topic['id'],1,uid)
        destination=types.SimpleNamespace(id=30,send=AsyncMock(),permissions_for=lambda m:permitted)
        guild=types.SimpleNamespace(id=1,get_member=lambda uid:None if uid==14 else people.get(uid))
        channel=types.SimpleNamespace(id=20,guild=guild,members=[people[11]],permissions_for=lambda m:denied if m.id==12 else permitted)
        cog=object.__new__(SquadCards); cog.bot=types.SimpleNamespace(get_channel=lambda _:destination);cog.interest_baseline=set()
        session={'id':'s1','destination':30,'message':99,'interest_topic':self.topic}
        await cog.notify_interested(channel,session)
        destination.send.assert_awaited_once()
        call=destination.send.call_args
        self.assertIn('<@10>',call.args[0]);self.assertNotIn('<@11>',call.args[0]);self.assertNotIn('<@12>',call.args[0])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict(),{'users':[10],'parse':[]})
        await cog.notify_interested(channel,session)
        self.assertEqual(destination.send.await_count,1)

    async def test_deployment_does_not_ping_existing_sessions(self):
        cog=object.__new__(SquadCards);cog.interest_baseline={'existing'};cog.bot=MagicMock()
        await cog.notify_interested(None,{'id':'existing'})
        cog.bot.get_channel.assert_not_called()

    async def test_persistent_button_updates_only_clickers_subscription(self):
        view=FootprintView(None,self.topic); self.assertTrue(view.is_persistent())
        i=interaction(); await view.toggle(i)
        self.assertEqual(storage.members(self.topic['id']),[i.user.id])
        await view.toggle(interaction());self.assertEqual(storage.members(self.topic['id']),[])
        self.assertIn('取消',i.followup.send.call_args.args[0])
        view.stop()

    async def test_ended_card_retains_button_and_registers_on_restart(self):
        bot=MagicMock();bot.get_channel.return_value=types.SimpleNamespace(send=AsyncMock())
        cog=object.__new__(SquadCards);cog.bot=bot;cog.save=MagicMock()
        message=types.SimpleNamespace(edit=AsyncMock(),content='old')
        bot.get_channel.return_value.fetch_message=AsyncMock(return_value=message)
        session={'id':'ended','destination':30,'message':99,'participants':{'10':'Jeff'},'started':1000,'ended':2000,'game':'NBA 2K27','mode':'REC'}
        await cog.render(None,session,ended=True)
        view=message.edit.call_args.kwargs['view']
        self.assertIsInstance(view,FootprintView)
        self.assertTrue(view.is_persistent())
        self.assertIsNone(message.edit.call_args.kwargs['content'])
        saved=next(t for t in storage.topics() if t['id']==view.topic['id'])
        restored=FootprintView(None,saved)
        self.assertEqual(restored.children[0].custom_id,view.children[0].custom_id)
        view.stop();restored.stop()
