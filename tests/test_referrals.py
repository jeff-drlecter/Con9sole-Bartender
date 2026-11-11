import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from features.community_levels import Ledger, calendar
from features.referrals import Referrals, INVITE_XP, match_batch, month_start
from core.sqlite_storage import connect_sqlite


class ReferralTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger=Ledger(Path(self.temp.name)/'xp.sqlite3')
        self.ledger.configure(1,mode='active')
        self.store=Referrals(self.ledger)
        self.store.save_link(1,10,'personal')

    def test_batch_only_unambiguous_deltas(self):
        self.assertEqual(match_batch({'a':1},{'a':3},2),'a')
        for before,after,count in [({'a':1},{'a':2,'b':1},2),({'a':1},{'a':3},1),({'a':1},{},1),({'a':1},{'a':1},1)]:
            self.assertIsNone(match_batch(before,after,count))

    def test_atomic_reward_is_durable_and_not_repeated_on_rejoin(self):
        self.store.joined(1,20,100,'personal')
        self.assertEqual(self.store.reward(1,20,100,200),(10,(0,INVITE_XP)))
        self.assertIsNone(Referrals(self.ledger).reward(1,20,100,201))
        self.store.departed(1,20,100,210)
        self.store.joined(1,20,300,'personal')
        self.assertIsNone(self.store.reward(1,20,300,301))
        self.assertEqual(self.store.board(1),[(10,1,INVITE_XP)])
        self.assertEqual(self.ledger.profile(1,10)['total'],INVITE_XP)
        self.assertEqual(self.ledger.leaderboard(1,calendar(200)[1]),[(10,INVITE_XP)])
        self.assertEqual(self.store.sources(1),[('personal',2,1,1)])

    def test_pause_retry_self_unknown_existing_departed(self):
        self.store.seed(1,[30])
        for user,code in [(30,'personal'),(10,'personal'),(40,None)]:
            self.store.joined(1,user,100,code)
            self.assertIsNone(self.store.reward(1,user,100,200))
        self.store.joined(1,50,100,'personal')
        self.ledger.configure(1,mode='off')
        self.assertIsNone(self.store.reward(1,50,100,200))
        self.ledger.configure(1,mode='active')
        self.assertIsNotNone(self.store.reward(1,50,100,201))
        self.store.joined(1,60,100,'personal')
        self.store.departed(1,60,100,150)
        self.assertIsNone(self.store.reward(1,60,100,200))

    def test_old_level_members_cannot_earn_referral_credit(self):
        self.ledger.ensure_membership(1,90,10,10)
        self.ledger.configure(1,member_lifecycles={'90':{'joined':10,'departed':True}})
        self.store.seed(1,[])
        self.store.joined(1,90,100,'personal')
        self.assertIsNone(self.store.reward(1,90,100,200))

    def test_concurrent_reward_attempts_commit_once(self):
        from concurrent.futures import ThreadPoolExecutor
        self.store.joined(1,20,100,'personal')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.store.reward(1,20,100,200),range(8)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.ledger.profile(1,10)['total'],INVITE_XP)
        self.assertEqual(self.store.board(1),[(10,1,INVITE_XP)])

    def test_platform_list_reads_live_codes_and_excludes_personal_links(self):
        from features.referrals import source_invites
        invites=[SimpleNamespace(code='live-platform',channel=SimpleNamespace(name='threads-invitation')),
                 SimpleNamespace(code='personal',channel=SimpleNamespace(name='rules')),
                 SimpleNamespace(code='unrelated',channel=SimpleNamespace(name='chat'))]
        self.assertEqual([(name,i.code) for name,i in source_invites(invites,{'personal'})],
                         [('Threads','live-platform')])

    def test_month_uses_hong_kong(self):
        from datetime import datetime,timezone
        now=datetime(2026,11,30,16,tzinfo=timezone.utc).timestamp()
        self.assertEqual(month_start(now),now)


