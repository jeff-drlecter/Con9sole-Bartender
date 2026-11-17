"""Exact trial scope, private configuration and revocation with synthetic fixtures."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from cogs.squad_cards import SquadCards
from cogs.tempvc import TempVCControlView
from features import voice_invites as invites, voice_invite_trial as trial
import test_voice_invites as fixtures

REAL_AUTHORIZE = invites.authorize


class TrialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=fixtures.VoiceShareTests(); self.f.addCleanup=self.addCleanup; self.f.setUp()

    def admin(self):
        f=self.f
        self.admin_member=MagicMock(spec=discord.Member)
        self.admin_member.id=7; self.admin_member.bot=False
        self.admin_member.guild_permissions=discord.Permissions(manage_guild=True)
        other=MagicMock(spec=discord.Member); other.id=8; other.bot=False
        bot=MagicMock(spec=discord.Member); bot.id=42; bot.bot=True
        role=N(id=1,permissions=discord.Permissions.all())
        self.guild=N(id=1,roles=[role],default_role=role,
            fetch_member=AsyncMock(side_effect=lambda uid:{7:self.admin_member,8:other,42:bot}[uid]))
        self.category=MagicMock(spec=discord.CategoryChannel)
        self.category.id=20; self.category.guild=self.guild; self.category.name='arbitrary name'
        self.category.overwrites={}; self.category.permissions_for.return_value=discord.Permissions.all()
        self.destination=MagicMock(spec=discord.TextChannel)
        self.destination.id=30; self.destination.guild=self.guild; self.destination.category_id=20
        self.destination.overwrites={}; self.destination.permissions_for.return_value=discord.Permissions.all()
        self.guild.fetch_channel=AsyncMock(side_effect=lambda cid:{20:self.category,30:self.destination}[cid])
        f.bot.fetch_guild=AsyncMock(return_value=self.guild)

    async def command(self, action, **kwargs):
        i=self.f.interaction(); i.channel_id=30
        await SquadCards.squad_invite_trial.callback(self.f.cog,i,action,**kwargs)
        return i

    async def test_missing_or_unknown_configuration_is_disabled_without_changing_old_cards(self):
        f=self.f
        for config in (None,{},dict(enabled=True),{'schema':2,'enabled':True},dict(f.cog.state['voice_invite_trial'],broad=True)):
            f.cog.state['voice_invite_trial']=config
            await f.cog.share_voice(f.interaction(),10)
            view=TempVCControlView(N(bot=f.bot),channel_id=10,user_id=7)
            self.assertNotIn('招人入隊',{item.label for item in view.children})
        f.auth.assert_not_awaited(); f.voice.create_invite.assert_not_awaited()
        await f.sweep(); f.now+=30; await f.sweep()
        f.destination.send.assert_awaited_once()
        self.assertNotIn('discord.gg',f.message.content)
        self.assertFalse(f.cog.state['sessions']['10'].get('voice_invite'))

    async def test_each_exact_scope_dimension_and_user_fail_closed(self):
        f=self.f; original=copy.deepcopy(f.cog.state['voice_invite_trial'])
        for key,value in [('guild',2),('category',21),('destination',31),('testers',[8]),('guild',True),('testers',[7,8,9])]:
            with self.subTest(key=key,value=value):
                f.cog.state['voice_invite_trial']={**original,key:value}
                await f.cog.share_voice(f.interaction(),10)
                self.assertFalse(f.cog.state['sessions'])
        f.voice.create_invite.assert_not_awaited(); f.auth.assert_not_awaited()
        f.cog.state['voice_invite_trial']=original
        f.destination.guild=N(id=2)
        with self.assertRaises(trial.TrialDenied): trial.require(f.cog,f.voice,f.destination,7)

    async def test_stale_button_and_direct_prepare_cannot_bypass_disabled_scope(self):
        f=self.f
        temp=N(bot=f.bot,_get_control_channel=lambda *args:(f.member,f.voice,None))
        view=TempVCControlView(temp,channel_id=10,user_id=7)
        self.assertIn('招人入隊',{item.label for item in view.children})
        f.cog.state.pop('voice_invite_trial')
        i=f.interaction(); i.response.is_done=lambda:False; i.response.send_message=AsyncMock()
        await view.recruit_button.callback(i)
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])
        session=dict(id='direct',destination=30,voice_invite=dict(state='requested',requester=7,voice=10,trial_revision='a'*32))
        await invites.prepare(f.cog,f.voice,session)
        self.assertTrue(session['voice_invite']['scope_stopped'])
        f.voice.create_invite.assert_not_awaited(); f.auth.assert_not_awaited()

    async def test_private_configure_status_and_disable_use_fresh_admin(self):
        f=self.f; f.cog.state.pop('voice_invite_trial'); self.admin()
        i=await self.command('configure',category=self.category,destination=self.destination,
                             tester_one=N(id=7),tester_two=N(id=8))
        self.assertTrue(trial.settings(f.cog))
        self.assertTrue(i.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(i.followup.send.call_args.kwargs['allowed_mentions'].to_dict(),{'parse':[]})
        self.assertEqual(self.guild.fetch_member.call_args_list[0].args,(7,))
        self.assertEqual(f.cog.state['voice_invite_trial']['testers'],[7,8])
        await self.command('status')
        f.cog.state=json.loads(Path(f.cog.path).read_text())
        self.assertTrue(trial.visible(f.cog,f.voice,7))
        await self.command('disable')
        self.assertIsNone(trial.settings(f.cog))
        self.assertFalse(trial.visible(f.cog,f.voice,7))

    async def test_cached_admin_cannot_override_fresh_non_admin(self):
        f=self.f; self.admin(); self.admin_member.guild_permissions=discord.Permissions.none()
        previous=copy.deepcopy(f.cog.state['voice_invite_trial'])
        i=await self.command('disable')
        self.assertEqual(f.cog.state['voice_invite_trial'],previous)
        self.assertIn('只限',i.followup.send.call_args.args[0])

    async def test_configure_rejects_wrong_route_category_or_origin_channel(self):
        f=self.f; self.admin(); previous=copy.deepcopy(f.cog.state['voice_invite_trial'])
        for failure in ('route','category','origin'):
            with self.subTest(failure=failure):
                f.cog.state['settings']['routes']['20']=31 if failure=='route' else 30
                self.destination.category_id=21 if failure=='category' else 20
                i=f.interaction(); i.channel_id=31 if failure=='origin' else 30
                await SquadCards.squad_invite_trial.callback(f.cog,i,'configure',self.category,self.destination,N(id=7),N(id=8))
                self.assertEqual(f.cog.state['voice_invite_trial'],previous)
        f.voice.create_invite.assert_not_awaited()

    async def test_disable_revokes_and_removes_url_without_reposting_or_removing_controls(self):
        f=self.f; session=await f.ready(); self.admin()
        await self.command('disable')
        self.assertTrue(session['voice_invite']['scope_stopped'])
        f.revoked.delete.assert_awaited_once()
        self.assertNotIn('discord.gg',f.message.content)
        self.assertNotIn('view',f.message.edit.call_args.kwargs)
        self.assertNotIn('ended',session)
        f.cog.state=json.loads(Path(f.cog.path).read_text())
        f.now+=60; await f.sweep(); await f.cog.share_voice(f.interaction(),10)
        f.voice.create_invite.assert_awaited_once(); f.destination.send.assert_awaited_once()

    async def test_route_drift_or_revision_change_revokes_persisted_opt_in(self):
        f=self.f; session=await f.ready()
        f.cog.state['settings']['routes']['20']=31
        f.cog.save(); f.cog.state=json.loads(Path(f.cog.path).read_text())
        await f.sweep()
        f.revoked.delete.assert_awaited_once(); self.assertNotIn('discord.gg',f.message.content)
        self.assertTrue(f.cog.state['sessions']['10']['voice_invite']['scope_stopped'])
        f.cog.state['settings']['routes']['20']=30
        f.cog.state['voice_invite_trial']['revision']='b'*32
        await f.cog.share_voice(f.interaction(),10)
        f.voice.create_invite.assert_awaited_once()

    async def test_scope_drift_during_post_withdraws_known_success_before_publication(self):
        f=self.f
        async def created(**kwargs):
            f.destination.category_id=21
            return N(code='session-code')
        f.voice.create_invite.side_effect=created
        await f.ready()
        f.revoked.delete.assert_awaited_once()
        self.assertNotIn('discord.gg',f.message.content)
        f.destination.send.assert_awaited_once()  # Original automatic card is retained.

    async def test_scope_drift_after_claim_rejects_and_reload_can_post_once(self):
        import cogs.squad_cards as cards
        from features import squad_interest
        f=self.f
        value=squad_interest.topic(1,'Synthetic restore')
        squad_interest.remember(value)
        squad_interest.toggle(value['id'],1,8,'once')
        notified=[]
        real_stats=cards.run_stats
        async def notify(channel,session):
            users=await real_stats(squad_interest.reserve,session['id'],value['id'],[8])
            if users: notified.append(users)
        f.cog.notify_interested=notify
        await f.cog.share_voice(f.interaction(),10)
        async def drift(function,*args,**kwargs):
            result=await real_stats(function,*args,**kwargs)
            if function is squad_interest.begin_card_post:
                f.destination.category_id=21
            return result
        f.now=1030
        with patch.object(cards,'run_stats',side_effect=drift):
            await f.sweep()
        session=f.cog.state['sessions']['10']
        self.assertIsNone(squad_interest.uncertain_card(session['id']))
        self.assertEqual(squad_interest.latest_card_post(session['id'])['state'],'rejected')
        f.destination.send.assert_not_awaited()
        self.assertFalse(notified)
        self.assertEqual(squad_interest.preferences(value['id']),{8:'once'})
        f.destination.category_id=20
        f.cog.state=json.loads(Path(f.cog.path).read_text())
        f.now+=60; await f.sweep()
        await f.sweep(); f.now+=5; await f.sweep()
        f.destination.send.assert_awaited_once()
        f.voice.create_invite.assert_awaited_once()
        self.assertEqual(notified,[[8]])
        self.assertIsNone(squad_interest.uncertain_card(session['id']))

    async def test_deferred_scope_cleanup_cannot_be_bypassed_by_roster_dirty_or_invite_timer(self):
        from cogs.squad_cards import RecruitmentChoices
        f=self.f; session=await f.ready()
        f.cog.state['voice_invite_trial']={'schema':1,'enabled':False}
        f.revoked.delete.side_effect=OSError('synthetic revoke unavailable')
        f.destination.fetch_message.side_effect=discord.Forbidden(N(status=403,reason='Forbidden'),{'message':'denied'})
        await trial.enforce(f.cog,f.voice,session)
        self.assertEqual(session['voice_scope_cleanup']['state'],'deferred')
        self.assertEqual(session['voice_invite']['state'],'revoking')
        count=f.destination.fetch_message.await_count
        f.now+=60; await f.sweep()
        for index in range(3):
            f.now+=5
            session['dirty']=True
            f.member.display_name='Changed '+str(index)
            f.voice.members=[f.member,N(id=8+index,bot=False,display_name='Synthetic peer')]
            await f.sweep()
        self.assertEqual(f.destination.fetch_message.await_count,count)
        self.assertEqual(f.revoked.delete.await_count,2)  # Only the 60-second revoke retry.
        persisted=json.loads(Path(f.cog.path).read_text())['sessions']['10']
        self.assertIn('10',persisted['participants'])  # Backoff does not lose the footprint roster.
        view=RecruitmentChoices(f.cog,'10',session)
        # Explicit settings may try after backoff, but repeated clicks cannot hammer 403.
        with self.assertRaises(discord.Forbidden):
            await view.set_count(f.interaction(),2)
        count+=1
        await view.set_count(f.interaction(),3)
        await f.sweep()
        self.assertEqual(f.destination.fetch_message.await_count,count)
        self.assertEqual(session['missing'],3)  # Desired state is durable while inaccessible.
        # Restoring access and explicitly refreshing resumes normal card behaviour.
        f.now+=60; f.destination.fetch_message.side_effect=None; f.revoked.delete.side_effect=None
        await view.set_count(f.interaction(),3)
        self.assertEqual(session['voice_scope_cleanup']['state'],'done')
        self.assertNotIn(session['id']+':scope',f.cog.state.get('voice_invite_cleanup_pending',{}))
        self.assertIn('缺 3 人',f.message.edit.call_args.kwargs['embed'].title)
        before=f.destination.fetch_message.await_count
        f.member.display_name='Restored roster'; await f.sweep()
        self.assertGreater(f.destination.fetch_message.await_count,before)
        self.assertNotIn('discord.gg',f.message.content)
        f.destination.send.assert_awaited_once(); f.voice.create_invite.assert_awaited_once()



class FreshScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_destination_drift_is_rejected_even_when_cached_scope_matches(self):
        fixture=fixtures.FreshAuthorizationTests(); fixture.fixture()
        cached=N(id=30,guild=fixture.guild,category_id=20)
        fixture.bot.get_channel=lambda cid:fixture.current if cid==10 else cached
        fixture.destination.category_id=21
        with self.assertRaises(trial.TrialDenied):
            await REAL_AUTHORIZE(fixture.bot,1,10,30,7,trial_cog=fixture.trial_cog,trial_revision='a'*32)
        self.assertEqual(fixture.guild.fetch_channel.await_count,2)
        fixture.voice.create_invite.assert_not_called()

    async def test_direct_authorize_without_scope_context_is_closed(self):
        fixture=fixtures.FreshAuthorizationTests(); fixture.fixture()
        with self.assertRaises(trial.TrialDenied):
            await REAL_AUTHORIZE(fixture.bot,1,10,30,7)
        fixture.bot.fetch_guild.assert_not_awaited()
