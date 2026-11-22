import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from features.squad_plans import PlanBook, confirmed, deadline, reminder_recipients


class AssemblyBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'plans.json'
        self.now = 10000
        self.book = PlanBook(self.path, lambda: self.now)

    def create(self, **options):
        args = dict(guild=1, channel=2, owner=3, game='Game', mode='Mode', start=self.now + 60,
                    party=1, capacity=None, assembly_host=True)
        args.update(options)
        p = self.book.create(**args)
        self.book.publish(p['id'], 10)
        return p['id']

    def restart(self):
        self.book = PlanBook(self.path, lambda: self.now)

    def edit(self, key, **changes):
        p = self.book.get(key)
        values = {k: p[k] for k in ('game', 'mode', 'start', 'party', 'capacity')}
        return self.book.act(key, 3, 'edit', changes=values | changes)

    def test_new_scheduled_only_and_legacy_file_preserved(self):
        legacy = self.create(assembly_host=None)
        original = self.path.read_bytes()
        self.restart()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn('assembly', self.book.get(legacy))
        with self.assertRaises(ValueError):
            self.book.act(legacy, 4, 'join_due')
        instant = self.create(instant=True)
        self.assertNotIn('assembly', self.book.get(instant))
        for enabled in (True, False):
            key = self.create(assembly_host=enabled)
            self.assertEqual(self.book.get(key)['assembly'], dict(
                generation=1, host=enabled, members=[], waiting=[], due={}, nudge={}, retired=[]))
        with self.assertRaises(ValueError):
            self.create(owner=5, assembly_host=1)

    def test_switches_preserve_rsvp_actual_start_reminder_and_host_notice(self):
        key = self.create(delivery_options=dict(minimum=None, auto_event=False, host_notices=True))
        self.book.act(key, 4, 'late')
        self.assertEqual(self.book.get(key)['assembly']['members'], [])
        self.book.act(key, 4, 'remind_on')
        self.book.clean(key)
        before = self.book.get(key)
        for action, expected in [('join_due', [4]), ('join_only', []), ('join_only', [])]:
            p = self.book.act(key, 4, action, generation=1)
            self.assertEqual(p['assembly']['members'], expected)
            self.assertEqual(p['late'], [4])
            self.assertEqual(reminder_recipients(p), {4})
            self.assertEqual(p['revision'], before['revision'])
            self.assertEqual(p['delivery'], before['delivery'])
            self.assertFalse(p['dirty'])
        self.book.assembly_action(key, 4, 'due_on', 1)
        self.assertEqual(self.book.act(key, 4, 'remind_off')['assembly']['members'], [4])
        self.assertEqual(self.book.assembly_action(key, 4, 'due_off', 1)['assembly']['members'], [])
        for user, action in [(3, 'due_on'), (5, 'due_on'), (4, 'host_off')]:
            with self.assertRaises(ValueError):
                self.book.assembly_action(key, user, action, 1)

    def test_due_opt_in_closes_at_start_but_rsvp_remains_available(self):
        key = self.create()
        self.book.act(key, 4, 'join')
        self.now += 60
        for delivered in (False, True):
            if delivered:
                self.assertTrue(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
                self.assertTrue(self.book.assembly_receipt(key, 1, 'due', 'sending', 'sent', message=226))
            with self.assertRaisesRegex(ValueError, '只報名'):
                self.book.act(key, 5, 'join_due', generation=1)
            with self.assertRaisesRegex(ValueError, '只報名'):
                self.book.assembly_action(key, 4, 'due_on', 1)
            self.assertEqual(self.book.get(key)['members'], [4])
        p = self.book.act(key, 5, 'join_only', generation=1)
        self.assertEqual(p['members'], [4, 5])
        self.assertEqual(p['assembly']['members'], [])

    def test_atomic_capacity_and_failed_storage(self):
        key = self.create(capacity=2)
        with patch('features.squad_plans.atomic_write_json', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.book.act(key, 7, 'join_due', generation=1)
        self.assertEqual(self.book.get(key)['members'], [])

        def join(uid):
            try:
                self.book.act(key, uid, 'join_due', generation=1)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(join, range(10, 30))), 1)
        self.restart()
        p = self.book.get(key)
        self.assertEqual(len(confirmed(p)), 1)
        self.assertEqual(p['assembly']['members'], confirmed(p))
        self.assertEqual(reminder_recipients(p), set())

    def test_wait_and_nudge_permissions_and_boundaries(self):
        key = self.create(assembly_host=False)
        self.book.act(key, 4, 'join_only')
        start = self.book.get(key)['start']
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'wait', 1)
        self.now = start
        self.book.clean(key)
        before = self.book.get(key)
        self.book.assembly_action(key, 4, 'wait', 1)
        with patch.object(self.book, '_write', side_effect=AssertionError('unexpected duplicate write')):
            p = self.book.assembly_action(key, 4, 'wait', 1)
        self.assertEqual(p['assembly']['waiting'], [4])
        self.assertEqual(p, dict(before, assembly=p['assembly'], dirty=True, revision=before['revision'] + 1))
        self.now += 300
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'nudge', 1)
        self.book.assembly_action(key, 3, 'host_on', 1)
        self.now -= 1
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'nudge', 1)
        self.now += 1
        for user in (3, 8):
            for action in ('wait', 'nudge'):
                with self.assertRaises(ValueError):
                    self.book.assembly_action(key, user, action, 1)
        req = self.book.assembly_action(key, 4, 'nudge', 1)['assembly']['nudge']
        self.assertEqual(req, dict(state='requested', actor=4, requested_at=self.now))
        self.restart()
        self.assertEqual(self.book.get(key)['assembly']['nudge'], req)
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'nudge', 1)
        self.book.assembly_action(key, 3, 'host_off', 1)
        self.book.assembly_action(key, 3, 'host_on', 1)
        self.assertFalse(self.book.assembly_receipt(key, 1, 'nudge', 'requested', 'sending'))
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'nudge', 1)

    def test_leave_clears_opt_in_wait_and_prevents_pending_nudge(self):
        key = self.create()
        self.book.act(key, 4, 'join_due')
        self.now += 360
        self.book.assembly_action(key, 4, 'wait', 1)
        self.book.assembly_action(key, 4, 'nudge', 1)
        self.book.act(key, 4, 'leave')
        self.restart()
        a = self.book.get(key)['assembly']
        self.assertEqual(a['members'], [])
        self.assertEqual(a['waiting'], [])
        self.assertEqual(a['nudge']['state'], 'skipped')
        self.assertFalse(self.book.assembly_receipt(key, 1, 'nudge', 'requested', 'sending'))

    def test_room_opened_early_can_send_due_but_cannot_wait_or_nudge(self):
        key = self.create()
        self.book.act(key, 4, 'join')
        self.book.link_voice(key, 3, 99)
        self.assertFalse(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
        self.now += 360
        self.assertTrue(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
        for released in (False, True):
            if released:
                self.book.release_voice(key)
                self.restart()
            for action in ('wait', 'nudge'):
                with self.assertRaises(ValueError):
                    self.book.assembly_action(key, 4, action, 1)

    def test_concurrent_claims_material_edits_and_stale_interactions(self):
        key = self.create()
        self.book.act(key, 4, 'join_due')
        self.now += 360
        self.book.assembly_action(key, 4, 'wait', 1)
        self.book.assembly_action(key, 4, 'nudge', 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = pool.map(lambda _: self.book.assembly_receipt(key, 1, 'due', None, 'sending'), range(20))
            self.assertEqual(sum(claims), 1)
        self.restart()
        self.assertFalse(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
        self.assertTrue(self.book.assembly_receipt(key, 1, 'due', 'sending', 'sent', message=120))
        self.edit(key, party=2)
        self.assertEqual(self.book.get(key)['assembly']['generation'], 1)
        self.book.link_voice(key, 3, 99)
        self.edit(key, mode='B')
        p = self.edit(key, mode='Mode')
        self.assertEqual(p['unconfirmed'], [4])
        self.assertNotIn('voice', p)
        self.assertEqual(p['assembly'], dict(generation=3, host=True, members=[], waiting=[],
                                            due={}, nudge={}, retired=[120]))
        for old in (1, 2):
            for action in ('join_due', 'join_only', 'join', 'late'):
                with self.assertRaisesRegex(ValueError, '約局已更新'):
                    self.book.act(key, 4, action, generation=old)
            with self.assertRaises(ValueError):
                self.book.assembly_action(key, 3, 'host_off', old)
            self.assertFalse(self.book.assembly_receipt(key, old, 'due', None, 'sending'))
        with self.assertRaises(ValueError):
            self.book.assembly_action(key, 4, 'wait', 3)
        self.book.act(key, 4, 'join', generation=3)
        self.assertEqual(self.book.get(key)['assembly']['members'], [])
        self.restart()
        self.assertTrue(self.book.assembly_retire_done(key, 120))
        self.assertFalse(self.book.assembly_retire_done(key, 120))

    def test_closed_plans_retire_sent_receipts_once(self):
        for endpoint in ('cancel', 'expire', 'end'):
            with self.subTest(endpoint=endpoint):
                key = self.create()
                self.book.act(key, 4, 'join')
                self.now += 360
                self.book.assembly_action(key, 4, 'nudge', 1)
                self.assertTrue(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
                if endpoint == 'cancel':
                    self.book.act(key, 3, 'cancel')
                elif endpoint == 'end':
                    self.book.link_voice(key, 3, 99)
                    self.book.sync_session(key, 99, 100, ended=True)
                else:
                    self.now = deadline(self.book.get(key)) + 1
                    with self.assertRaises(ValueError):
                        self.book.assembly_action(key, 4, 'wait', 1)
                    self.book.expire()
                # A confirmed delivery may complete just after a concurrent close.
                self.assertTrue(self.book.assembly_receipt(key, 1, 'due', 'sending', 'sent', message=130))
                self.assertEqual(self.book.get(key)['assembly']['retired'], [130])
                self.assertFalse(self.book.assembly_receipt(key, 1, 'nudge', 'requested', 'sending'))
                self.assertTrue(self.book.assembly_retire_done(key, 130))
                self.book.expire()
                self.restart()
                self.assertEqual(self.book.get(key)['assembly']['retired'], [])

    def test_failed_ambiguous_skipped_receipts_never_rearm(self):
        for terminal in ('unknown', 'failed', 'skipped'):
            key = self.create()
            self.now += 60
            self.assertTrue(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))
            self.restart()
            self.assertTrue(self.book.assembly_receipt(key, 1, 'due', 'sending', terminal))
            self.restart()
            self.assertFalse(self.book.assembly_receipt(key, 1, 'due', terminal, 'sending'))
            self.assertFalse(self.book.assembly_receipt(key, 1, 'due', None, 'sending'))

    def test_invalid_assembly_fails_closed_preserving_file(self):
        key = self.create()
        initial = self.path.read_text()
        for field, bad in [('generation', True), ('host', 1), ('members', [4]), ('waiting', [3]),
                           ('retired', [42, 42]), ('retired', [10]), ('opened', 'yes'),
                           ('due', {'state': 'sent'}), ('due', {'state': 'other'}),
                           ('nudge', {'state': 'requested', 'actor': 8})]:
            state = json.loads(initial)
            state['plans'][key]['assembly'][field] = bad
            data = json.dumps(state).encode()
            self.path.write_bytes(data)
            with self.subTest(field=field, bad=bad), self.assertRaisesRegex(ValueError, 'Invalid plan assembly'):
                self.restart()
            self.assertEqual(self.path.read_bytes(), data)
