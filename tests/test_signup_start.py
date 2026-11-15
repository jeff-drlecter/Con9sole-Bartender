"""Offline contract tests for explicit plan consent and the existing receipt journal."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
from features.squad_plans import PlanBook, reminder_recipients, notification_exclusions, public_status
from features import squad_interest as interest
from cogs.squad_cards import SquadCards


class SignupStart(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.db = patch.object(interest, 'STATS_DB', self.path/'stats.db')
        self.db.start(); self.addCleanup(self.db.stop)
        self.book = PlanBook(self.path/'plans.json', clock=lambda:10000)
        self.p = self.book.create(guild=1, channel=30, owner=1, game='FC', mode='PC', start=10100, party=1, capacity=5)
        self.key = self.p['id']; self.book.publish(self.key,99)
        self.topic = interest.topic(1,'FC'); interest.remember(self.topic)

    def act(self, uid, action):
        return self.book.act(self.key,uid,action)

    def test_explicit_consent_leave_rejoin_reconfirm_restart_and_again(self):
        self.act(2,'join'); self.assertEqual(reminder_recipients(self.book.get(self.key)),set())
        self.act(2,'remind_on'); self.act(3,'late'); self.act(3,'remind_on')
        self.assertEqual(reminder_recipients(PlanBook(self.book.path).get(self.key)),{2,3})
        p=self.book.get(self.key)
        changes={k:p[k] for k in ('game','mode','start','party','capacity')}; changes['mode']='PS5'
        self.book.act(self.key,1,'edit',changes=changes)
        self.assertEqual(reminder_recipients(self.book.get(self.key)),set())
        self.assertEqual(notification_exclusions(self.book.get(self.key)),{2,3})
        self.act(2,'join'); self.assertEqual(reminder_recipients(self.book.get(self.key)),{2})
        self.act(2,'leave');self.act(2,'join')
        self.assertEqual(reminder_recipients(self.book.get(self.key)),set())
        self.assertIn(2,notification_exclusions(self.book.get(self.key)))
        self.act(2,'remind_on');self.act(2,'remind_off')
        self.assertNotIn(2,reminder_recipients(self.book.get(self.key)))
        p=self.book.create(guild=1,channel=30,owner=1,game='FC',mode='PC',start=10200,party=1,capacity=5)
        self.assertEqual(p['members'],[]);self.assertEqual(p['reminders'],[])

    def test_full_due_empty_room_do_not_consume(self):
        interest.toggle(self.topic['id'],1,2)
        for uid in (2,3,4,5): self.act(uid,'join')
        with self.assertRaises(ValueError):self.act(6,'join')
        self.book.clock=lambda:10101;self.book.expire()
        self.book.link_voice(self.key,1,20)
        self.assertEqual(self.book.get(self.key)['status'],'gathering')
        self.assertEqual(interest.members(self.topic['id']),[2])
        self.assertNotIn('members',public_status(self.book.get(self.key)))
        self.assertIsNone(public_status(self.book.get(self.key))['attendance'])

    def test_receipts_dedupe_failure_uncertainty_restart(self):
        scope=self.topic['id']
        interest.toggle(scope,1,2);interest.toggle(scope,1,3,'always')
        self.assertEqual(interest.reserve('s',scope,[2,2,3,4],plan_users={2,4}),[2,3,4])
        self.assertEqual(interest.members(scope),[3])
        rev=interest.claim_delivery('s',scope,0)
        self.assertEqual(interest.pending_deliveries('s',scope),[])
        self.assertEqual(interest.reserve('s',scope,[2,3,4],plan_users={2,4}),[])
        interest.finish_delivery('s',scope,0,retry=True,now=10,expected_revision=rev)
        self.assertEqual(interest.pending_deliveries('s',scope,now=70),[(0,[2,3,4])])
        rev=interest.claim_delivery('s',scope,0)
        interest.cancel(scope,1,3)
        self.assertEqual(interest.delivery_users('s',scope,0,rev),[2,4])
        interest.finish_delivery('s',scope,0,message_id=500,expected_revision=rev)
        self.assertEqual(interest.pending_deliveries('s',scope),[])

    async def test_combined_delivery_fresh_permissions_and_withdrawals(self):
        for uid in (2,3,4,5):
            self.act(uid,'join');self.act(uid,'remind_on');interest.toggle(self.topic['id'],1,uid)
        self.act(3,'leave');self.act(4,'remind_off')
        self.book.link_voice(self.key,1,20); self.book.sync_session(self.key,20,'s')
        people={uid:N(id=uid,bot=False,display_name=str(uid)) for uid in (1,2,3,4,5)}
        perms=N(view_channel=True,connect=True)
        # 5 lost access; cache deliberately still contains everyone.
        guild=N(id=1,get_member=lambda uid:people.get(uid),fetch_member=AsyncMock(side_effect=lambda uid:people.get(uid)))
        voice=N(id=20,guild=guild,members=[people[1]],permissions_for=lambda m:N(view_channel=m.id!=5,connect=True))
        dest=N(id=30,permissions_for=lambda m:perms,send=AsyncMock(return_value=N(id=500)))
        plans=N(book=self.book,lock=asyncio.Lock())
        cog=object.__new__(SquadCards);cog.bot=N(get_channel=lambda _:dest,get_cog=lambda _:plans)
        cog.interest_baseline=set();cog.refresh_interest_cards=AsyncMock()
        session=dict(id='s',destination=30,message=99,interest_topic=self.topic,plan_id=self.key)
        await cog.notify_interested(voice,session)
        self.assertEqual(dest.send.await_count,1)
        self.assertEqual(dest.send.await_args.kwargs['allowed_mentions'].to_dict(),{'users':[2,3,4],'parse':[]})
        await cog.notify_interested(voice,session)
        self.assertEqual(dest.send.await_count,1)
        self.assertIn(5,interest.members(self.topic['id']))

    def test_cross_scope_same_session_never_repeats(self):
        other=interest.topic(1,'Other');interest.remember(other)
        interest.toggle(self.topic['id'],1,2);interest.toggle(other['id'],1,2)
        interest.reserve('same',self.topic['id'],[2])
        self.assertEqual(interest.reserve('same',other['id'],[2],plan_users={2}),[])
        self.assertEqual(interest.members(other['id']),[2])

    async def test_unknown_send_result_is_not_replayed(self):
        interest.toggle(self.topic['id'],1,2)
        people={uid:N(id=uid,bot=False,display_name=str(uid)) for uid in (1,2)}
        perms=N(view_channel=True,connect=True)
        guild=N(id=1,fetch_member=AsyncMock(side_effect=lambda uid:people[uid]))
        voice=N(id=20,guild=guild,members=[people[1]],permissions_for=lambda m:perms)
        dest=N(id=30,permissions_for=lambda m:perms,send=AsyncMock(side_effect=TimeoutError()))
        cog=object.__new__(SquadCards);cog.bot=N(get_channel=lambda _:dest)
        cog.interest_baseline=set();cog.refresh_interest_cards=AsyncMock()
        session=dict(id='timeout',destination=30,message=99,interest_topic=self.topic)
        with self.assertLogs('cogs.squad_cards',level='ERROR'):
            await cog.notify_interested(voice,session)
        await cog.notify_interested(voice,session)
        self.assertEqual(dest.send.await_count,1)
        self.assertEqual(interest.pending_deliveries('timeout',self.topic['id']),[])
        # Restart baseline suppresses even a new, previously unsent session.
        interest.toggle(self.topic['id'],1,2)
        session['id']='restart';cog.interest_baseline.add('restart')
        await cog.notify_interested(voice,session)
        self.assertEqual(interest.members(self.topic['id']),[2])
        self.assertEqual(dest.send.await_count,1)

    async def test_fresh_departure_and_permission_change_before_send(self):
        interest.toggle(self.topic['id'],1,2)
        person=N(id=2,bot=False,display_name='two')
        perms=N(view_channel=True,connect=True)
        guild=N(id=1,fetch_member=AsyncMock(side_effect=[person,None]))
        voice=N(id=20,guild=guild,members=[N(id=1,bot=False)],permissions_for=lambda m:perms)
        dest=N(id=30,permissions_for=lambda m:perms,send=AsyncMock())
        cog=object.__new__(SquadCards);cog.bot=N(get_channel=lambda _:dest)
        cog.interest_baseline=set();cog.refresh_interest_cards=AsyncMock()
        session=dict(id='departure',destination=30,message=99,interest_topic=self.topic)
        await cog.notify_interested(voice,session)
        dest.send.assert_not_awaited()
        interest.toggle(self.topic['id'],1,2)
        guild.fetch_member=AsyncMock(side_effect=[person,N(id=2,bot=False,display_name='two',denied=True)])
        voice.permissions_for=lambda m:N(view_channel=not getattr(m,'denied',False),connect=True)
        session['id']='permission'
        await cog.notify_interested(voice,session)
        dest.send.assert_not_awaited()

    async def test_ui_quick_choices_and_consent_owner(self):
        from cogs.squad_plans import InstantChoices, ReminderView, PlanForm
        member=N(id=2,roles=[],voice=N(channel=N(members=[N(bot=False),N(bot=False),N(bot=True)])))
        channel=N(id=30,category=N(name='EA SPORTS FC'))
        cog=N(book=self.book,lock=asyncio.Lock())
        choices=InstantChoices(cog,channel,2)
        self.assertEqual([b.label for b in choices.children],['欠 1 人','欠 2 人','欠 3 人','自訂'])
        i=N(user=member,response=N(send_modal=AsyncMock(),send_message=AsyncMock()))
        with patch('cogs.squad_plans.allowed',return_value=True):
            await choices.children[1].callback(i)
        draft=i.response.send_message.await_args.kwargs['view']
        self.assertEqual(draft.seed['game'],'EA SPORTS FC')
        self.assertEqual(draft.seed['party'],1);self.assertEqual(draft.seed['missing'],2)
        self.act(2,'join');view=ReminderView(cog,self.key,member)
        self.assertFalse(view.children[0].disabled);self.assertTrue(view.children[1].disabled)
        i.user=N(id=3);i.guild_id=1;i.channel_id=30
        await view.children[0].callback(i)
        self.assertEqual(reminder_recipients(self.book.get(self.key)),set())
        # Repeat form copies game/mode only; fresh roster and consent created by PlanBook.
        form=PlanForm(cog,channel,seed=self.book.get(self.key))
        self.assertEqual(form.game.default,'FC')

    async def test_02_status_is_fresh_authorized_and_roster_free(self):
        import config
        from cogs.squad_plans import SquadPlans
        p=self.book.state['plans'][self.key];p['guild']=config.GUILD_ID
        cog=N(book=self.book)
        guild=N(id=config.GUILD_ID,fetch_member=AsyncMock(return_value=N(id=2)),fetch_channel=AsyncMock(return_value=N(id=30)))
        with patch('cogs.squad_plans.can_read',return_value=False):
            self.assertIsNone(await SquadPlans.member_status(cog,guild,2,self.key))
        with patch('cogs.squad_plans.can_read',return_value=True),patch('cogs.squad_plans.allowed',return_value=True),patch('cogs.squad_plans.is_server_admin',return_value=False):
            result=await SquadPlans.member_status(cog,guild,2,self.key)
        self.assertNotIn('members',result);self.assertNotIn('reminders',result)
        self.assertFalse(result['permissions']['edit']);self.assertFalse(result['permissions']['cancel'])
        self.assertEqual(guild.fetch_member.await_count,2)

    def test_old_records_default_off_without_schema_rewrite(self):
        self.act(2,'join')
        state=self.book.state
        state['plans'][self.key].pop('reminders',None)
        state['plans'][self.key].pop('withdrawn',None)
        self.book._write(state)
        old=self.book.path.read_bytes()
        reopened=PlanBook(self.book.path)
        self.assertEqual(reminder_recipients(reopened.get(self.key)),set())
        self.assertEqual(old,self.book.path.read_bytes())

    async def test_private_language(self):
        from cogs.squad_plans import ReminderView, private_copy
        self.act(2,'join')
        hk=N(id=2,roles=[N(name='語境偏好｜香港',managed=False,permissions=N(value=0))])
        tw=N(id=2,roles=[N(name='語境偏好｜台灣',managed=False,permissions=N(value=0))])
        cog=N(book=self.book)
        self.assertEqual(ReminderView(cog,self.key,hk).children[0].label,'呢局開局時提我')
        self.assertEqual(ReminderView(cog,self.key,tw).children[0].label,'本局開局時提醒我')
        self.assertEqual(private_copy(hk,'已取消本局開局提醒。'),'已取消呢局開局提醒。')
