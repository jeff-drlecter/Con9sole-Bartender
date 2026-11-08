import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs.squad_cards import add_interest_fields, SquadCards, FootprintView, InterestRosterPages, interest_topic, interest_summary, interest_roster
from features import squad_interest as storage
from quick_bar_fakes import interaction


class InterestTests(unittest.IsolatedAsyncioTestCase):
    def test_delivery_retry_is_durable_and_uncertain_send_is_not_replayed(self):
        storage.toggle(self.topic['id'],1,10)
        storage.reserve('session',self.topic['id'],[10],now=100)
        self.assertEqual(storage.pending_deliveries('session',self.topic['id'],now=100),[(0,[10])])
        self.assertTrue(storage.claim_delivery('session',self.topic['id'],0))
        self.assertFalse(storage.claim_delivery('session',self.topic['id'],0))
        self.assertEqual(storage.pending_deliveries('session',self.topic['id'],now=200),[])
        storage.finish_delivery('session',self.topic['id'],0,retry=True,now=200)
        self.assertEqual(storage.pending_deliveries('session',self.topic['id'],now=259),[])
        self.assertEqual(storage.pending_deliveries('session',self.topic['id'],now=260),[(0,[10])])
        self.assertTrue(storage.claim_delivery('session',self.topic['id'],0))
        storage.finish_delivery('session',self.topic['id'],0,message_id=333)
        self.assertEqual(storage.pending_deliveries('session',self.topic['id'],now=300),[])

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
        self.assertEqual(storage.topic(1,'NBA 2K27','Park')['id'],self.topic['id'])
        self.assertNotEqual(storage.topic(2,'NBA 2K27','REC')['id'],self.topic['id'])
        self.assertFalse(storage.toggle(self.topic['id'],1,10))
        self.assertEqual(storage.members(self.topic['id']),[])
        with self.assertRaises(ValueError): storage.toggle(self.topic['id'],2,10)

    async def test_once_consumed_recurring_retained_switch_and_excluded_source(self):
        scope = self.topic['id']
        storage.toggle(scope, 1, 10, 'once', 'source')
        self.assertEqual(storage.reserve('source', scope, [10], now=10000), [])
        self.assertEqual(storage.members(scope), [10])
        self.assertEqual(storage.reserve('next', scope, [10], now=10001), [10])
        self.assertEqual(storage.members(scope), [])
        self.assertEqual(storage.reserve('another', scope, [10]), [])
        storage.toggle(scope, 1, 10, 'always')
        self.assertEqual(storage.reserve('recurring1', scope, [10], now=10002), [10])
        self.assertEqual(storage.reserve('recurring1', scope, [10], now=10003), [])
        self.assertEqual(storage.reserve('recurring2', scope, [10], now=10004), [10])
        self.assertEqual(storage.preferences(scope), {10: 'always'})
        storage.toggle(scope, 1, 10, 'once')
        self.assertEqual(storage.preferences(scope), {10: 'once'})
        storage.toggle(scope, 1, 10, 'once')
        self.assertEqual(storage.reserve('cancelled', scope, [10]), [])

    async def test_simultaneous_workers_cannot_double_claim(self):
        storage.toggle(self.topic['id'],1,10)
        results=await asyncio.gather(*[asyncio.to_thread(storage.reserve,'session',self.topic['id'],[10],now=10000) for _ in range(4)])
        self.assertEqual(sum(len(r) for r in results),1)

    async def test_notifications_filter_users_and_only_allow_consented_mentions(self):
        permitted=types.SimpleNamespace(view_channel=True,connect=True)
        denied=types.SimpleNamespace(view_channel=False,connect=False)
        people={uid:types.SimpleNamespace(id=uid,bot=uid==13,display_name=f'Player {uid}') for uid in range(10,15)}
        for uid in people: storage.toggle(self.topic['id'],1,uid)
        destination=types.SimpleNamespace(id=30,send=AsyncMock(return_value=types.SimpleNamespace(id=501)),permissions_for=lambda m:permitted)
        guild=types.SimpleNamespace(id=1,get_member=lambda uid:None if uid==14 else people.get(uid))
        channel=types.SimpleNamespace(id=20,guild=guild,members=[people[11]],permissions_for=lambda m:denied if m.id==12 else permitted)
        cog=object.__new__(SquadCards); cog.bot=types.SimpleNamespace(get_channel=lambda _:destination);cog.interest_baseline=set();cog.lock=asyncio.Lock();cog.state={"sessions":{}};cog.refresh_interest_cards=AsyncMock()
        session={'id':'s1','destination':30,'message':99,'interest_topic':self.topic}
        await cog.notify_interested(channel,session)
        destination.send.assert_awaited_once()
        call=destination.send.call_args
        self.assertIn('<@10>',call.args[0]);self.assertNotIn('<@11>',call.args[0]);self.assertNotIn('<@12>',call.args[0])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict(),{'users':[10],'parse':[]})
        self.assertNotIn('embed', call.kwargs)
        self.assertNotIn('embeds', call.kwargs)
        self.assertNotIn('\n', call.args[0])
        self.assertIn('[查看召人卡]', call.args[0])
        self.assertEqual(len(call.kwargs['view'].children), 1)
        self.assertEqual(call.kwargs['view'].children[0].url, 'https://discord.com/channels/1/20')
        self.assertNotIn(10, storage.members(self.topic['id']))
        await cog.notify_interested(channel,session)
        self.assertEqual(destination.send.await_count,1)

    async def test_deployment_does_not_ping_existing_sessions(self):
        cog=object.__new__(SquadCards);cog.interest_baseline={'existing'};cog.bot=MagicMock()
        await cog.notify_interested(None,{'id':'existing'})
        cog.bot.get_channel.assert_not_called()

    async def test_persistent_button_updates_only_clickers_subscription(self):
        view=FootprintView(None,self.topic); self.assertTrue(view.is_persistent())
        view.refresh = AsyncMock()
        i=interaction(); await view.toggle(i)
        self.assertEqual(storage.members(self.topic['id']),[i.user.id])
        await view.toggle(interaction());self.assertEqual(storage.members(self.topic['id']),[])
        self.assertIn('取消',i.followup.send.call_args.args[0])
        view.stop()

    async def test_separate_successful_subscriptions_emit_separate_receipts(self):
        view = FootprintView(None, self.topic)
        view.refresh = AsyncMock()
        events = []
        for event_id in (101, 102, 103):
            i = interaction(); i.id = event_id
            await view.toggle(i)
            events.extend(call.args[3] for call in i.client.dispatch.call_args_list)
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0], events[1])
        self.assertTrue(events[0].endswith(':101'))
        self.assertTrue(events[1].endswith(':103'))
        view.stop()

    def roster_interaction(self, ids=(10, 11)):
        people = {uid: types.SimpleNamespace(id=uid, bot=False, display_name=f'Player {uid}') for uid in ids}
        guild = types.SimpleNamespace(id=1, get_member=people.get)
        message = types.SimpleNamespace(id=500, author=types.SimpleNamespace(id=99),
            embeds=[discord.Embed(title='足跡').add_field(name='一齊玩過', value='Jeff')], edit=AsyncMock())
        channel = types.SimpleNamespace(id=100, fetch_message=AsyncMock(return_value=message),
            permissions_for=lambda _: types.SimpleNamespace(view_channel=True))
        i = interaction(guild=guild, channel=channel)
        i.client.user.id = 99
        i.message = message
        return i, message

    async def test_public_roster_join_cancel_refresh_and_no_ping(self):
        view = FootprintView(None, self.topic)
        i, message = self.roster_interaction()
        await view.toggle(i)
        edited = message.edit.call_args.kwargs
        self.assertEqual(edited['embed'].fields[0].name, '一齊玩過')
        self.assertEqual(len(edited['embed'].fields), 1)
        self.assertEqual(edited['allowed_mentions'].to_dict(), {'parse': []})
        message.embeds = [edited['embed']]
        await view.toggle(i)
        embed = message.edit.call_args.kwargs['embed']
        self.assertEqual(len(embed.fields), 1)
        self.assertEqual(embed.fields[0].value, 'Jeff')
        storage.toggle(self.topic['id'], 1, 11)
        await view.show_roster(i)
        self.assertEqual(len(message.edit.call_args.kwargs['embed'].fields), 1)
        self.assertIn('<@11>', i.followup.send.call_args.kwargs['embed'].description)
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(i.followup.send.call_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        view.stop()

    async def test_private_roster_buttons_toggle_switch_cancel_and_keep_source_session(self):
        view = FootprintView(None, self.topic)
        source, card = self.roster_interaction()
        storage.track_card(self.topic['id'], 100, card.id, 'live-session')
        await view.show_roster(source)
        pages = source.followup.send.call_args.kwargs['view']
        once, always = pages.children[-2:]
        self.assertEqual([once.label, always.label], ['🙋 下次叫我', '🔔 每次都叫我'])
        click, _ = self.roster_interaction()
        click.message = types.SimpleNamespace(id=999)  # Private panel, never a public card.
        self.assertTrue(await pages.interaction_check(click))
        await once.callback(click)
        self.assertEqual(storage.preferences(self.topic['id']), {10: 'once'})
        self.assertIn('下次叫我', pages.roster[0][1])
        self.assertEqual(storage.card_session(500), 'live-session')
        self.assertFalse(storage.card_session(999))
        self.assertEqual(click.response.defer.call_args.kwargs['thinking'], False)
        self.assertEqual(click.edit_original_response.call_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        click.followup.send.assert_not_awaited()
        await always.callback(click)
        self.assertEqual(storage.preferences(self.topic['id']), {10: 'always'})
        self.assertIn('每次都叫我', pages.roster[0][1])
        await always.callback(click)
        self.assertEqual(storage.preferences(self.topic['id']), {})
        self.assertEqual(pages.roster, [])
        self.assertTrue(pages.previous.disabled)
        self.assertTrue(pages.next_page.disabled)
        self.assertIn('已取消', click.edit_original_response.call_args.kwargs['content'])
        other = interaction()
        other.user.id = 11
        self.assertFalse(await pages.interaction_check(other))
        pages.stop()
        view.stop()

    async def test_concurrent_clicks_render_latest_members(self):
        lock = asyncio.Lock()
        cog = object.__new__(SquadCards)
        cog.lock = lock
        cog.state = {'sessions': {}}
        views = [FootprintView(cog, self.topic) for _ in range(2)]
        i, message = self.roster_interaction()
        j, _ = self.roster_interaction()
        j.channel = i.channel
        j.user.id = 11
        cog.bot = types.SimpleNamespace(get_guild=lambda _: i.guild, get_channel=lambda _: i.channel,
                                        user=types.SimpleNamespace(id=99))
        await asyncio.gather(views[0].toggle(i), views[1].toggle(j))
        self.assertEqual(storage.members(self.topic['id']), [10, 11])
        self.assertEqual(len(message.edit.call_args.kwargs['embed'].fields), 1)
        await views[0].show_roster(i)
        private = i.followup.send.call_args.kwargs
        self.assertTrue(private['ephemeral'])
        self.assertIn('<@10>', private['embed'].description)
        self.assertIn('<@11>', private['embed'].description)
        for view in views: view.stop()

    async def test_refresh_failure_keeps_subscription_and_reports_saved(self):
        view = FootprintView(None, self.topic)
        view.refresh = AsyncMock(side_effect=ValueError('deleted card'))
        i = interaction()
        with self.assertLogs('cogs.squad_cards', level='ERROR'):
            await view.toggle(i)
        self.assertEqual(storage.members(self.topic['id']), [10])
        self.assertIn('登記已儲存', i.followup.send.call_args.args[0])
        view.stop()

    async def test_live_registration_excludes_current_and_refreshes_footprints(self):
        from cogs.squad_cards import CardView
        i, footprint = self.roster_interaction()
        live = types.SimpleNamespace(id=600, author=types.SimpleNamespace(id=99),
            embeds=[discord.Embed(title='開緊團')], edit=AsyncMock())
        messages = {500: footprint, 600: live}
        i.channel.fetch_message = AsyncMock(side_effect=lambda mid: messages[mid])
        voice = types.SimpleNamespace(id=20, members=[], category=types.SimpleNamespace(name='NBA 2K27'))
        cog = object.__new__(SquadCards)
        cog.lock = asyncio.Lock()
        session = dict(id='current', message=600, game='NBA 2K27', interest_topic=self.topic)
        cog.state = {'sessions': {'20': session}}
        cog.bot = types.SimpleNamespace(get_guild=lambda _: i.guild,
            get_channel=lambda cid: voice if cid == 20 else i.channel,
            user=types.SimpleNamespace(id=99))
        storage.track_card(self.topic['id'], 100, 500)
        storage.track_card(self.topic['id'], 100, 600, 'current')
        view = CardView(cog, '20', session)
        i.message = live
        await view.toggle(i)
        self.assertEqual(len(footprint.edit.call_args.kwargs['embed'].fields), 1)
        self.assertIsInstance(live.edit.call_args.kwargs['view'], CardView)
        self.assertEqual(storage.reserve('current', self.topic['id'], [10]), [])
        self.assertEqual(storage.reserve('next', self.topic['id'], [10]), [10])
        await cog.refresh_interest_cards(self.topic)
        self.assertEqual(len(footprint.edit.call_args.kwargs['embed'].fields), 1)
        self.assertEqual(storage.preferences(self.topic['id']), {})
        view.stop()

    async def test_roster_permissions_long_lists_and_pagination(self):
        people = {uid: types.SimpleNamespace(id=uid, bot=uid == 2, display_name='@everyone *name*') for uid in range(100)}
        guild = types.SimpleNamespace(get_member=people.get)
        channel = types.SimpleNamespace(permissions_for=lambda m: types.SimpleNamespace(view_channel=m.id != 3))
        roster = interest_roster(guild, channel, range(101))
        self.assertNotIn(2, [uid for uid, _ in roster])
        self.assertNotIn(3, [uid for uid, _ in roster])
        self.assertEqual(len(roster), 98)
        self.assertNotIn('@everyone', roster[0][1])
        self.assertLessEqual(len(interest_summary([(10**18 + uid, '') for uid in range(1000)])), 1024)
        pages = InterestRosterPages(10, roster, self.topic['label'])
        self.assertTrue(pages.previous.disabled)
        self.assertFalse(pages.next_page.disabled)
        i = interaction()
        await pages.move(i, 1)
        self.assertEqual(pages.page, 1)
        self.assertLess(len(pages.embed().description), 4096)
        j = interaction(); j.user.id = 11
        self.assertFalse(await pages.interaction_check(j))
        pages.stop()

    async def test_ended_card_retains_button_and_registers_on_restart(self):
        bot=MagicMock();bot.get_channel.return_value=types.SimpleNamespace(id=30,send=AsyncMock())
        cog=object.__new__(SquadCards);cog.bot=bot;cog.save=MagicMock();cog.lock=asyncio.Lock()
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

class MigrationTests(unittest.TestCase):
    def test_existing_mode_subscriptions_merge_as_recurring_and_old_buttons_resolve(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite3'
            with sqlite3.connect(path) as conn:
                conn.executescript('''
                    CREATE TABLE squad_interest_topics(scope TEXT PRIMARY KEY,guild_id INTEGER NOT NULL,label TEXT NOT NULL);
                    CREATE TABLE squad_interest_members(scope TEXT NOT NULL,user_id INTEGER NOT NULL,last_notified REAL NOT NULL DEFAULT 0,PRIMARY KEY(scope,user_id));
                    CREATE TABLE squad_interest_attempts(session_id TEXT NOT NULL,scope TEXT NOT NULL,attempted_at REAL NOT NULL,PRIMARY KEY(session_id,scope));
                    INSERT INTO squad_interest_topics VALUES ('old-rec',1,'NBA 2K27 · REC');
                    INSERT INTO squad_interest_topics VALUES ('old-park',1,'NBA 2K27 · Park');
                    INSERT INTO squad_interest_members VALUES ('old-rec',10,1000);
                    INSERT INTO squad_interest_members VALUES ('old-park',10,1001);
                    INSERT INTO squad_interest_members VALUES ('old-park',11,1001);
                    INSERT INTO squad_interest_attempts VALUES ('previous','old-rec',1000);
                ''')
            with patch.object(storage, 'STATS_DB', path):
                storage.initialize()
                canonical = storage.topic(1, 'NBA 2K27')['id']
                self.assertEqual(storage.preferences(canonical), {10: 'always', 11: 'always'})
                self.assertEqual(storage.members('old-rec'), [10, 11])
                self.assertEqual(storage.reserve('previous', canonical, [10]), [])
                storage.toggle('old-rec', 1, 10, 'once')
                self.assertEqual(storage.preferences('old-park'), {10: 'once', 11: 'always'})
                storage.initialize.__wrapped__()
                self.assertEqual(storage.preferences(canonical), {10: 'once', 11: 'always'})


class HiddenRosterTests(unittest.TestCase):
    def test_old_roster_fields_removed_without_removing_participants(self):
        embed = discord.Embed(title="足跡")
        embed.add_field(name="一齊玩過", value="Jeff")
        for name in ("🙋 下次叫埋 · 1 人", "🔔 每次都叫 · 1 人", "🙋 下次想玩"):
            embed.add_field(name=name, value="<@123>")
        add_interest_fields(embed, [(123, "Player")], {123: "once"})
        self.assertEqual([(field.name, field.value) for field in embed.fields], [("一齊玩過", "Jeff")])
        add_interest_fields(embed, [(123, "Player")], {123: "always"})
        self.assertEqual(len(embed.fields), 1)
