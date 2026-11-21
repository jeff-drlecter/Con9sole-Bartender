import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from features.squad_plans import PlanBook, confirmed
from features.plan_delivery import PlanDelivery, options, fingerprint, same_audience, event_url
from features.plan_services import AccessError


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.now = 10000
        self.book = PlanBook(Path(self.tmp.name) / 'plans.json', clock=lambda: self.now)
        self.channel = N(id=20, send=AsyncMock(return_value=N(id=777)))
        self.guild = N(id=config.GUILD_ID, create_scheduled_event=AsyncMock(),
                       fetch_scheduled_event=AsyncMock(), fetch_scheduled_events=AsyncMock(return_value=[]))
        self.cog = N(book=self.book, lock=asyncio.Lock(), bot=N(user=N(id=9), get_guild=lambda _:self.guild))
        self.delivery = PlanDelivery(self.cog)
        self.delivery.access = AsyncMock(return_value=(self.guild, self.channel, N(id=9)))
        self.voice = N(id=50)
        self.delivery.destination = AsyncMock(return_value=self.voice)
        self.delivery.valid_members = AsyncMock(side_effect=lambda g,c,p: confirmed(p))
        async def create(**kw):
            e = N(id=88, creator_id=9, name=kw['name'], description=kw['description'],
                  channel_id=kw['channel'].id, start_time=kw['start_time'],
                  entity_type=discord.EntityType.voice, status=discord.EventStatus.scheduled)
            async def edit(**changes):
                for field in ('name', 'description', 'start_time', 'status'):
                    if field in changes: setattr(e, field, changes[field])
                if 'channel' in changes:e.channel_id=changes['channel'].id
                return e
            e.edit = AsyncMock(side_effect=edit)
            self.guild.fetch_scheduled_event.return_value = e
            self.guild.fetch_scheduled_events.return_value = [e]
            return e
        self.guild.create_scheduled_event.side_effect = create

    def make(self, *, party=1, capacity=4, instant=False, legacy=False, **delivery_options):
        p = self.book.create(guild=self.guild.id, channel=20, owner=1, game='Cross-game', mode='PC',
            start=11000, party=party, capacity=capacity, instant=instant,
            delivery_options=None if legacy else options(party, capacity, instant=instant, **delivery_options))
        self.book.publish(p['id'], 99)
        return p['id']

    async def process(self, key):
        async with self.cog.lock:
            await self.delivery.reconcile_event(self.book.get(key))
            await self.delivery.flush_notices(self.book.get(key))

    async def test_threshold_declared_party_late_not_attendance_or_reminder(self):
        k=self.make(party=2,capacity=4)
        self.book.act(k,2,'late'); await self.process(k)
        self.guild.create_scheduled_event.assert_not_awaited()
        self.book.act(k,3,'join'); await self.process(k)
        self.guild.create_scheduled_event.assert_awaited_once()
        p=self.book.get(k)
        self.assertEqual(p['status'],'open'); self.assertEqual(p['reminders'],[])
        self.assertIn('預計 4 人', self.guild.create_scheduled_event.await_args.kwargs['description'])
        self.assertEqual(p['delivery']['event']['state'],'linked')
        self.now+=31; await self.process(k)
        self.channel.send.assert_awaited_once()
        call=self.channel.send.await_args
        self.assertIn('新增 2 人',call.args[0]); self.assertIn('1 人稍後到',call.args[0])
        self.assertIn('活動已建立',call.args[0])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict()['users'],[1])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict()['parse'],[])

    async def test_concurrent_final_slot_and_event_create_once(self):
        k=self.make(capacity=2)
        async def join(uid):
            async with self.cog.lock:
                try:self.book.act(k,uid,'join')
                except ValueError:return False
                await self.delivery.reconcile_event(self.book.get(k)); return True
        self.assertEqual(sum(await asyncio.gather(join(2),join(3))),1)
        await self.process(k)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_legacy_instant_unlimited_never_infer_event(self):
        for params in [dict(legacy=True),dict(instant=True),dict(capacity=None)]:
            k=self.make(**params);self.book.act(k,2,'join');await self.process(k)
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_cleared_threshold_survives_publication_restart_and_notice_change(self):
        from features.plan_delivery_ui import Draft, Numbers, Settings

        settings = dict(minimum=None, auto_event=False, host_notices=True)
        owner = N(id=1)
        data = dict(game='Cross-game', mode='PC', start=11000, party=1, capacity=2)
        draft = Draft(self.cog, self.channel, owner, data)
        form = Numbers(draft, owner)
        form.minimum._value = ''
        with patch.object(draft, 'authorize_update', new=AsyncMock(return_value=True)):
            await form.on_submit(N(edit_original_response=AsyncMock()))
        self.assertEqual(draft.settings, settings)
        p = self.book.create(guild=self.guild.id, channel=20, owner=1,
                             delivery_options=draft.settings, **draft.data)
        key = p['id']
        self.book.publish(key, 99)
        self.book.act(key, 2, 'join')
        await self.process(key)
        self.guild.create_scheduled_event.assert_not_awaited()

        reopened = PlanBook(self.book.path, clock=lambda: self.now)
        p = reopened.get(key)
        self.assertEqual(p['delivery']['settings'], settings)
        self.assertTrue(Settings(self.cog, p, N(id=1)).auto.disabled)
        with self.assertRaises(ValueError):
            reopened.delivery_settings(key, 1, dict(settings, auto_event=True),
                                       expected_revision=p['revision'])
        updated = reopened.delivery_settings(key, 1, dict(settings, host_notices=False),
                                             expected_revision=p['revision'])
        self.assertEqual(updated['delivery']['settings'], dict(settings, host_notices=False))

    async def test_adding_capacity_preserves_absent_threshold(self):
        key = self.make(capacity=None)
        plan = self.book.get(key)
        changes = {name: plan[name] for name in ('game', 'mode', 'start', 'party', 'capacity')}
        changes['capacity'] = 4
        self.book.act(key, 1, 'edit', changes=changes)
        self.assertIsNone(PlanBook(self.book.path).get(key)['delivery']['settings']['minimum'])

    async def test_default_threshold_zero_and_legacy_settings(self):
        self.assertEqual(options(1, 4), dict(minimum=4, auto_event=True, host_notices=True))
        with self.assertRaises(ValueError):
            options(1, 4, minimum=0, auto=False)
        key = self.make(legacy=True)
        reopened = PlanBook(self.book.path, clock=lambda: self.now)
        legacy = reopened.get(key)
        self.assertNotIn('delivery', legacy)
        chosen = dict(minimum=None, auto_event=False, host_notices=True)
        saved = reopened.delivery_settings(key, 1, chosen, expected_revision=legacy['revision'])
        self.assertEqual(saved['delivery']['settings'], chosen)

    async def test_published_already_meets_minimum_only_once(self):
        k=self.make(party=2,capacity=4,minimum=2)
        await self.process(k);await self.process(k)
        self.guild.create_scheduled_event.assert_awaited_once()
        self.channel.send.assert_not_awaited()

    async def test_repeat_late_change_leave_rejoin_no_duplicate_host_notice(self):
        k=self.make()
        self.book.act(k,2,'join')
        with self.assertRaises(ValueError):self.book.act(k,2,'join')
        self.book.act(k,2,'late'); self.book.act(k,2,'leave');self.book.act(k,2,'join')
        self.now+=31;await self.process(k)
        self.assertEqual(len(self.book.get(k)['delivery']['notices']),1)
        self.channel.send.assert_awaited_once()
        self.book.act(k,2,'leave');self.book.act(k,2,'join');self.now+=31;await self.process(k)
        self.channel.send.assert_awaited_once()

    async def test_notice_disabled_and_reenabled_never_backfills(self):
        k=self.make();self.book.act(k,2,'join');p=self.book.get(k)
        s=dict(p['delivery']['settings'],host_notices=False)
        self.book.delivery_settings(k,1,s,expected_revision=p['revision'])
        p=self.book.get(k);s['host_notices']=True
        self.book.delivery_settings(k,1,s,expected_revision=p['revision'])
        self.now+=31;await self.process(k)
        self.channel.send.assert_not_awaited()

    async def test_restart_never_sends_old_queued_notice(self):
        k=self.make();self.book.act(k,2,'join')
        self.book=PlanBook(self.book.path,clock=lambda:self.now);self.cog.book=self.book
        self.delivery=PlanDelivery(self.cog);self.delivery.recover();self.now+=31
        await self.delivery.flush_notices(self.book.get(k))
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.book.get(k)['delivery']['notices'][0]['state'],'skipped_restart')

    async def test_notice_timeout_preserves_unknown_no_replay(self):
        k=self.make();self.book.act(k,2,'join');self.now+=31
        self.channel.send.side_effect=TimeoutError()
        await self.process(k);await self.process(k)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.book.get(k)['delivery']['notices'][0]['state'],'unknown')

    async def test_send_intent_exists_before_transport(self):
        k=self.make();self.book.act(k,2,'join');self.now+=31
        async def send(*a,**kw):
            persisted=PlanBook(self.book.path,clock=lambda:self.now).get(k)
            self.assertEqual(persisted['delivery']['notices'][0]['state'],'sending')
            return N(id=3)
        self.channel.send.side_effect=send
        await self.process(k)

    async def test_revoked_withdrawn_unconfirmed_not_notified(self):
        k=self.make();self.book.act(k,2,'join');self.book.act(k,2,'leave')
        self.now+=31;await self.process(k);self.channel.send.assert_not_awaited()
        k=self.make();self.book.act(k,3,'join')
        p=self.book.get(k)
        self.book.act(k,1,'edit',changes={**{x:p[x] for x in ('game','mode','start','party','capacity')},'start':12000})
        self.now+=31;await self.process(k);self.channel.send.assert_not_awaited()
        self.book.act(k,3,'join');self.now+=31;await self.process(k)
        self.channel.send.assert_not_awaited()

    async def test_source_failure_never_empty_success_or_send(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');self.now+=31
        self.delivery.access.side_effect=AccessError('denied')
        await self.process(k)
        self.channel.send.assert_not_awaited();self.guild.create_scheduled_event.assert_not_awaited()
        self.assertEqual(self.book.get(k)['delivery']['notices'][0]['state'],'skipped_access')

    async def test_visibility_failure_disables_instead_of_external_fallback(self):
        k=self.make(capacity=2);self.book.act(k,2,'join')
        self.delivery.destination.return_value=None
        await self.process(k)
        p=self.book.get(k)
        self.assertFalse(p['delivery']['settings']['auto_event'])
        self.assertEqual(p['delivery']['event']['state'],'blocked')
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_create_timeout_read_reconcile_no_recreate(self):
        k=self.make(capacity=2);self.book.act(k,2,'join')
        actual=self.guild.create_scheduled_event.side_effect
        async def ambiguous(**kw):
            self.assertEqual(PlanBook(self.book.path).get(k)['delivery']['event']['state'],'creating')
            await actual(**kw);raise TimeoutError()
        self.guild.create_scheduled_event.side_effect=ambiguous
        await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['state'],'unknown')
        self.assertIsNone(event_url(self.book.get(k)))
        await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['id'],88)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_unknown_without_match_stays_unknown(self):
        k=self.make(capacity=2);self.book.act(k,2,'join')
        self.guild.create_scheduled_event.side_effect=TimeoutError()
        await self.process(k);await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['state'],'unknown')
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_403_is_failed_and_never_claimed_created(self):
        k=self.make(capacity=2);self.book.act(k,2,'join')
        self.guild.create_scheduled_event.side_effect=discord.Forbidden(N(status=403,reason='denied'),'')
        await self.process(k);self.now+=31;await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['state'],'failed')
        self.assertNotIn('活動已建立',self.channel.send.await_args.args[0])

    async def test_count_fall_keeps_event_reschedule_cancel_synchronize(self):
        k=self.make(capacity=3);self.book.act(k,2,'join');self.book.act(k,3,'join')
        await self.process(k);event=self.guild.fetch_scheduled_event.return_value
        self.book.act(k,2,'leave');await self.process(k)
        self.assertEqual(event.status,discord.EventStatus.scheduled)
        p=self.book.get(k)
        self.book.act(k,1,'edit',changes={**{x:p[x] for x in ('game','mode','start','party','capacity')},'start':12000})
        await self.process(k)
        self.assertEqual(int(event.start_time.timestamp()),12000)
        self.assertEqual(self.book.get(k)['unconfirmed'],[3])
        self.book.act(k,1,'cancel');await self.process(k)
        self.assertEqual(event.status,discord.EventStatus.cancelled)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_manual_edit_or_delete_never_overwritten_or_recreated(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        e=self.guild.fetch_scheduled_event.return_value;e.name='Manual'
        await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['state'],'conflict')
        e.edit.assert_not_awaited()
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        self.guild.fetch_scheduled_event.side_effect=discord.NotFound(N(status=404,reason='deleted'),'')
        await self.process(k);await self.process(k)
        self.assertEqual(self.book.get(k)['delivery']['event']['state'],'deleted')
        self.assertEqual(self.guild.create_scheduled_event.await_count,2)

    async def test_event_interest_not_an_rsvp_actual_session_only_starts(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        e=self.guild.fetch_scheduled_event.return_value;e.user_count=99
        self.now=11001;await self.process(k)
        self.assertEqual(self.book.get(k)['members'],[2]);self.assertEqual(e.status,discord.EventStatus.scheduled)
        self.book.link_voice(k,1,50);self.book.sync_session(k,50,'real-session');await self.process(k)
        self.assertEqual(e.status,discord.EventStatus.active)
        self.book.sync_session(k,50,'real-session',ended=True);await self.process(k)
        self.assertEqual(e.status,discord.EventStatus.completed)

    async def test_owner_and_revision_checks_cannot_change_others_settings(self):
        k=self.make();p=self.book.get(k);s=dict(p['delivery']['settings'],host_notices=False)
        with self.assertRaises(ValueError):self.book.delivery_settings(k,2,s,expected_revision=0)
        self.book.act(k,2,'join')
        with self.assertRaises(ValueError):self.book.delivery_settings(k,1,s,expected_revision=0)
        self.assertTrue(self.book.get(k)['delivery']['settings']['host_notices'])

    async def test_real_acl_bits_reject_wider_event(self):
        def channel(typ, overwrites):
            ch=MagicMock(spec=typ);ch.guild=N(id=1);ch.category_id=5;ch._overwrites=overwrites;return ch
        bit=discord.Permissions.view_channel.flag
        source=channel(discord.TextChannel,[N(id=1,type=0,allow=0,deny=bit),N(id=2,type=0,allow=bit,deny=0)])
        voice=channel(discord.VoiceChannel,copy.deepcopy(source._overwrites))
        self.assertTrue(same_audience(source,voice))
        voice._overwrites=[];self.assertFalse(same_audience(source,voice))
        voice._overwrites=copy.deepcopy(source._overwrites);voice._overwrites.append(N(id=123,type=1,allow=bit,deny=0))
        self.assertFalse(same_audience(source,voice))

    async def test_draft_explicit_summary_cancel_other_user_and_settings(self):
        from features.plan_delivery_ui import Draft
        owner=N(id=1)
        data=dict(game='FC',mode='PC',party=2,capacity=4,start=11000,instant=False)
        view=Draft(self.cog,N(id=20),owner,data)
        self.assertIn('4 人成局',view.summary());self.assertIn('有人報名時提醒我：開啟',view.summary())
        i=N(user=N(id=2),response=N(send_message=AsyncMock(),edit_message=AsyncMock(),defer=AsyncMock()),
            followup=N(send=AsyncMock()),edit_original_response=AsyncMock())
        await view.publish.callback(i);self.assertEqual(self.book.all(),[])
        i.user=owner;i.guild=self.guild
        with patch('features.plan_services.fresh_source',new=AsyncMock(return_value=(owner,N(id=20)))):
            await view.notice.callback(i);self.assertFalse(view.settings['host_notices'])
            await view.cancel.callback(i)
        self.assertTrue(view.used);self.assertEqual(self.book.all(),[])

    async def test_permission_changes_after_member_scan_stop_notice(self):
        k=self.make();self.book.act(k,2,'join');self.now+=31
        self.delivery.access.side_effect=[(self.guild,self.channel,N(id=9)),AccessError('denied')]
        await self.delivery.flush_notices(self.book.get(k))
        self.channel.send.assert_not_awaited()

    async def test_state_changes_during_rest_read_do_not_create_or_ping(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');self.now+=31
        async def changed(*args):
            self.book.act(k,2,'leave')
            return [2]
        self.delivery.valid_members.side_effect=changed
        await self.delivery.reconcile_event(self.book.get(k))
        self.guild.create_scheduled_event.assert_not_awaited()
        self.book.act(k,2,'join')
        await self.delivery.flush_notices(self.book.get(k))
        self.channel.send.assert_not_awaited()

    async def test_actual_destination_permissions_and_acl(self):
        from features.tempvc_settings import get_hub_channel_name
        bit=discord.Permissions.view_channel.flag
        source=MagicMock(spec=discord.TextChannel);source.id=20;source.guild=N(id=1);source.category_id=8
        source._overwrites=[N(id=1,type=0,allow=0,deny=bit)]
        voice=MagicMock(spec=discord.VoiceChannel);voice.id=50;voice.guild=N(id=1);voice.category_id=8
        voice.name=get_hub_channel_name();voice._overwrites=copy.deepcopy(source._overwrites)
        perms=discord.Permissions.none();perms.view_channel=True;perms.connect=True;perms.create_events=True
        voice.permissions_for.return_value=perms
        self.guild.fetch_channels=AsyncMock(return_value=[voice])
        actual=PlanDelivery(self.cog)
        self.assertEqual(await actual.destination(self.guild,source,N(id=9),{'status':'open'}),voice)
        perms.create_events=False
        self.assertIsNone(await actual.destination(self.guild,source,N(id=9),{'status':'open'}))
        perms.create_events=True;voice._overwrites=[]
        self.assertIsNone(await actual.destination(self.guild,source,N(id=9),{'status':'open'}))

    async def test_live_permission_widening_closes_linked_event(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        event=self.guild.fetch_scheduled_event.return_value
        self.delivery.destination.return_value=None
        await self.process(k)
        self.assertEqual(event.status,discord.EventStatus.cancelled)
        self.assertFalse(self.book.get(k)['delivery']['settings']['auto_event'])

    async def test_corrupt_delivery_preserves_file_and_restart_retains_receipts(self):
        import json
        k=self.make();self.book.act(k,2,'join');self.now+=31;await self.process(k)
        before=self.book.path.read_bytes();reopened=PlanBook(self.book.path,clock=lambda:self.now)
        self.assertEqual(reopened.get(k)['delivery'],self.book.get(k)['delivery'])
        self.assertEqual(self.book.path.read_bytes(),before)
        data=json.loads(before);data['plans'][k]['delivery']['notices'][0]['users']=['not-a-user']
        self.book.path.write_text(json.dumps(data));bad=self.book.path.read_bytes()
        with self.assertRaises(ValueError):PlanBook(self.book.path)
        self.assertEqual(self.book.path.read_bytes(),bad)

    async def test_sdk_form_defaults_keep_custom_game_mode_and_start(self):
        from cogs.squad_plans import PlanForm
        f=PlanForm(self.cog,N(id=20,category=None),seed=dict(game='Custom',mode='PS5',party=2,missing=3,start='明天 22:00'))
        self.assertEqual((f.game.value,f.mode.value,f.start.value),('Custom','PS5','明天 22:00'))

    async def test_deleted_source_closes_owned_event_and_no_host_ping(self):
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        event=self.guild.fetch_scheduled_event.return_value
        self.delivery.access.side_effect=AccessError('card_deleted');self.now+=31
        await self.process(k)
        self.assertEqual(event.status,discord.EventStatus.cancelled)
        self.channel.send.assert_not_awaited()

    async def test_locales_are_private_and_public_event_stays_neutral(self):
        from features.plan_delivery_ui import summary
        def member(name):return N(id=1,roles=[N(name=name,managed=False,permissions=discord.Permissions.none())])
        data=dict(game='Test',mode='PC',party=1,capacity=3,start=11000)
        s=options(1,3)
        self.assertIn('夠人',summary(member('語境偏好｜香港'),data,s))
        self.assertIn('達標',summary(member('語境偏好｜台灣'),data,s))
        self.assertIn('達標',summary(N(id=1),data,s))
        k=self.make(capacity=2);self.book.act(k,2,'join');await self.process(k)
        self.assertNotIn('夠人',self.guild.create_scheduled_event.await_args.kwargs['description'])

    async def test_ineligible_confirmed_members_do_not_meet_threshold(self):
        k=self.make(capacity=3);self.book.act(k,2,'join');self.book.act(k,3,'join')
        self.delivery.valid_members.return_value=[2]
        self.delivery.valid_members.side_effect=None
        await self.process(k);self.guild.create_scheduled_event.assert_not_awaited()

    async def test_double_preview_submit_consumes_once_after_fresh_access(self):
        from features.plan_delivery_ui import Draft
        from cogs.squad_plans import PlanForm
        owner=N(id=1);ch=N(id=20)
        view=Draft(self.cog,ch,owner,dict(game='FC',mode='PC',party=1,capacity=2,start=11000))
        def inter():return N(user=owner,guild=self.guild,response=N(send_message=AsyncMock()))
        with patch.object(PlanForm,'on_submit',new_callable=AsyncMock) as submit:
            await asyncio.gather(view.publish.callback(inter()),view.publish.callback(inter()))
            submit.assert_awaited_once()

    async def test_member_http_failures_are_unknown_not_zero_and_bots_excluded(self):
        k=self.make();self.book.act(k,2,'join');self.book.act(k,3,'join')
        snapshot=N(id=config.GUILD_ID)
        ch=N(guild=snapshot)
        self.guild.fetch_member=AsyncMock(side_effect=lambda uid:N(id=uid,bot=uid==3,guild=N(id=0)))
        actual=PlanDelivery(self.cog)
        with patch('cogs.squad_plans.allowed',side_effect=lambda i:i.user.guild is snapshot):
            self.assertEqual(await actual.valid_members(self.guild,ch,self.book.get(k)),[2])
            self.guild.fetch_member.side_effect=OSError('offline')
            with self.assertRaises(AccessError):await actual.valid_members(self.guild,ch,self.book.get(k))
