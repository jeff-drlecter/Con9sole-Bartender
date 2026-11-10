import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord
from features.maintenance import Store, differences, snapshot
from cogs.maintenance import Maintenance, private_destination, private_candidate, format_findings


def role(rid, mask=0, bot=None, name='role'):
    result = Mock(spec=discord.Role)
    result.id, result.permissions, result.name = rid, discord.Permissions(mask), name
    result.is_bot_managed.return_value = bot is not None
    result.tags = NS(bot_id=bot)
    return result


def channel(cid, **extra):
    return dict(id=str(cid), type=2, parent_id=None, permission_overwrites=[], **extra)


def observed():
    return snapshot([role(1)], [channel(10)], [], {9: [1]})


class SnapshotTests(unittest.TestCase):
    def test_order_cosmetic_and_tracked_temporary_only(self):
        r = [role(1, 1024), role(2, 2048)]
        rules = [dict(id='4', enabled=True, exempt_roles=['1', '2'], name='a')]
        a = snapshot(r, [channel(10), channel(11)], rules, {9: [1, 2]}, [11])
        rules[0].update(name='rename', exempt_roles=['2', '1'])
        b = snapshot(list(reversed(r)), [channel(11), channel(10)], rules, {9: [2, 1]}, [11])
        self.assertEqual(a, b)
        b['channels']['12'] = a['channels']['10']
        self.assertEqual(differences(a, b), {'channels': ['12']})

    def test_unknown_channel_and_bot_membership_are_monitored(self):
        a = snapshot([role(1)], [dict(id='20', type=20)], [], {9: [1]})
        b = snapshot([role(1)], [dict(id='20', type=20)], [], {9: [1, 2]})
        self.assertIn('20', a['channels'])
        self.assertEqual(differences(a, b), {'bots': ['9']})

    def test_alert_never_contains_raw_config(self):
        result = format_findings({'drift': {'automod': ['123']}})
        self.assertIn('123', result)
        self.assertNotIn('regex', result)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'maintenance.sqlite3'
        self.store = Store(self.path)

    def baseline(self):
        data = observed()
        token = self.store.preview(1, 7, data, 10, now=100)
        self.store.accept(1, 7, token, data, now=101)
        self.store.enable(1, True)
        return data

    def test_explicit_actor_expiry_and_unchanged_preview(self):
        with self.assertRaises(ValueError):
            self.store.enable(1, True)
        data = observed()
        token = self.store.preview(1, 7, data, 10, now=100)
        for actor, code, current, now in [(8, token, data, 101), (7, 'bad', data, 101),
                                        (7, token, data, 701), (7, token, {}, 101)]:
            with self.assertRaises(ValueError):
                self.store.accept(1, actor, code, current, now=now)
        self.assertIsNone(self.store.state(1)['baseline'])
        self.store.accept(1, 7, token, data, now=101)
        self.assertEqual(self.store.state(1)['channel'], 10)
        with self.assertRaises(ValueError):
            self.store.accept(1, 7, token, data, now=102)

    def test_versions_retained_and_sqlite_backup_restorable(self):
        self.baseline()
        data = observed(); data['roles']['2'] = '0'
        token = self.store.preview(1, 7, data, 10, now=200)
        self.store.accept(1, 7, token, data, now=201)
        with sqlite3.connect(self.path) as source, sqlite3.connect(Path(self.folder.name) / 'backup.db') as target:
            source.backup(target)
            self.assertEqual(target.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(target.execute('SELECT count(*) FROM baselines').fetchone()[0], 2)

    def test_two_background_observations_manual_never_triggers(self):
        self.baseline()
        finding = {'health': ['loop stopped']}
        self.assertIsNone(self.store.observe(1, finding, background=False))
        self.assertIsNone(self.store.observe(1, finding, background=True))
        fp = self.store.observe(1, finding, background=True)
        self.assertIsNotNone(fp)
        self.assertTrue(self.store.reserve(1, fp))
        self.assertFalse(Store(self.path).reserve(1, fp))
        self.assertIsNone(Store(self.path).observe(1, finding, background=True))
        self.assertEqual(Store(self.path).state(1)['receipts'], {'uncertain': 1})
        self.store.sent(1, fp, 99)
        self.assertEqual(self.store.state(1)['receipts'], {'sent': 1})
        self.store.observe(1, {}, background=True)
        self.assertIsNone(self.store.observe(1, finding, background=True))
        self.assertIsNone(self.store.observe(1, finding, background=True))

    def test_disable_and_accept_do_not_forget_uncertain_intent(self):
        self.baseline()
        self.store.reserve(1, 'a')
        self.store.enable(1, False)
        token = self.store.preview(1, 7, observed(), 10, now=200)
        self.store.accept(1, 7, token, observed(), now=201)
        self.assertEqual(self.store.state(1)['receipts'], {'uncertain': 1})
        self.assertFalse(self.store.state(1)['enabled'])


class PrivacyTests(unittest.TestCase):
    def test_candidate_search_rejects_public_member_and_unsupported_channels(self):
        roles = [role(1, 1024), role(2, 8)]
        raw = dict(id='10', type=0, permission_overwrites=[])
        self.assertFalse(private_candidate(1, roles, raw))
        raw['permission_overwrites'] = [dict(id='1', type=0, allow='0', deny='1024')]
        self.assertTrue(private_candidate(1, roles, raw))
        raw['permission_overwrites'].append(dict(id='77', type=1, allow='1024', deny='0'))
        self.assertFalse(private_candidate(1, roles, raw))
        raw.update(type=20, permission_overwrites=[])
        self.assertFalse(private_candidate(1, roles, raw))

    def test_admin_only_and_member_allow_fail_closed(self):
        guild = NS(id=1)
        everyone, admin, mod = role(1), role(2, 8), role(3, 8192)
        target = Mock(spec=discord.TextChannel)
        target.guild = guild
        target.overwrites = {everyone: discord.PermissionOverwrite(view_channel=False),
                             admin: discord.PermissionOverwrite(view_channel=True)}
        private_destination(guild, [everyone, admin, mod], target)
        target.overwrites[mod] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaises(ValueError):
            private_destination(guild, [everyone, admin, mod], target)
        del target.overwrites[mod]
        target.overwrites[discord.Object(77)] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaises(ValueError):
            private_destination(guild, [everyone, admin, mod], target)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.bot = Mock()
        self.cog = Maintenance.__new__(Maintenance)
        self.cog.bot = self.bot
        self.cog.store = Store(Path(self.folder.name) / 'maintenance.db')
        self.cog.lock = asyncio.Lock()
        token = self.cog.store.preview(1, 7, observed(), 10)
        self.cog.store.accept(1, 7, token, observed())
        self.cog.store.enable(1, True)
        self.guild = NS(id=1)
        self.cog.collect = AsyncMock(return_value=observed())
        self.cog.health = AsyncMock(return_value=['loop stopped'])
        self.destination = Mock()
        self.destination.send = AsyncMock(return_value=NS(id=99))
        self.cog.destination = AsyncMock(return_value=self.destination)

    async def test_private_alert_once_and_no_blind_retry(self):
        self.destination.send.side_effect = TimeoutError()
        await self.cog.check(self.guild, background=True)
        await self.cog.check(self.guild, background=True)
        await self.cog.check(self.guild, background=True)
        self.destination.send.assert_awaited_once()
        self.assertEqual(self.cog.store.state(1)['receipts'], {'uncertain': 1})

    async def test_privacy_failure_never_sends_or_reserves(self):
        self.cog.destination.side_effect = ValueError('public')
        await self.cog.check(self.guild, background=True)
        await self.cog.check(self.guild, background=True)
        self.destination.send.assert_not_awaited()
        self.assertEqual(self.cog.store.state(1)['receipts'], {})

    async def test_cancel_during_send_keeps_uncertain(self):
        self.destination.send.side_effect = asyncio.CancelledError()
        await self.cog.check(self.guild, background=True)
        with self.assertRaises(asyncio.CancelledError):
            await self.cog.check(self.guild, background=True)
        self.assertEqual(Store(self.cog.store.path).state(1)['receipts'], {'uncertain': 1})

    async def test_partial_read_never_reports_empty_or_updates_baseline(self):
        self.cog.collect.side_effect = RuntimeError('missing channel read')
        result = await self.cog.check(self.guild, background=False)
        self.assertEqual(result, {'read_error': True})
        self.assertEqual(self.cog.store.state(1)['baseline']['snapshot'], observed())
        self.destination.send.assert_not_awaited()

    async def test_collector_uses_raw_unknown_types_and_fresh_core_members(self):
        del self.cog.collect
        self.bot.user = NS(id=9)
        roles = [role(1), role(2, bot=9), role(3, bot=8, name='Dyno'), role(4, bot=7, name='Carl-bot')]
        guild = NS(id=1, fetch_roles=AsyncMock(return_value=roles),
                   fetch_automod_rules=AsyncMock(return_value=[]),
                   fetch_member=AsyncMock(return_value=NS(roles=[roles[0]])),
                   _state=NS(http=NS(get_all_guild_channels=AsyncMock(return_value=[dict(id='20', type=20)]))))
        with patch('utils.is_temp_vc_id', return_value=False):
            value = await self.cog.collect(guild)
        self.assertIn('20', value['channels'])
        self.assertEqual(set(value['bots']), {'7', '8', '9'})
        self.assertEqual(guild.fetch_member.await_count, 3)

    async def test_fresh_authority_ignores_stale_cached_permissions(self):
        member = NS(id=7, _roles=[2], guild_permissions=discord.Permissions.all())
        guild = NS(owner_id=99, fetch_member=AsyncMock(return_value=member),
                   fetch_roles=AsyncMock(return_value=[role(1), role(2)]))
        inter = NS(guild_id=1, guild=guild, user=NS(id=7))
        with patch('cogs.maintenance.config.GUILD_ID', 1):
            self.assertFalse(await self.cog.authorize(inter))
            guild.fetch_roles.return_value = [role(1), role(2, 32)]
            self.assertTrue(await self.cog.authorize(inter))

    async def test_same_target_new_values_make_new_drift_fingerprint(self):
        self.cog.health.return_value = []
        a = observed(); a['roles']['1'] = '1024'
        self.cog.collect.return_value = a
        await self.cog.check(self.guild, background=True)
        await self.cog.check(self.guild, background=True)
        b = observed(); b['roles']['1'] = '2048'
        self.cog.collect.return_value = b
        await self.cog.check(self.guild, background=True)
        await self.cog.check(self.guild, background=True)
        self.assertEqual(self.destination.send.await_count, 2)

    async def test_delivery_probe_is_labelled_and_once_per_baseline(self):
        self.assertIn('已送出', await self.cog.test_delivery(self.guild))
        self.assertIn('唔會重發', await self.cog.test_delivery(self.guild))
        self.destination.send.assert_awaited_once()
        self.assertIn('並非異常警報', self.destination.send.call_args.args[0])

    async def test_delivery_probe_timeout_never_retries(self):
        self.destination.send.side_effect = TimeoutError()
        self.assertIn('結果不明', await self.cog.test_delivery(self.guild))
        self.assertIn('唔會重發', await self.cog.test_delivery(self.guild))
        self.destination.send.assert_awaited_once()

    async def test_manual_check_never_sends(self):
        for _ in range(3):
            await self.cog.check(self.guild, background=False)
        self.destination.send.assert_not_awaited()