class ReferralUI(unittest.IsolatedAsyncioTestCase):
    async def test_menu_layout_and_persistent_ids(self):
        from features.menu_views import QuickBarView,HomeMenuView,SectionMenuView,AdminToolView
        from cogs.invites import InviteView
        for view in [QuickBarView(MagicMock()),HomeMenuView(MagicMock()),SectionMenuView(MagicMock(),'rankings')]:
            invite=next(b for b in view.children if b.item.id=='invite')
            self.assertEqual(invite.row,3 if isinstance(view,QuickBarView) else 0)
            self.assertEqual(invite.label,'邀請朋友')
            self.assertTrue(view.is_persistent())
            view.stop()
        view=InviteView(MagicMock())
        self.assertTrue(view.is_persistent());view.stop()

    async def test_old_invite_entry_routes_to_personal_link_without_format_step(self):
        from features.invite_tools import create_invite_link_from_button
        cog=SimpleNamespace(menu_entry=AsyncMock())
        inter=MagicMock();inter.client.get_cog.return_value=cog
        await create_invite_link_from_button(inter,can_use_admin_func=lambda _:False)
        cog.menu_entry.assert_awaited_once_with(inter)

    async def test_platform_entry_rechecks_authority(self):
        from cogs.invites import Invites
        cog=Invites(MagicMock());inter=MagicMock();inter.response.send_message=AsyncMock()
        with patch('cogs.invites.is_server_admin',return_value=False):
            await cog.platform_entry(inter)
        self.assertNotIn('view',inter.response.send_message.call_args.kwargs)

    async def test_pending_or_unverified_join_does_not_award(self):
        from cogs.invites import Invites
        cog=Invites(MagicMock());cog.store=MagicMock()
        member=SimpleNamespace(bot=False,pending=True)
        await cog.try_reward(member)
        cog.store.reward.assert_not_called()

    async def test_concurrent_clicks_reuse_one_invite(self):
        from cogs.invites import Invites
        import config
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'xp');store=Referrals(ledger)
            cog=Invites(MagicMock());cog.store=store
            channel=MagicMock();channel.permissions_for.return_value.view_channel=True
            created=[]
            async def create(**kwargs):
                invite=SimpleNamespace(code='new-code',uses=0);created.append(invite);return invite
            channel.create_invite=AsyncMock(side_effect=create)
            guild=MagicMock();guild.get_channel.return_value=channel
            guild.invites=AsyncMock(side_effect=lambda:list(created))
            def interaction():
                return SimpleNamespace(guild_id=config.GUILD_ID,guild=guild,user=SimpleNamespace(id=10,bot=False),
                    response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
            await asyncio.gather(cog.menu_entry(interaction()),cog.menu_entry(interaction()))
            channel.create_invite.assert_awaited_once()
            self.assertEqual(store.link(config.GUILD_ID,10),'new-code')
            self.assertEqual(cog.snapshots[config.GUILD_ID]['new-code'],0)

    async def test_disconnect_between_queued_join_and_baseline_cannot_credit_old_batch(self):
        from cogs.invites import Invites
        import config
        cog=Invites(MagicMock());cog.store=MagicMock();cog.store.joined=MagicMock()
        guild=MagicMock();guild.id=config.GUILD_ID
        guild.invites=AsyncMock(return_value=[SimpleNamespace(code='other',uses=1)])
        member=SimpleNamespace(guild=guild,id=10,joined_at=SimpleNamespace(timestamp=lambda:100))
        cog.pending_joins=[(member,1)]
        cog.ready=True;cog.epoch=2;cog.snapshots={config.GUILD_ID:{'other':0}}
        cog.try_reward=AsyncMock()
        with patch('cogs.invites.asyncio.sleep',new=AsyncMock()):
            await cog.process_batch()
        self.assertIsNone(cog.store.joined.call_args.args[-1])

    async def test_platform_dropdown_callback_checks_authority_again(self):
        from cogs.invites import PlatformSelect
        select=PlatformSelect(MagicMock(),[('Test',SimpleNamespace(code='fake',uses=1))])
        inter=MagicMock();inter.response.send_message=AsyncMock()
        with patch('cogs.invites.is_server_admin',return_value=False):
            await select.callback(inter)
        inter.guild.invites.assert_not_called()
        self.assertTrue(inter.response.send_message.call_args.kwargs['ephemeral'])
