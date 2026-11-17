"""Synthetic Discord fixtures: no live bot, credentials, or production state."""
import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs.squad_cards import SquadCards, RecruitmentChoices
from cogs.squad_plans import PlanView
from cogs.tempvc import TempVCControlView
from features import squad_interest, squad_participants, voice_invites as invites
from features.squad_plans import PlanBook

N = types.SimpleNamespace


class VoiceShareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        for target, value in [('config.GUILD_ID', 1),
                              ('features.squad_interest.STATS_DB', Path(self.tmp.name)/'stats.sqlite3'),
                              ('features.squad_participants.STATS_DB', Path(self.tmp.name)/'stats.sqlite3')]:
            p = patch(target, value); p.start(); self.addCleanup(p.stop)
        p = patch('time.time', side_effect=lambda: self.now); p.start(); self.addCleanup(p.stop)
        self.member = N(id=7, display_name='Host', bot=False)
        self.guild = N(id=1, afk_channel=None)
        self.voice = N(id=10, guild=self.guild, category_id=20, category=N(name=''),
                       members=[self.member], create_invite=AsyncMock(return_value=N(code='session-code')))
        self.guild.voice_channels = [self.voice]
        self.message = N(id=99, content='', author=N(id=42))
        async def edit(**kw):
            if 'content' in kw: self.message.content = kw['content'] or ''
        self.message.edit = AsyncMock(side_effect=edit)
        async def send(**kw):
            self.message.content = kw.get('content', '') or ''
            return self.message
        self.destination = N(id=30, send=AsyncMock(side_effect=send), fetch_message=AsyncMock(return_value=self.message))
        self.plans = None
        self.revoked = N(inviter=N(id=42), channel=N(id=10), delete=AsyncMock())
        self.bot = N(user=N(id=42), get_channel=lambda x:{10:self.voice,30:self.destination}.get(x),
                     get_guild=lambda _:self.guild, is_ready=lambda:True,
                     get_cog=lambda name:self.plans if name=='SquadPlans' else None,
                     fetch_invite=AsyncMock(return_value=self.revoked), add_view=MagicMock())
        self.cog = object.__new__(SquadCards)
        self.cog.bot = self.bot
        self.cog.path = str(Path(self.tmp.name)/'sessions.json')
        self.cog.state = {'settings':{'routes':{'20':30}},'sessions':{}}
        self.cog.lock = asyncio.Lock(); self.cog.arrivals = {}; self.cog.interest_baseline = set()
        self.cog.notify_interested = AsyncMock()
        p = patch.object(invites, 'authorize', new=AsyncMock(return_value=(self.voice,self.destination)))
        self.auth = p.start(); self.addCleanup(p.stop)

        async def create_once(voice, *, max_age, reason, before_send):
            before_send()
            result = await voice.create_invite(max_age=max_age,max_uses=0,temporary=False,unique=True,reason=reason)
            return {'code':result.code}
        p = patch.object(invites.transport, 'create_once', side_effect=create_once)
        p.start(); self.addCleanup(p.stop)

    def interaction(self):
        return N(guild_id=1, user=self.member, response=N(defer=AsyncMock()), followup=N(send=AsyncMock()))

    async def sweep(self):
        async with self.cog.lock: await self.cog.reconcile()

    async def ready(self):
        await self.cog.share_voice(self.interaction(),10)
        self.now += 30
        await self.sweep()
        return self.cog.state['sessions']['10']

    async def test_prethreshold_settings_then_simultaneous_clicks_and_sweeper(self):
        await self.cog.share_voice(self.interaction(),10)
        session = self.cog.state['sessions']['10']
        view = RecruitmentChoices(self.cog,'10',session)
        await view.set_count(self.interaction(),2)
        self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_not_awaited()
        self.cog.notify_interested.assert_not_awaited()
        self.now += 29; await self.sweep()
        self.destination.send.assert_not_awaited()
        self.now += 1
        await asyncio.gather(self.cog.share_voice(self.interaction(),10), self.sweep(),
                             self.cog.share_voice(self.interaction(),10))
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()
        self.assertEqual(self.voice.create_invite.call_args.kwargs['max_age'],3600)
        self.assertTrue(self.voice.create_invite.call_args.kwargs['unique'])
        self.assertEqual(self.message.content.count(invites.PREFIX),1)
        self.assertEqual(session['missing'],2)
        self.assertIsNotNone(self.message.edit.call_args.kwargs['view'])
        self.assertEqual(self.message.edit.call_args.kwargs['allowed_mentions'].to_dict(),{'parse':[]})

    async def test_existing_card_opt_in_updates_without_another_send(self):
        await self.sweep(); self.now += 30; await self.sweep()
        self.assertNotIn('discord.gg',self.message.content)
        await asyncio.gather(*(self.cog.share_voice(self.interaction(),10) for _ in range(3)))
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()
        self.assertIn('discord.gg/session-code',self.message.content)

    async def test_unknown_create_survives_reload_and_is_never_replayed(self):
        self.voice.create_invite.side_effect = asyncio.TimeoutError()
        await self.ready()
        self.cog.state = json.loads(Path(self.cog.path).read_text())
        self.voice.create_invite.side_effect = None
        await self.cog.share_voice(self.interaction(),10)
        await self.sweep()
        self.voice.create_invite.assert_awaited_once()
        self.assertEqual(self.cog.state['sessions']['10']['voice_invite']['state'],'uncertain')
        self.voice.members = []; self.now += 30; await self.sweep(); self.now += 30; await self.sweep()
        self.assertTrue(self.cog.state['voice_invite_uncertain'])
        self.bot.fetch_invite.assert_not_awaited()

    async def test_unknown_send_never_creates_second_invite_or_message(self):
        self.destination.send.side_effect = asyncio.TimeoutError()
        session = await self.ready()
        self.assertIsNotNone(squad_interest.uncertain_card(session['id']))
        self.cog.state = json.loads(Path(self.cog.path).read_text())
        await self.cog.share_voice(self.interaction(),10)
        await self.sweep()
        self.voice.create_invite.assert_awaited_once(); self.destination.send.assert_awaited_once()

    async def test_end_grace_revoke_retry_reload_and_public_entry_removed(self):
        session = await self.ready()
        self.voice.members = []
        await self.sweep(); self.now += 29; await self.sweep()
        self.revoked.delete.assert_not_awaited()
        self.revoked.delete.side_effect = OSError('network')
        self.now += 1; await self.sweep()
        self.assertIn('10',self.cog.state['sessions'])
        self.assertNotIn('discord.gg',self.message.content)
        self.assertIsNone(self.message.edit.call_args.kwargs['view'])
        self.revoked.delete.assert_awaited_once()
        self.cog.state = json.loads(Path(self.cog.path).read_text())
        await self.sweep(); self.revoked.delete.assert_awaited_once()
        self.now += 60; self.revoked.delete.side_effect = None
        await self.sweep()
        self.assertFalse(self.cog.state['sessions']); self.assertEqual(self.revoked.delete.await_count,2)
        self.destination.send.assert_awaited_once()

    async def test_deleted_room_closes_immediately_and_only_exact_bot_code(self):
        await self.ready(); self.guild.voice_channels=[]
        self.revoked.inviter.id = 777
        await self.sweep()
        self.revoked.delete.assert_not_awaited()
        self.assertNotIn('discord.gg',self.message.content)
        self.assertIn('10',self.cog.state['sessions'])
        self.now += 3600; await self.sweep()
        self.assertFalse(self.cog.state['sessions'])

    async def test_permission_denial_does_not_create_intent_or_send(self):
        self.auth.side_effect = invites.ShareDenied('denied')
        inter = self.interaction(); await self.cog.share_voice(inter,10)
        self.assertEqual(self.cog.state['sessions'],{})
        self.voice.create_invite.assert_not_awaited(); self.destination.send.assert_not_awaited()
        self.assertIn('denied',inter.followup.send.call_args.args[0])

    async def test_permissions_change_revokes_and_removes_public_url(self):
        session=await self.ready()
        self.auth.side_effect = invites.ShareDenied('private changed')
        self.now += 60; await self.sweep()
        self.revoked.delete.assert_awaited_once()
        self.assertNotIn('discord.gg',self.message.content)
        self.assertEqual(session['voice_invite']['state'],'revoked')

    async def test_expiry_removes_url_without_renewal(self):
        session=await self.ready(); self.now += 3600; await self.sweep()
        self.assertEqual(session['voice_invite']['state'],'expired')
        self.assertNotIn('discord.gg',self.message.content)
        await self.cog.share_voice(self.interaction(),10)
        self.voice.create_invite.assert_awaited_once()

    async def test_linked_plan_keeps_message_controls_signups_and_no_send(self):
        book=PlanBook(Path(self.tmp.name)/'plans.json',clock=lambda:self.now)
        p=book.create(guild=1,channel=30,owner=7,game='FC',mode='Clubs',start=1100,party=1,capacity=None)
        book.publish(p['id'],99); book.act(p['id'],8,'join'); book.link_voice(p['id'],7,10)
        self.plans=N(book=book,refresh=AsyncMock(),lock=asyncio.Lock())
        session=await self.ready()
        self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_awaited_once()
        self.assertEqual(session['message'],99)
        self.assertEqual(book.get(p['id'])['members'],[8])
        self.assertIsInstance(self.message.edit.call_args.kwargs['view'],PlanView)
        self.assertIn('discord.gg',self.message.content)
        book.sync_session(p['id'],10,session['id'],ended=True)
        self.now += 60; await self.sweep()
        self.revoked.delete.assert_awaited_once(); self.assertNotIn('discord.gg',self.message.content)
        self.destination.send.assert_not_awaited()

    async def test_pending_bound_plan_cancellation_never_falls_back_to_new_card(self):
        book=PlanBook(Path(self.tmp.name)/'plans.json',clock=lambda:self.now)
        p=book.create(guild=1,channel=30,owner=7,game='FC',mode='',start=1100,party=1,capacity=None)
        book.publish(p['id'],99); book.link_voice(p['id'],7,10)
        self.plans=N(book=book,refresh=AsyncMock(),lock=asyncio.Lock())
        await self.cog.share_voice(self.interaction(),10)
        book.act(p['id'],7,'cancel')
        self.now += 30; await self.sweep()
        self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_not_awaited()
        self.assertTrue(self.cog.state['sessions']['10']['missing_card'])

    async def test_opt_in_keeps_startup_notification_baseline(self):
        self.cog.startup_occupied={'10'}
        await self.cog.share_voice(self.interaction(),10)
        self.assertIn(self.cog.state['sessions']['10']['id'],self.cog.interest_baseline)

    async def test_slow_share_leave_rejoin_preserves_event_history(self):
        for cache_already_rejoined in (False,True):
            with self.subTest(cache_already_rejoined=cache_already_rejoined):
                # Each scenario uses a fresh synthetic session in the same fixture.
                self.cog.state['sessions']={}; self.cog.__dict__.pop('_invite_presence_starts',None)
                self.cog.__dict__.pop('_invite_voice_epochs',None)
                self.now=1000; self.member.guild=self.guild
                self.auth.side_effect=None
                await self.cog.share_voice(self.interaction(),10)
                entered,release=asyncio.Event(),asyncio.Event()
                async def delayed(*args,**kwargs):
                    entered.set(); await release.wait(); return self.voice,self.destination
                self.auth.side_effect=delayed; self.now=1010
                share=asyncio.create_task(self.cog.share_voice(self.interaction(),10)); await entered.wait()
                self.now=1020
                self.voice.members=[self.member] if cache_already_rejoined else []
                leave=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=self.voice),N(channel=None)))
                await asyncio.sleep(0)
                self.now=1021; self.voice.members=[self.member]
                rejoin=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=None),N(channel=self.voice)))
                await asyncio.sleep(0); self.now=1040; release.set()
                await asyncio.gather(share,leave,rejoin)
                self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_not_awaited()
                self.assertEqual(self.cog.state['sessions']['10']['qualified'],1021)
        self.auth.side_effect=None; self.now=1051; await self.sweep()
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()

    async def test_disconnect_reconnect_during_slow_authorization_restarts_clock(self):
        await self.cog.share_voice(self.interaction(),10)
        entered,release=asyncio.Event(),asyncio.Event()
        async def delayed(*args,**kwargs):
            entered.set(); await release.wait(); return self.voice,self.destination
        self.auth.side_effect=delayed; self.now=1010
        share=asyncio.create_task(self.cog.share_voice(self.interaction(),10)); await entered.wait()
        self.now=1020; disconnected=asyncio.create_task(self.cog.on_disconnect()); await asyncio.sleep(0)
        self.now=1021; await self.cog.on_resumed()
        self.now=1040; release.set(); await asyncio.gather(share,disconnected)
        await self.sweep()
        self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_not_awaited()
        self.assertEqual(self.cog.state['sessions']['10']['qualified'],1021)
        self.now=1051; await self.sweep()
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()

    async def test_presence_changes_during_prepare_block_invite_post(self):
        await self.cog.share_voice(self.interaction(),10); self.member.guild=self.guild
        entered,release=asyncio.Event(),asyncio.Event()
        async def delayed(*args,**kwargs):
            entered.set(); await release.wait(); return self.voice,self.destination
        self.auth.side_effect=delayed; self.now=1030
        sweep=asyncio.create_task(self.sweep()); await entered.wait()
        self.now=1031; self.voice.members=[]
        leave=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=self.voice),N(channel=None)))
        await asyncio.sleep(0); self.now=1032; self.voice.members=[self.member]
        join=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=None),N(channel=self.voice)))
        await asyncio.sleep(0); self.now=1040; release.set(); await asyncio.gather(sweep,leave,join)
        self.destination.send.assert_not_awaited(); self.voice.create_invite.assert_not_awaited()
        self.now=1062; await self.sweep()
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()

    async def test_card_claim_aborted_before_send_is_rejected_not_uncertain(self):
        import cogs.squad_cards as cards
        await self.cog.share_voice(self.interaction(),10); self.member.guild=self.guild
        entered,release=asyncio.Event(),asyncio.Event(); real_stats=cards.run_stats
        async def delayed(function,*args,**kwargs):
            if function is squad_interest.begin_card_post:
                entered.set(); await release.wait()
            return await real_stats(function,*args,**kwargs)
        self.now=1030
        with patch.object(cards,'run_stats',side_effect=delayed):
            sweep=asyncio.create_task(self.sweep()); await entered.wait()
            self.now=1031; self.voice.members=[]
            leave=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=self.voice),N(channel=None)))
            await asyncio.sleep(0); self.now=1032; self.voice.members=[self.member]
            join=asyncio.create_task(self.cog.on_voice_state_update(self.member,N(channel=None),N(channel=self.voice)))
            await asyncio.sleep(0); release.set(); await asyncio.gather(sweep,leave,join)
        session=self.cog.state['sessions']['10']
        self.assertIsNone(squad_interest.uncertain_card(session['id']))
        self.destination.send.assert_not_awaited()
        self.now=1062; await self.sweep()
        self.destination.send.assert_awaited_once(); self.voice.create_invite.assert_awaited_once()

    async def test_deleted_room_forbidden_card_retires_with_private_evidence(self):
        session=await self.ready(); self.guild.voice_channels=[]
        self.destination.fetch_message.side_effect=discord.Forbidden(N(status=403,reason='Forbidden'),{'message':'denied'})
        await self.sweep()
        self.assertFalse(self.cog.state['sessions'])
        self.assertEqual(session['voice_invite']['state'],'revoked')
        self.assertEqual(self.cog.state['voice_invite_cleanup_pending'][session['id']]['message'],99)
        count=self.destination.fetch_message.await_count
        self.cog.state=json.loads(Path(self.cog.path).read_text())
        for _ in range(3):
            self.now+=5; await self.sweep()
        self.assertEqual(self.destination.fetch_message.await_count,count)
        self.destination.send.assert_awaited_once()

    async def test_message_cleanup_backoff_deadline_survives_restart(self):
        session=await self.ready(); self.guild.voice_channels=[]
        self.destination.fetch_message.side_effect=OSError('offline')
        await self.sweep(); count=self.destination.fetch_message.await_count
        self.cog.state=json.loads(Path(self.cog.path).read_text())
        self.now+=5; await self.sweep()
        self.assertEqual(self.destination.fetch_message.await_count,count)
        self.now+=55; await self.sweep()
        self.assertEqual(self.destination.fetch_message.await_count,count+1)
        self.now+=240; await self.sweep()
        self.assertFalse(self.cog.state['sessions'])
        self.assertIn(session['id'],self.cog.state['voice_invite_cleanup_pending'])
        self.destination.send.assert_awaited_once()

    async def test_old_room_controls_remain_and_share_is_private(self):
        view=TempVCControlView(N(bot=self.bot),channel_id=10)
        labels={b.label for b in view.children}
        self.assertTrue({'改名','改人數上限','刪除小隊 call','返回吧枱','加入語音房','招人入隊'} <= labels)
        inter=self.interaction(); await self.cog.share_voice(inter,10)
        self.assertTrue(inter.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])


