"""Independent auditor regressions: outcomes required before replacement can ship.

No Discord login or production data. These intentionally target failures found
outside the original feature's self-tests.
"""
import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import cogs.community_levels as levels
from features.community_levels import Ledger, threshold


class Role:
    def __init__(self, role_id, position, **permissions):
        self.id = role_id
        self.position = position
        self.permissions = discord.Permissions(**permissions)
        self.managed = False

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= other.position


def state(channel, **changes):
    return types.SimpleNamespace(channel=channel, self_mute=False, mute=False,
        self_deaf=False, deaf=False, afk=False, suppress=False,
        self_stream=False, self_video=False, **changes)


class LevelAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.guild_patch = patch.object(levels.config, 'GUILD_ID', 1)
        self.guild_patch.start()
        self.bot = MagicMock()
        self.bot.is_ready.return_value = True
        self.cog = levels.CommunityLevels(self.bot)
        self.cog.gateway_confirmed = True
        self.cog.ledger = Ledger(Path(self.tmp.name) / 'audit.sqlite3')
        self.low, self.high = Role(50, 5), Role(150, 15)
        self.cog.cfg = self.cog.ledger.configure(1, mode='active',
            rewards={'5': 50, '15': 150})
        self.guild = types.SimpleNamespace(id=1, afk_channel=None,
            voice_channels=[], stage_channels=[],
            get_role=lambda rid: {50: self.low, 150: self.high}.get(rid),
            get_channel=lambda cid: None)
        self.member = self.make_member(10)
        self.member.roles = []
        self.member.add_roles = AsyncMock(side_effect=self.add_roles)
        self.member.remove_roles = AsyncMock(side_effect=self.remove_roles)
        self.bot.get_guild.return_value = self.guild

    async def asyncTearDown(self):
        self.guild_patch.stop()
        self.tmp.cleanup()

    def make_member(self, uid):
        return types.SimpleNamespace(id=uid, guild=self.guild, bot=False,
            roles=[], voice=None, premium_since=None, mention=f'<@{uid}>', display_name='player')

    async def add_roles(self, *roles, **kwargs):
        for role in roles:
            if role not in self.member.roles:
                self.member.roles.append(role)

    async def remove_roles(self, *roles, **kwargs):
        self.member.roles = [r for r in self.member.roles if r not in roles]

    def total(self, value):
        existing = self.cog.ledger.profile(1, 10)['total']
        self.cog.ledger.adjust(1, 10, 99, value-existing, 'audit fixture', 100)

    async def test_late_old_reconciliation_uses_latest_durable_xp(self):
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member, (0, threshold(15)))
        # An older delayed event cannot undo a newer level.
        await self.cog.apply_rewards(self.member, (0, threshold(5)))
        self.assertEqual([r.id for r in self.member.roles], [150])

    async def test_simultaneous_reconciliation_cannot_finish_out_of_order(self):
        self.total(threshold(5))
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_add(*roles, **kwargs):
            if self.low in roles:
                started.set()
                await release.wait()
            await self.add_roles(*roles, **kwargs)

        self.member.add_roles.side_effect = delayed_add
        older = asyncio.create_task(self.cog.apply_rewards(self.member, (0, threshold(5))))
        await asyncio.wait_for(started.wait(), 1)
        self.total(threshold(15))
        newer = asyncio.create_task(self.cog.apply_rewards(self.member, (0, threshold(15))))
        try:
            await asyncio.sleep(0.02)
            self.assertFalse(newer.done(), 'newer side effects bypassed in-flight reconciliation')
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(older, newer), 1)
        self.assertEqual([r.id for r in self.member.roles], [150])

    async def test_pause_waits_for_inflight_effects_then_prevents_more(self):
        self.total(threshold(5))
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_add(*roles, **kwargs):
            started.set()
            await release.wait()
            await self.add_roles(*roles, **kwargs)

        self.member.add_roles.side_effect = delayed_add
        pending = asyncio.create_task(self.cog.apply_rewards(self.member, (0, threshold(5))))
        await asyncio.wait_for(started.wait(), 1)
        pause = asyncio.create_task(self.cog.configure(mode='off'))
        try:
            await asyncio.sleep(0.02)
            self.assertFalse(pause.done(), 'pause completed while role effects were still running')
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(pending, pause), 1)
        self.assertEqual(self.cog.cfg['mode'], 'off')
        self.member.add_roles.reset_mock()
        self.member.remove_roles.reset_mock()
        await self.cog.apply_rewards(self.member, (0, threshold(15)))
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()

    def voice_room(self, count=2):
        channel = types.SimpleNamespace(id=30, parent_id=None, category_id=None, members=[], guild=self.guild)
        channel.members = [self.make_member(10+i) for i in range(count)]
        for member in channel.members:
            member.voice = state(channel)
        self.guild.voice_channels = [channel]
        return channel

    async def test_self_mute_and_stream_events_preserve_everyones_clock(self):
        room = self.voice_room()
        self.cog.voice_clock = {(30, 10): 100, (30, 11): 100}
        member = room.members[0]
        before, after = state(room), state(room)
        after.self_mute = True
        after.self_stream = True
        member.voice = after
        with patch.object(levels.time, 'monotonic', return_value=250):
            await self.cog.on_voice_state_update(member, before, after)
        self.assertEqual(self.cog.voice_clock, {(30, 10): 100, (30, 11): 100})

    async def test_third_member_leaving_preserves_two_existing_peers(self):
        room = self.voice_room(3)
        self.cog.voice_clock = {(30, 10): 100, (30, 11): 100, (30, 12): 150}
        leaving = room.members.pop()
        leaving.voice = None
        with patch.object(levels.time, 'monotonic', return_value=250):
            await self.cog.on_voice_state_update(leaving, state(room), state(None))
        self.assertEqual(self.cog.voice_clock, {(30, 10): 100, (30, 11): 100})

    async def test_deafening_below_two_invalidates_elapsed_time(self):
        room = self.voice_room()
        self.cog.voice_clock = {(30, 10): 100, (30, 11): 100}
        member = room.members[0]
        before, after = state(room), state(room)
        after.self_deaf = True
        member.voice = after
        with patch.object(levels.time, 'monotonic', return_value=250):
            await self.cog.on_voice_state_update(member, before, after)
        self.assertEqual(self.cog.voice_clock, {})

    async def test_disconnected_gateway_never_awards_cached_voice_attendance(self):
        self.voice_room()
        self.cog.gateway_confirmed = True
        self.cog.voice_clock = {(30, 10): 0, (30, 11): 0}
        self.cog.credit = AsyncMock()
        await self.cog.on_disconnect()
        # Even a stale is_ready result must not bypass explicit disconnect fencing.
        self.bot.is_ready.return_value = True
        with patch.object(levels.time, 'monotonic', return_value=600):
            await self.cog.voice_tick.coro(self.cog)
        self.cog.credit.assert_not_awaited()
        self.assertEqual(self.cog.voice_clock, {})
        await self.cog.on_resumed()
        self.assertTrue(self.cog.gateway_confirmed)
        with patch.object(levels.time, 'monotonic', return_value=700):
            await self.cog.voice_tick.coro(self.cog)
        self.cog.credit.assert_not_awaited()
        self.assertEqual(self.cog.voice_clock, {(30, 10): 700, (30, 11): 700})

    async def test_not_ready_gateway_never_awards(self):
        self.voice_room()
        self.cog.gateway_confirmed = True
        self.cog.voice_clock = {(30, 10): 0, (30, 11): 0}
        self.cog.credit = AsyncMock()
        self.bot.is_ready.return_value = False
        with patch.object(levels.time, 'monotonic', return_value=600):
            await self.cog.voice_tick.coro(self.cog)
        self.cog.credit.assert_not_awaited()
        self.assertEqual(self.cog.voice_clock, {})

    def announcement_channel(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        self.guild.get_channel = lambda cid: channel
        self.cog.cfg['announcement_channel'] = 999
        return channel

    async def test_queued_old_events_do_not_repeat_latest_milestone_notice(self):
        channel = self.announcement_channel()
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        await self.cog.apply_rewards(self.member, (threshold(4), threshold(5)))
        self.assertEqual(channel.send.await_count, 1)
        # The suppression survives a process/ledger restart.
        self.cog.ledger = Ledger(self.cog.ledger.path)
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        self.assertEqual(channel.send.await_count, 1)
        self.assertEqual(self.cog.ledger.notice_level(1, 10, 0), 15)

    async def test_notice_uses_embed_box_and_preserves_explicit_ping_setting(self):
        channel = self.announcement_channel()
        self.cog.cfg['level_templates'] = {}
        self.cog.cfg['announcement_template'] = '恭喜 {user.ping} 升級！依家你係 等級{level}'
        self.cog.cfg['announcement_ping'] = False
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        sent=channel.send.call_args.kwargs
        self.assertIsNone(sent['content'])
        self.assertIsInstance(sent['embed'],discord.Embed)
        self.assertIn('等級15',sent['embed'].description)
        self.assertEqual(sent['allowed_mentions'].to_dict(),{'parse':[]})

    async def test_missing_embed_permission_leaves_notice_pending(self):
        channel=self.announcement_channel()
        self.guild.me=object()
        channel.permissions_for.return_value=discord.Permissions(view_channel=True,send_messages=True,embed_links=False)
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member,(threshold(14),threshold(15)))
        channel.send.assert_not_awaited()
        self.assertEqual(self.cog.ledger.notice_level(1,10,0),14)
        channel.permissions_for.return_value=discord.Permissions(view_channel=True,send_messages=True,embed_links=True)
        await self.cog.apply_rewards(self.member,(threshold(15),threshold(15)))
        channel.send.assert_awaited_once()

    async def test_nickname_mention_template_keeps_only_target_notification(self):
        channel=self.announcement_channel()
        self.cog.cfg.update(level_templates={},announcement_template='恭喜 <@!10>！Lv.{level}',announcement_ping=True)
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member,(threshold(14),threshold(15)))
        sent=channel.send.call_args.kwargs
        self.assertEqual(sent['content'],self.member.mention)
        self.assertEqual(sent['allowed_mentions'].to_dict(),{'users':[10],'parse':[]})

    async def test_ordinary_level_up_is_plain_text_and_never_tags(self):
        channel=self.announcement_channel()
        self.cog.cfg.update(level_templates={},announcement_template='恭喜 {user.ping} Lv.{level}',announcement_ping=True)
        self.total(threshold(16))
        self.cog.ledger.mark_notice(1,10,15)
        await self.cog.apply_rewards(self.member,(threshold(15),threshold(16)))
        sent=channel.send.call_args.kwargs
        self.assertNotIn('embed',sent)
        self.assertNotIn('<@10>',sent['content'])
        self.assertEqual(sent['allowed_mentions'].to_dict(),{'parse':[]})
        self.assertIn('Lv.16',sent['content'])

    async def test_ordinary_notice_does_not_require_embed_links(self):
        channel=self.announcement_channel()
        self.guild.me=object()
        channel.permissions_for.return_value=discord.Permissions(view_channel=True,send_messages=True,embed_links=False)
        self.total(threshold(16))
        self.cog.ledger.mark_notice(1,10,15)
        await self.cog.apply_rewards(self.member,(threshold(15),threshold(16)))
        channel.send.assert_awaited_once()
        self.assertNotIn('embed',channel.send.call_args.kwargs)
        self.assertEqual(self.cog.ledger.notice_level(1,10,0),16)

    async def test_major_milestone_tags_once_even_with_name_only_template(self):
        channel=self.announcement_channel()
        self.cog.cfg.update(level_templates={'15':'{user} 成為活躍會員'},announcement_ping=True)
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member,(threshold(14),threshold(15)))
        await self.cog.apply_rewards(self.member,(threshold(14),threshold(15)))
        self.assertEqual(channel.send.await_count,1)
        self.assertEqual(channel.send.call_args.kwargs['content'],self.member.mention)
        self.assertEqual(channel.send.call_args.kwargs['allowed_mentions'].to_dict(),{'users':[10],'parse':[]})

    async def test_failed_notice_is_retried_on_later_reconciliation(self):
        channel = self.announcement_channel()
        channel.send.side_effect = [
            discord.HTTPException(types.SimpleNamespace(status=500, reason='Unavailable'), 'retry'),
            None,
        ]
        self.total(threshold(15))
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        self.assertEqual(self.cog.ledger.notice_level(1, 10, 0), 14)
        # New event itself does not cross a milestone; pending notice must still retry.
        await self.cog.apply_rewards(self.member, (threshold(15), threshold(15)))
        self.assertEqual(channel.send.await_count, 2)
        self.assertEqual(self.cog.ledger.notice_level(1, 10, 0), 15)
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        self.assertEqual(channel.send.await_count, 2)

    async def test_failed_role_assignment_does_not_announce_membership_as_granted(self):
        channel = self.announcement_channel()
        self.total(threshold(15))
        self.member.add_roles.side_effect = discord.HTTPException(
            types.SimpleNamespace(status=403, reason='Forbidden'), 'permissions')
        await self.cog.apply_rewards(self.member, (threshold(14), threshold(15)))
        channel.send.assert_not_awaited()
        # Once permissions recover, retry the role before announcing membership.
        self.member.add_roles.side_effect = self.add_roles
        await self.cog.apply_rewards(self.member, (threshold(15), threshold(15)))
        self.assertEqual([r.id for r in self.member.roles], [150])
        channel.send.assert_awaited_once()

    async def test_confirmation_flags_cannot_bypass_replacement_gate(self):
        self.cog.cfg['mode'] = 'preview'
        self.cog.guard = AsyncMock(return_value=True)
        self.cog.configure = AsyncMock()
        inter = types.SimpleNamespace(followup=types.SimpleNamespace(send=AsyncMock()))
        with patch.object(levels,'REPLACEMENT_READY',False):
            await self.cog.activate.callback(self.cog, inter,
                amari_rewards_disabled=True, baseline_verified=True,
                announcement=types.SimpleNamespace(id=999), ping=True)
        self.cog.configure.assert_not_awaited()
        self.assertEqual(self.cog.cfg['mode'], 'preview')
        self.assertIn('未通過驗收', inter.followup.send.call_args.args[0])

    def test_curve_matches_independent_official_table_examples(self):
        # Values transcribed from current Amari XP Info during the audit.
        examples = {0: 0, 1: 35, 2: 55, 3: 115, 5: 355,
                    15: 3955, 50: 48055, 75: 109555, 100: 196055}
        for level, xp in examples.items():
            with self.subTest(level=level):
                self.assertEqual(threshold(level), xp)

    def test_moderation_roles_cannot_be_automatic_level_rewards(self):
        me = types.SimpleNamespace(top_role=Role(999, 100))
        self.assertTrue(levels.reward_role_safe(Role(50, 5), me))
        for permission in ('administrator', 'manage_guild', 'manage_roles',
                           'kick_members', 'ban_members', 'moderate_members',
                           'manage_channels', 'manage_webhooks'):
            with self.subTest(permission=permission):
                self.assertFalse(levels.reward_role_safe(Role(50, 5, **{permission: True}), me))
        self.assertFalse(levels.reward_role_safe(Role(999, 100), me))


if __name__ == '__main__':
    unittest.main()
