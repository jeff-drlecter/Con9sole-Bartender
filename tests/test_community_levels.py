import asyncio
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from features.community_levels import Ledger, battle_identity, calendar, level_for, threshold
from cogs.community_levels import CommunityLevels, eligible, voice_members


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'levels.sqlite3'
        self.store=Ledger(self.path)
        self.store.configure(1,mode='preview')

    def tearDown(self): self.tmp.cleanup()

    def test_off_and_restart_and_no_cross_guild_leak(self):
        self.assertIsNone(self.store.award(2,10,'text','m1',100))
        self.assertEqual(self.store.award(1,10,'text','m1',100),(0,1))
        self.assertEqual(Ledger(self.path).profile(1,10)['total'],1)
        self.assertEqual(self.store.profile(2,10)['total'],0)

    def test_shared_cooldown_receipt_consumed_during_cooldown_and_restart(self):
        self.store.award(1,10,'text','m1',100)
        self.assertIsNone(self.store.award(1,10,'activity','m2',110))
        self.assertIsNone(Ledger(self.path).award(1,10,'activity','m2',180))
        self.assertEqual(self.store.award(1,10,'activity','m3',180),(1,2))
        self.assertEqual(self.store.profile(1,10)['activity'],1)

    def test_concurrent_writers_and_daily_cap(self):
        self.store.configure(1,activity_daily_cap=1)
        def award(_): return Ledger(self.path).award(1,10,'activity','same',100)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(award,range(4)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertIsNone(self.store.award(1,10,'activity','next',200))
        self.assertIsNotNone(self.store.award(1,10,'activity','tomorrow',100+86400))

    def test_booster_voice_is_independent_and_weekly_admin_points_excluded(self):
        self.assertEqual(self.store.award(1,10,'text','m1',100,multiplier=2),(0,2))
        self.assertEqual(self.store.award(1,10,'voice','v1',101,multiplier=2),(2,27))
        self.store.adjust(1,10,99,100,'correction',102)
        self.assertEqual(self.store.leaderboard(1,calendar(100)[1]),[(10,27)])
        self.assertEqual(self.store.leaderboard(1,calendar(100+8*86400)[1]),[])

    def test_curve_boundaries_and_import_level_baseline_preserves_earned(self):
        for level in [0,1,5,15,100,400,10000]:
            self.assertEqual(level_for(threshold(level)),level)
            if level: self.assertEqual(level_for(threshold(level)-1),level-1)
        self.store.award(1,10,'text','m1',100)
        self.assertEqual(self.store.import_levels(1,[(10,15)],100),1)
        self.assertEqual(self.store.profile(1,10)['total'],1)
        self.store.import_levels(1,[(10,15)],100,commit=True)
        self.assertEqual(self.store.profile(1,10)['total'],threshold(15)+1)
        with self.assertRaises(ValueError): self.store.import_levels(1,[(10,15)],100,commit=True)

    def test_import_validation_is_atomic_and_bindings_are_scoped(self):
        for rows in [[],[(10,5),(10,6)],[(10,-1)]]:
            with self.assertRaises(ValueError): self.store.import_levels(1,rows,100,commit=True)
        self.assertEqual(self.store.profile(1,10)['total'],0)
        self.store.bind(1,20,'example',10)
        self.assertEqual(self.store.resolve(1,20,'example'),10)
        self.assertIsNone(self.store.resolve(2,20,'example'))
        self.assertIsNone(self.store.resolve(1,21,'example'))

    def test_calendar_is_hong_kong_monday(self):
        from datetime import datetime,timezone
        before=datetime(2026,11,8,15,59,tzinfo=timezone.utc).timestamp()
        self.assertEqual(calendar(before)[1],'2026-W45')
        self.assertEqual(calendar(before+60)[1],'2026-W46')

    def test_durable_repair_queue_backoff_and_newer_version_not_cleared(self):
        self.store.configure(1,mode='active')
        self.store.award(1,10,'text','first',100)
        self.store.award(1,11,'text','other',100)
        self.assertEqual(self.store.pending_roles(1,1,now=100),[(10,1,0)])
        self.store.defer_repair(1,10,100)
        self.assertEqual(Ledger(self.path).pending_roles(1,1,now=101),[(11,1,0)])
        self.store.award(1,10,'text','second',200)
        self.store.mark_repaired(1,10,1)
        self.assertIn((10,2,0),self.store.pending_roles(1,now=300))
        self.store.mark_repaired(1,10,2)
        self.assertNotIn(10,[r[0] for r in self.store.pending_roles(1,now=300)])

    def test_personal_rank_and_paginated_total_board_have_stable_ties(self):
        for uid in range(10,22):self.store.award(1,uid,'text',f'm{uid}',100)
        self.assertEqual(self.store.rank_position(1,10),1)
        self.assertEqual(self.store.rank_position(1,21),12)
        self.assertEqual(self.store.leaderboard(1,page=2),[(20,1),(21,1)])
        self.assertIsNone(self.store.rank_position(1,999))

    def test_battle_parser_handles_player_pet_death_and_ignores_unrelated(self):
        header={'author':{'name':'example'},'description':'<@10> (Member)'}
        result={'title':'Tharok the Vaultwarden attack!','fields':[{'name':'You','value':'HP: 10\nDamage Taken: 10'}]}
        self.assertEqual(battle_identity([header,result]),(10,'example'))
        self.assertEqual(battle_identity([{'description':"*example's pet attacking*"},result]),(None,'example'))
        result['fields']=[];result['description']='You tried attacking Tharok but they killed you.'
        self.assertEqual(battle_identity([header,result]),(10,'example'))
        self.assertIsNone(battle_identity([header,{'title':'Inventory','description':'Damage Taken'}]))
        self.assertIsNone(battle_identity([dict(header,description='<@10> <@11>'),result]))

    def test_real_game_card_projections_with_player_identity_redacted(self):
        # Captured via OFF diagnostics on 2026-11-07; account identity replaced.
        normal=[{'title':'player','description':'<@10> (👑 Member)\n⬆️ **Level:** 100\n\n🔶 **Experience:** 999 / 999'},
            {'title':'Tharok the Vaultwarden attack!','fields':[
                {'name':'You','value':'\n**❤️ HP:** 10,168 / 19,488\n**🗡️ Damage Taken:** 1,966\n\n','inline':False},
                {'name':'Tharok the Vaultwarden','value':'\n**❤️ HP:** 4,850,898 / 6,425,000\n**🗡️ Damage Taken:** 139,773','inline':False}]}]
        pet=[{'title':'Emerald Whelp 🐾','description':"*player's pet attacking*\n⬆️ **Level:** 10\n\nEmerald Whelp (* Epic*)"},
            {'title':'Tharok the Vaultwarden attack!','description':'**You casted 🐾 Emerald Whelp Attack**!\n',
             'fields':[{'name':'Tharok the Vaultwarden','value':'\n**❤️ HP:** 4,388,298 / 6,425,000\n**🗡️ Damage Taken:** 462,600','inline':False}]}]
        self.assertEqual(battle_identity(normal),(10,'player'))
        self.assertEqual(battle_identity(pet),(None,'player'))
        pet[0]['description']='<@11>\n'+pet[0]['description']
        self.assertNotEqual(battle_identity(pet),(None,'player'))


class CogTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_response_identity_rejects_incoming_webhook_spoofs(self):
        from cogs.community_levels import original_bot_message
        msg=types.SimpleNamespace(author=types.SimpleNamespace(bot=True,id=20),webhook_id=20,application_id=20)
        self.assertTrue(original_bot_message(msg))
        for app,webhook,author in [(None,20,20),(20,21,20),(21,21,20),(20,20,21)]:
            msg.application_id, msg.webhook_id, msg.author.id=app,webhook,author
            self.assertFalse(original_bot_message(msg))
        msg.webhook_id=None
        self.assertTrue(original_bot_message(msg))
        msg.author.bot=False
        self.assertFalse(original_bot_message(msg))

    async def test_ready_restores_only_live_same_guild_threads_and_continues_after_failure(self):
        active=MagicMock(spec=discord.Thread)
        active.guild=types.SimpleNamespace(id=1)
        active.archived=False
        active.join=AsyncMock()
        archived=MagicMock(spec=discord.Thread)
        archived.guild=types.SimpleNamespace(id=1)
        archived.archived=True
        archived.join=AsyncMock()
        foreign=MagicMock(spec=discord.Thread)
        foreign.guild=types.SimpleNamespace(id=2)
        foreign.archived=False
        foreign.join=AsyncMock()
        self.cog.cfg['sources']=[{'bot':20,'channel':i} for i in (30,31,32,33)]
        self.cog.bot.get_channel=lambda cid:{30:archived,32:foreign,33:active}.get(cid)
        self.cog.bot.fetch_channel=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404,reason='missing'),'missing'))
        await self.cog.on_ready()
        active.join.assert_awaited_once()
        archived.join.assert_not_awaited()
        foreign.join.assert_not_awaited()
        self.assertTrue(self.cog.gateway_confirmed)

    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cog=CommunityLevels(MagicMock())
        self.cog.ledger=Ledger(Path(self.tmp.name)/'db')
        self.cog.cfg=self.cog.ledger.configure(1,mode='preview',sources=[{'bot':20,'channel':30}])
        self.guild=types.SimpleNamespace(id=1)
        self.member=types.SimpleNamespace(id=10,name='example',bot=False,roles=[],guild=self.guild,premium_since=None)
        self.guild.get_member=lambda uid:self.member if uid==10 else None
        self.channel=types.SimpleNamespace(id=30,parent_id=None,category_id=None)
        self.config_patch=patch('config.GUILD_ID',1);self.config_patch.start()

    async def asyncTearDown(self):
        self.config_patch.stop(); self.tmp.cleanup()

    async def test_untrusted_bot_cannot_award_and_preview_never_changes_roles(self):
        embeds=[discord.Embed.from_dict({'author':{'name':'example'},'description':'<@10>'}),
                discord.Embed(title='Enemy attack!',description='Damage Taken: 10')]
        msg=types.SimpleNamespace(author=types.SimpleNamespace(bot=True,id=99),webhook_id=None,
                                  channel=self.channel,guild=self.guild,embeds=embeds,id=123,created_at=types.SimpleNamespace(timestamp=lambda:100))
        self.cog.apply_rewards=AsyncMock()
        await self.cog.observe_battle(msg)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],0)
        msg.author.id=20
        await self.cog.observe_battle(msg)
        self.assertEqual(self.cog.ledger.profile(1,10)['activity'],1)
        self.cog.apply_rewards.assert_not_awaited()
        msg.webhook_id=20;msg.id=124
        await self.cog.observe_battle(msg)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],1)

    async def test_excluded_parent_and_role_and_voice_bot_deaf_filters(self):
        cfg=dict(self.cog.cfg,excluded_channels=[40])
        self.channel.parent_id=40
        self.assertFalse(eligible(self.member,self.channel,cfg))
        self.channel.parent_id=None
        self.member.voice=types.SimpleNamespace(self_deaf=False,deaf=False,afk=False,suppress=False)
        self.channel.members=[self.member,types.SimpleNamespace(bot=True,roles=[])]
        self.assertEqual(voice_members(self.channel,self.cog.cfg),[self.member])
        self.member.voice.self_deaf=True
        self.assertEqual(voice_members(self.channel,self.cog.cfg),[])

    async def test_failed_and_unknown_pet_identity_does_not_award(self):
        self.cog.credit=AsyncMock()
        msg=types.SimpleNamespace(author=types.SimpleNamespace(bot=True,id=20),webhook_id=None,
            channel=self.channel,guild=self.guild,id=123,
            embeds=[discord.Embed(description="*stranger's pet attacking*"),discord.Embed(title='Enemy attack!',description='Damage Taken: 1')])
        await self.cog.observe_battle(msg)
        self.cog.credit.assert_not_awaited()

    async def test_role_adjustment_below_first_reward_removes_only_configured_roles(self):
        role=MagicMock();role.id=99
        other=MagicMock();other.id=100
        self.cog.cfg['mode']='active'
        member=types.SimpleNamespace(id=10,roles=[role,other],guild=MagicMock(),
                                     add_roles=AsyncMock(),remove_roles=AsyncMock())
        member.guild.id=1
        member.guild.get_role.return_value=role
        member.guild.get_channel.return_value=None
        self.cog.cfg['rewards']={'5':99}
        await self.cog.apply_rewards(member,(threshold(5),0))
        member.remove_roles.assert_awaited_once_with(role,reason='Con9sole 等級角色替換')
        member.add_roles.assert_not_awaited()

    async def test_inspector_never_exports_untrusted_or_unrecognized_message(self):
        self.cog.guard=AsyncMock(return_value=True)
        inter=types.SimpleNamespace(guild_id=1,user=types.SimpleNamespace(),followup=types.SimpleNamespace(send=AsyncMock()))
        self.channel.permissions_for=lambda _:types.SimpleNamespace(view_channel=True,read_message_history=True)
        message=types.SimpleNamespace(author=types.SimpleNamespace(bot=True,id=99),channel=self.channel,
            webhook_id=None,embeds=[discord.Embed(description='private content')])
        self.channel.fetch_message=AsyncMock(return_value=message)
        await self.cog.inspect.callback(self.cog,inter,self.channel,'123')
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)
        self.assertNotIn('private content',inter.followup.send.call_args.args[0])
        message.author.id=20
        inter.followup.send.reset_mock()
        await self.cog.inspect.callback(self.cog,inter,self.channel,'123')
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)
        self.assertNotIn('private content',inter.followup.send.call_args.args[0])

    async def test_raw_inspector_requires_admin_and_both_read_permissions(self):
        self.cog.guard=AsyncMock(return_value=True)
        inter=types.SimpleNamespace(guild_id=1,user=types.SimpleNamespace(guild_permissions=types.SimpleNamespace(administrator=False)),followup=types.SimpleNamespace(send=AsyncMock()))
        self.channel.permissions_for=lambda _:types.SimpleNamespace(view_channel=True,read_message_history=True)
        message=types.SimpleNamespace(author=types.SimpleNamespace(bot=True,id=20),channel=self.channel,
            webhook_id=None,embeds=[discord.Embed(description='private content')])
        self.channel.fetch_message=AsyncMock(return_value=message)
        await self.cog.inspect.callback(self.cog,inter,self.channel,'123',raw_private=True)
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)
        self.channel.fetch_message.reset_mock()
        self.channel.permissions_for=lambda _:types.SimpleNamespace(view_channel=False,read_message_history=True)
        await self.cog.inspect.callback(self.cog,inter,self.channel,'123',raw_private=True)
        self.channel.fetch_message.assert_not_awaited()

    async def test_message_link_resolves_uncached_thread_and_checks_scope(self):
        thread=MagicMock(spec=discord.Thread)
        thread.guild=types.SimpleNamespace(id=1)
        thread.permissions_for.return_value=types.SimpleNamespace(view_channel=True,read_message_history=True)
        thread.fetch_message=AsyncMock(return_value='card')
        self.cog.bot.get_channel.return_value=None
        self.cog.bot.fetch_channel=AsyncMock(return_value=thread)
        inter=types.SimpleNamespace(user=self.member)
        actual,message=await self.cog.resolve_card_link(inter,'https://discord.com/channels/1/30/123')
        self.assertIs(actual,thread);self.assertEqual(message,'card')
        self.cog.bot.fetch_channel.assert_awaited_once_with(30)
        for link in ('https://evil.com/channels/1/30/123','https://discord.com/channels/2/30/123'):
            with self.assertRaises(ValueError):await self.cog.resolve_card_link(inter,link)
        thread.permissions_for.return_value.view_channel=False
        thread.fetch_message.reset_mock()
        with self.assertRaises(ValueError):await self.cog.resolve_card_link(inter,'https://discord.com/channels/1/30/123')
        thread.fetch_message.assert_not_awaited()

    async def test_wrong_guild_never_credits(self):
        self.member.guild=types.SimpleNamespace(id=2)
        await self.cog.credit(self.member,self.channel,'activity','i1')
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],0)


if __name__=='__main__': unittest.main()