class AudienceTests(unittest.TestCase):
    def test_public_voice_is_compatible_but_member_denial_rejects_broad_destination(self):
        role=N(id=1,permissions=discord.Permissions(view_channel=True,connect=True))
        guild=N(roles=[role],default_role=role)
        permissions=lambda _:discord.Permissions(view_channel=True,connect=True)
        voice=N(permissions_for=permissions,overwrites={})
        destination=N(overwrites={})
        self.assertTrue(invites.compatible_audience(guild,voice,destination))
        target=discord.Object(id=9)
        voice.overwrites[target]=discord.PermissionOverwrite(connect=False)
        self.assertFalse(invites.compatible_audience(guild,voice,destination))

    def test_matching_private_audience_proves_access_without_changing_permissions(self):
        role=N(id=1,permissions=discord.Permissions.none())
        guild=N(roles=[role],default_role=role)
        target=discord.Object(id=9)
        voice=N(permissions_for=lambda _:discord.Permissions.none(),
                overwrites={target:discord.PermissionOverwrite(view_channel=True,connect=True)})
        destination=N(overwrites={target:discord.PermissionOverwrite(view_channel=True)})
        self.assertTrue(invites.compatible_audience(guild,voice,destination))
        destination.overwrites={}
        self.assertFalse(invites.compatible_audience(guild,voice,destination))

    def test_real_discord_private_view_gate_keeps_raw_connect_for_visible_role(self):
        client=discord.Client(intents=discord.Intents.none())
        base=discord.Permissions(view_channel=True,connect=True)
        guild=discord.Guild(state=client._connection,data={'id':'1','name':'synthetic','owner_id':'99',
            'roles':[{'id':'1','name':'@everyone','permissions':str(base.value)},
                     {'id':'2','name':'Verified','permissions':'0'},
                     {'id':'3','name':'Other','permissions':'0'}]})
        view=discord.Permissions(view_channel=True).value
        overwrites=[{'id':'1','type':0,'allow':'0','deny':str(view)},
                    {'id':'2','type':0,'allow':str(view),'deny':'0'}]
        voice=discord.VoiceChannel(state=client._connection,guild=guild,
            data={'id':'10','type':2,'name':'private','position':0,'bitrate':64000,'user_limit':0,'permission_overwrites':overwrites})
        destination=discord.TextChannel(state=client._connection,guild=guild,
            data={'id':'30','type':0,'name':'private-text','position':0,'permission_overwrites':overwrites})
        self.assertFalse(voice.permissions_for(guild.default_role).connect)
        self.assertTrue(voice.permissions_for(guild.get_role(2)).connect)
        self.assertTrue(destination.permissions_for(guild.get_role(2)).view_channel)
        self.assertTrue(invites.compatible_audience(guild,voice,destination))
        broader=discord.TextChannel(state=client._connection,guild=guild,
            data={'id':'31','type':0,'name':'broader','position':0,'permission_overwrites':overwrites+[
                {'id':'3','type':0,'allow':str(view),'deny':'0'}]})
        self.assertFalse(invites.compatible_audience(guild,voice,broader))



class FreshAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        self.member=MagicMock(spec=discord.Member); self.member.id=7
        self.me=MagicMock(spec=discord.Member); self.me.id=42
        self.vp=discord.Permissions(view_channel=True,connect=True,create_instant_invite=True)
        self.dp=discord.Permissions(view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
        self.voice=MagicMock(spec=discord.VoiceChannel); self.voice.id=10; self.voice.user_limit=4
        self.voice.overwrites={}; self.voice.permissions_for.return_value=self.vp
        self.destination=MagicMock(spec=discord.TextChannel); self.destination.id=30
        self.destination.overwrites={}; self.destination.permissions_for.return_value=self.dp
        role=N(id=1,permissions=self.vp)
        self.guild=N(default_role=role,roles=[role],
            fetch_member=AsyncMock(side_effect=lambda uid:self.member if uid==7 else self.me),
            fetch_channel=AsyncMock(side_effect=lambda cid:self.voice if cid==10 else self.destination))
        self.current=N(members=[N(id=7,bot=False)])
        self.bot=N(user=N(id=42),fetch_guild=AsyncMock(return_value=self.guild),get_channel=lambda _:self.current,is_ready=lambda:True)

    async def test_fresh_guild_roles_channels_and_members_used(self):
        self.fixture()
        with patch('cogs.tempvc.tempvc_storage.creator_id',return_value=7):
            result=await invites.authorize(self.bot,1,10,30,7)
        self.assertEqual(result,(self.voice,self.destination))
        self.bot.fetch_guild.assert_awaited_once_with(1)
        self.assertEqual([c.args[0] for c in self.guild.fetch_member.call_args_list],[7,42])
        self.assertEqual([c.args[0] for c in self.guild.fetch_channel.call_args_list],[10,30])

    async def test_permission_denials_full_room_and_departure_fail_closed(self):
        for bit in ('view_channel','connect','create_instant_invite','send_messages','embed_links','read_message_history','full','left'):
            with self.subTest(bit=bit):
                self.fixture()
                if bit=='full': self.voice.user_limit=1
                elif bit=='left': self.current.members=[]
                elif bit in ('connect','create_instant_invite'): setattr(self.vp,bit,False)
                else: setattr(self.dp,bit,False)
                with patch('cogs.tempvc.tempvc_storage.creator_id',return_value=7):
                    with self.assertRaises(invites.ShareDenied):
                        await invites.authorize(self.bot,1,10,30,7)
                self.voice.create_invite.assert_not_called()

    async def test_former_admin_does_not_use_cached_authority(self):
        self.fixture()
        with patch('cogs.tempvc.tempvc_storage.creator_id',return_value=8), patch('cogs.tempvc.user_can_admin_teardown',return_value=False) as admin:
            with self.assertRaises(invites.ShareDenied):
                await invites.authorize(self.bot,1,10,30,7)
            admin.assert_called_once_with(self.member)
