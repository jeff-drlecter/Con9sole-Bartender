import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.http import handle_message_parameters

import config
from features import plan_assembly_delivery as assembly
from features.squad_plans import PlanBook, deadline


class AssemblyDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 10_000
        self.book = PlanBook(Path(tmp.name) / 'plans.json', clock=lambda: self.now)
        self.guild = N(id=config.GUILD_ID, unavailable=False, fetch_roles=AsyncMock(return_value=[]))
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild = 20, self.guild
        self.channel.permissions_for.return_value = discord.Permissions.all()
        self.guild.fetch_channel = AsyncMock(return_value=self.channel)
        self.guild.fetch_member = AsyncMock(side_effect=lambda uid: N(id=uid, guild=self.guild, bot=uid == 9))
        self.denied = set()
        self.enterContext(patch('cogs.squad_plans.allowed', side_effect=lambda i: i.user.id not in self.denied))
        self.enterContext(patch('cogs.squad_plans.can_read', side_effect=lambda i: i.user.id not in self.denied))
        self.cog = N(book=self.book, bot=N(user=N(id=9), get_guild=lambda _: self.guild))
        self.delivery = assembly.AssemblyDelivery(self.cog)
        self.enterContext(patch.object(assembly, '_view', side_effect=self.view))
        self.original = self.message(99)
        self.messages = {99: self.original}
        self.channel.fetch_message.side_effect = self.fetch
        self.channel.send.side_effect = self.send
        self.key = self.plan()

    def plan(self, host=True):
        p = self.book.create(guild=config.GUILD_ID, channel=20, owner=1, game='Example', mode='PC',
                             start=self.now + 30, party=1, capacity=None, assembly_host=host)
        self.book.publish(p['id'], 99)
        return p['id']

    def message(self, mid):
        m = N(id=mid, author=N(id=9), guild=self.guild, channel=self.channel, content='', components=[])
        async def edit(**kw):
            m.content = kw['content']
            m.components = self.components(kw.get('view'))
        m.edit = AsyncMock(side_effect=edit)
        return m

    @staticmethod
    def view(cog, p):
        v = discord.ui.View(timeout=None)
        v.add_item(discord.ui.Button(label='加入語音' if p.get('voice') else '我在等',
                                     custom_id='synthetic-control'))
        return v

    @staticmethod
    def components(view):
        return [] if view is None else [N(to_dict=lambda data=d: data) for d in view.to_components()]

    async def fetch(self, mid):
        if mid not in self.messages:
            raise discord.NotFound(N(status=404, reason='gone'), '')
        return self.messages[mid]

    async def send(self, content, **kw):
        kind = 'due' if kw['view'] is not None else 'nudge'
        persisted = PlanBook(self.book.path).get(self.key)['assembly'][kind]
        self.assertEqual(persisted['state'], 'sending')
        mid = 300 + len(self.messages)
        msg = self.message(mid)
        msg.content, msg.components = content, self.components(kw['view'])
        self.messages[mid] = msg
        return msg

    def p(self):
        return self.book.get(self.key)

    def join(self, uid, opt=True):
        self.book.act(self.key, uid, 'join_due' if opt else 'join_only', generation=1)

    def action(self, uid, name):
        return self.book.assembly_action(self.key, uid, name, self.p()['assembly']['generation'])

    def due(self, offset=0):
        self.now = self.p()['start'] + offset
        self.book.expire()

    async def tick(self):
        await self.delivery.tick(self.p())

    def mentions(self):
        kwargs = self.channel.send.await_args.kwargs
        options = kwargs['allowed_mentions'].to_dict()
        self.assertEqual(options['parse'], [])
        self.assertFalse(options.get('replied_user'))
        return options.get('users', [])

    async def test_only_consented_readable_members_and_host_in_single_original_post(self):
        self.join(2)
        self.join(3, False)
        self.join(4)
        self.join(5)
        self.book.act(self.key, 5, 'leave')
        self.denied.add(4)
        await self.tick()
        self.channel.send.assert_not_awaited()
        self.due()
        await self.tick()
        self.assertEqual(self.mentions(), [1, 2])
        args = self.channel.send.await_args
        self.assertIn('/20/99', args.args[0])
        self.assertNotIn('<@3>', args.args[0])
        self.assertLessEqual(len(args.kwargs['nonce']), 25)
        with handle_message_parameters(content=args.args[0], nonce=args.kwargs['nonce']) as spec:
            self.assertTrue(spec.payload['enforce_nonce'])
        reads = self.guild.fetch_channel.await_count
        await self.tick()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.guild.fetch_channel.await_count, reads)

    async def test_opt_out_and_missing_original(self):
        self.action(1, 'host_off')
        self.join(2)
        self.action(2, 'due_off')
        self.due()
        del self.messages[99]
        await self.tick()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.p()['assembly']['due']['state'], 'skipped')

    async def test_consent_revoked_during_access_without_revision_bump(self):
        self.join(2)
        self.due()
        revision = self.p()['revision']
        async def revoke(mid):
            self.action(2, 'due_off')
            self.assertEqual(self.p()['revision'], revision)
            return await self.fetch(mid)
        self.channel.fetch_message.side_effect = revoke
        await self.tick()
        self.channel.send.assert_not_awaited()
        await self.tick()
        self.assertEqual(self.mentions(), [1])

    async def test_due_late_is_silent_no_roster_scan_including_exact_deadline(self):
        self.join(2)
        self.due(deadline(self.p()) - self.p()['start'])
        await self.tick()
        self.assertEqual(self.mentions(), [])
        self.assertEqual([c.args[0] for c in self.guild.fetch_member.await_args_list], [9])

    async def test_crossing_time_boundary_while_fetching_avoids_stale_ping(self):
        self.join(2)
        self.due(299)
        async def delayed(mid):
            self.now += 2
            return await self.fetch(mid)
        self.channel.fetch_message.side_effect = delayed
        await self.tick()
        self.assertEqual(self.mentions(), [])

    async def test_room_opened_before_due_uses_join_voice_no_nudge(self):
        self.join(2)
        self.book.link_voice(self.key, 1, 500)
        await self.tick()
        self.channel.send.assert_not_awaited()
        self.due()
        await self.tick()
        args = self.channel.send.await_args
        self.assertIn('加入語音', args.args[0])
        self.assertEqual(args.kwargs['view'].children[0].label, '加入語音')
        self.due(300)
        with self.assertRaises(ValueError):
            self.action(2, 'nudge')
        await self.tick()
        self.channel.send.assert_awaited_once()

    async def test_waiting_count_only_then_room_open_updates_same_post(self):
        self.join(23, False)
        self.due()
        await self.tick()
        msg = self.messages[self.p()['assembly']['due']['message']]
        self.action(23, 'wait')
        await self.tick()
        self.assertIn('1 人', msg.content)
        self.assertNotIn('<@', msg.content)
        self.assertEqual(msg.edit.await_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.book.link_voice(self.key, 1, 500)
        await self.tick()
        self.assertIn('加入語音', msg.content)
        self.assertNotIn('等候', msg.content)
        self.channel.send.assert_awaited_once()

    async def test_public_nudge_is_one_host_only_with_fresh_requester(self):
        self.join(2, False)
        self.due(299)
        await self.tick()
        with self.assertRaises(ValueError):
            self.action(2, 'nudge')
        self.due(300)
        self.action(2, 'nudge')
        self.guild.fetch_member.reset_mock()
        await self.tick()
        self.assertEqual(self.mentions(), [1])
        self.assertNotIn('<@2>', self.channel.send.await_args.args[0])
        self.assertIn(2, [c.args[0] for c in self.guild.fetch_member.await_args_list])
        self.assertIsNone(self.channel.send.await_args.kwargs['view'])
        self.assertEqual(self.p()['assembly']['nudge']['state'], 'sent')
        self.assertNotEqual(*(c.kwargs['nonce'] for c in self.channel.send.await_args_list))
        await self.tick()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_denied_requester_and_delayed_request_never_nudge(self):
        for reason in ('requester', 'delay'):
            with self.subTest(reason=reason):
                self.key = self.plan()
                self.join(2)
                self.due(300)
                await self.tick()
                self.channel.send.reset_mock()
                self.action(2, 'nudge')
                if reason == 'requester':
                    self.denied.add(2)
                else:
                    self.now += 301
                await self.tick()
                self.assertEqual(self.p()['assembly']['nudge']['state'], 'skipped')
                self.channel.send.assert_not_awaited()
                self.denied.clear()

    async def test_ambiguous_and_explicit_errors_are_never_retried(self):
        for err, expected in ((TimeoutError(), 'unknown'), (discord.Forbidden(N(status=403, reason='deny'), ''), 'failed')):
            with self.subTest(expected=expected):
                self.key = self.plan()
                self.due()
                self.channel.send.side_effect = err
                self.channel.send.reset_mock()
                await self.tick()
                self.assertEqual(self.p()['assembly']['due']['state'], expected)
                self.cog.book = self.book = PlanBook(self.book.path, clock=lambda: self.now)
                self.delivery = assembly.AssemblyDelivery(self.cog)
                await self.tick()
                self.channel.send.assert_awaited_once()

    async def test_restart_with_persisted_intent_never_calls_discord(self):
        self.due()
        self.book.assembly_receipt(self.key, 1, 'due', None, 'sending')
        self.cog.book = self.book = PlanBook(self.book.path, clock=lambda: self.now)
        self.delivery = assembly.AssemblyDelivery(self.cog)
        await self.tick()
        self.assertEqual(self.p()['assembly']['due']['state'], 'unknown')
        self.channel.send.assert_not_awaited()

    async def test_retire_cancel_and_terminal_no_rest(self):
        self.due()
        await self.tick()
        mid = self.p()['assembly']['due']['message']
        self.book.act(self.key, 1, 'cancel')
        self.assertIn(mid, self.p()['assembly']['retired'])
        await self.tick()
        self.assertEqual(self.p()['assembly']['retired'], [])
        self.assertEqual(self.messages[mid].content, assembly.CLOSED_TEXT)
        self.assertEqual(self.messages[mid].components, [])
        self.guild.fetch_channel.reset_mock()
        self.delivery = assembly.AssemblyDelivery(self.cog)
        await self.tick()
        self.guild.fetch_channel.assert_not_awaited()

    async def test_deleted_original_redacts_active_mirror_no_role_or_member_ids(self):
        self.due()
        await self.tick()
        mid = self.p()['assembly']['due']['message']
        del self.messages[99]
        self.book.availability(self.key, 'card_deleted')
        await self.delivery.refresh(self.p())
        self.assertEqual(self.messages[mid].content, assembly.CLOSED_TEXT)
        self.assertEqual(self.messages[mid].components, [])

    async def test_wrong_author_guild_channel_or_id_never_edits(self):
        self.due()
        await self.tick()
        mid = self.p()['assembly']['due']['message']
        for field, other in (('guild', N(id=-1)), ('channel', N(id=50)), ('author', N(id=77)), ('id', 99)):
            with self.subTest(field=field):
                self.delivery = assembly.AssemblyDelivery(self.cog)
                impostor = self.message(mid)
                setattr(impostor, field, other)
                self.messages[mid] = impostor
                await self.delivery.refresh(self.p())
                impostor.edit.assert_not_awaited()

    async def test_large_roster_respects_message_and_lookup_limits(self):
        users = [10**18 + i for i in range(120)]
        for uid in users:
            self.join(uid)
        self.denied.update(users[:3])
        self.due()
        await self.tick()
        args = self.channel.send.await_args
        self.assertLessEqual(len(args.args[0]), 2000)
        ids = self.mentions()
        self.assertEqual(ids[:2], [1, users[3]])
        self.assertLessEqual(len(ids), 100)
        reads = [c.args[0] for c in self.guild.fetch_member.await_args_list if c.args[0] != 9]
        self.assertLessEqual(len(reads), 100)
        self.assertEqual(reads[:4], [1, *users[:3]])

    async def test_source_deleted_during_member_scan_prevents_post(self):
        self.join(2)
        self.due()
        async def missing_after_scan(uid):
            if uid == 2:
                del self.messages[99]
            return N(id=uid, guild=self.guild, bot=uid == 9)
        self.guild.fetch_member.side_effect = missing_after_scan
        await self.tick()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.p()['assembly']['due']['state'], 'skipped')

    async def test_unavailable_guild_uses_cooldown_then_posts_silently(self):
        self.join(2)
        self.due()
        self.guild.unavailable = True
        await self.tick()
        self.assertEqual(self.p()['assembly']['due'], {})
        self.guild.unavailable = False
        await self.tick()
        self.guild.fetch_channel.assert_not_awaited()
        self.now += 301
        await self.tick()
        self.assertEqual(self.mentions(), [])

    async def test_cancel_during_preflight_and_expired_plan_never_posts(self):
        self.due()
        async def cancel(mid):
            self.book.act(self.key, 1, 'cancel')
            self.channel.fetch_message.side_effect = self.fetch
            return await self.fetch(mid)
        self.channel.fetch_message.side_effect = cancel
        await self.tick()
        self.channel.send.assert_not_awaited()
        self.key = self.plan()
        self.now = deadline(self.p()) + 1
        self.book.expire()
        await self.tick()
        self.channel.send.assert_not_awaited()

    async def test_retirement_with_write_permission_revoked_can_still_redact(self):
        self.due()
        await self.tick()
        mid = self.p()['assembly']['due']['message']
        self.book.act(self.key, 1, 'cancel')
        perms = discord.Permissions.all()
        perms.send_messages = False
        self.channel.permissions_for.return_value = perms
        await self.tick()
        self.assertEqual(self.messages[mid].content, assembly.CLOSED_TEXT)
