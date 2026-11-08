"""Independent membership-generation races, using a real isolated XP ledger."""
import asyncio
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cogs.community_levels as levels
from features.community_levels import Ledger, threshold
from core.sqlite_storage import connect_sqlite


class MembershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(levels.config,'GUILD_ID',1);self.patch.start()
        self.bot=MagicMock();self.cog=levels.CommunityLevels(self.bot)
        self.cog.ledger=Ledger(Path(self.tmp.name)/'levels.db')
        self.cog.cfg=self.cog.ledger.configure(1,mode='active')
        self.cog.apply_rewards=AsyncMock()
        self.present={}
        self.guild=types.SimpleNamespace(id=1,get_member=self.present.get,members=[])
        self.bot.get_guild.return_value=self.guild
        self.channel=types.SimpleNamespace(id=30,parent_id=None,category_id=None)
        self.old=self.member(100)
        self.present[10]=self.old

    async def asyncTearDown(self):self.patch.stop();self.tmp.cleanup()

    def member(self,stamp):
        return types.SimpleNamespace(id=10,guild=self.guild,bot=False,roles=[],premium_since=None,
            joined_at=datetime.fromtimestamp(stamp,timezone.utc))

    async def old_score(self):
        await self.cog.credit(self.old,self.channel,'text','old-message',200)
        self.cog.ledger.adjust(1,10,99,499,'old balance',201)

    async def test_first_membership_preserves_existing_balance_and_does_not_seed(self):
        self.cog.ledger.adjust(1,10,99,700,'imported first balance',150)
        await self.cog.on_member_join(self.old)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],700)
        fresh=self.member(100);fresh.id=11;self.present[11]=fresh
        await self.cog.on_member_join(fresh)
        self.assertEqual(self.cog.ledger.profile(1,11)['total'],0)

    async def test_return_seeds_exact_floor_once_without_old_xp_or_weekly_bonus(self):
        await self.old_score();self.present.clear()
        await self.cog.on_member_remove(self.old)
        returning=self.member(500);self.present[10]=returning
        await self.cog.on_member_join(returning)
        await self.cog.on_member_join(returning)
        self.assertEqual(self.cog.ledger.profile(1,10),dict(total=355,text=0,activity=0,voice=0,imported=355))
        self.assertEqual(self.cog.ledger.leaderboard(1,'1970-W01'),[])
        self.assertEqual(self.cog.ledger.notice_level(1,10,0),5)

    async def test_delayed_old_departure_cannot_clear_rejoined_member_award(self):
        await self.old_score()
        await self.cog.role_lock.acquire()
        self.present.clear()
        leaving=asyncio.create_task(self.cog.on_member_remove(self.old))
        await asyncio.sleep(0)
        returning=self.member(500);self.present[10]=returning
        await self.cog.credit(returning,self.channel,'text','new-message',600)
        self.cog.role_lock.release();await leaving
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],356)
        self.assertEqual(self.cog.ledger.event_proof(1,'new-message')[1],1)
        await self.cog.on_member_remove(self.old)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],356)

    async def test_old_queued_action_rejected_after_membership_changes(self):
        await self.old_score()
        await self.cog.lock.acquire()
        queued=asyncio.create_task(self.cog.credit(self.old,self.channel,'text','stale-action',700))
        await asyncio.sleep(0)
        returning=self.member(500);self.present[10]=returning
        self.cog.lock.release();await queued
        await self.cog.on_member_join(returning)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],threshold(5))
        self.assertIsNone(self.cog.ledger.event_proof(1,'stale-action'))

    async def test_exclusion_changed_while_awaiting_lock_is_respected(self):
        await self.cog.lock.acquire()
        queued=asyncio.create_task(self.cog.credit(self.old,self.channel,'text','excluded-action',700))
        await asyncio.sleep(0)
        self.cog.cfg=self.cog.ledger.configure(1,excluded_channels=[30])
        self.cog.lock.release();await queued
        self.assertIsNone(self.cog.ledger.event_proof(1,'excluded-action'))

    async def test_restart_detects_new_generation_and_cannot_seed_twice(self):
        await self.old_score()
        self.cog.ledger=Ledger(self.cog.ledger.path)
        returning=self.member(500);self.present[10]=returning
        await self.cog.on_member_join(returning)
        self.cog.ledger=Ledger(self.cog.ledger.path)
        await self.cog.on_member_join(returning)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],355)

    async def test_deleted_lifetime_events_are_not_retained_in_inventory(self):
        await self.old_score();self.present.clear()
        await self.cog.on_member_remove(self.old)
        self.assertEqual(self.cog.ledger.engagement_inventory(1,0,1000)['retained'],{})
        returning=self.member(500);self.present[10]=returning
        await self.cog.credit(returning,self.channel,'text','current-message',600)
        self.assertEqual(set(self.cog.ledger.engagement_inventory(1,0,1000)['retained']),{'current-message'})

    async def test_old_timestamp_card_cannot_award_new_membership(self):
        await self.old_score()
        returning=self.member(500);self.present[10]=returning
        await self.cog.credit(returning,self.channel,'activity','old-card',400)
        self.assertEqual(self.cog.ledger.profile(1,10)['total'],355)
        self.assertIsNone(self.cog.ledger.event_proof(1,'old-card'))

    async def test_role_repair_budget_preserves_durable_jobs_and_voice_loop(self):
        await self.old_score()
        self.guild.voice_channels=[];self.guild.stage_channels=[]
        self.cog.gateway_confirmed=True;self.bot.is_ready.return_value=True
        self.cog.retry_role_drill=AsyncMock()
        cancelled=asyncio.Event()
        async def stalled():
            try:await asyncio.Future()
            finally:cancelled.set()
        self.cog.repair_pending=stalled
        timeout=asyncio.timeout
        with patch.object(levels.asyncio,'timeout',side_effect=lambda _:timeout(.001)):
            await levels.CommunityLevels.voice_tick.coro(self.cog)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(self.cog.ledger.pending_roles(1))

    async def test_source_update_immediately_reconciles_subscriptions(self):
        self.cog.guard=AsyncMock(return_value=True)
        self.cog.reconcile_sources=AsyncMock()
        inter=types.SimpleNamespace(guild_id=1,followup=types.SimpleNamespace(send=AsyncMock()))
        source_bot=types.SimpleNamespace(id=20,bot=True)
        await levels.CommunityLevels.source.callback(self.cog,inter,source_bot,self.channel)
        self.assertIn({'bot':20,'channel':30},self.cog.ledger.settings(1)['sources'])
        self.cog.reconcile_sources.assert_awaited_once()
