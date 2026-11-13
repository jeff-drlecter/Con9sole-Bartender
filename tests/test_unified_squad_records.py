"""Preserve real reservation semantics across migration, edits and voice linkage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from features.squad_plans import PlanBook, confirmed


class UnifiedRecords(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'plans.json'
        self.now = 10000
        self.book = PlanBook(self.path, clock=lambda: self.now)

    def create(self, **kw):
        values = dict(guild=1, channel=2, owner=3, game='FC', mode='Clubs',
                      start=self.now + 100, party=1, capacity=5)
        values.update(kw)
        p = self.book.create(**values)
        self.book.publish(p['id'], 99)
        return self.book.get(p['id'])

    def test_legacy_record_keeps_all_four_members_ids_links_and_unknown_fields(self):
        p = self.create()
        for user in range(4, 8):
            self.book.act(p['id'], user, 'join')
        original = self.book.state
        original.pop('schema')
        original['plans'][p['id']].update(status='started', extra={'keep': True})
        raw = json.dumps(original).encode()
        self.path.write_bytes(raw)
        self.now += 101
        upgraded = PlanBook(self.path, clock=lambda: self.now)
        value = upgraded.get(p['id'])
        self.assertEqual(value['members'], [4, 5, 6, 7])
        self.assertEqual((value['id'], value['message'], value['owner'], value['channel']), (p['id'], 99, 3, 2))
        self.assertEqual(value['extra'], {'keep': True})
        self.assertEqual(value['status'], 'due')
        self.assertEqual(self.path.with_suffix('.json.before-unified-v2').read_bytes(), raw)
        self.assertEqual(PlanBook(self.path, clock=lambda: self.now).get(p['id']), value)

    def test_old_unknown_started_is_history_not_fake_attendance(self):
        p = self.create()
        state = self.book.state
        state.pop('schema')
        state['plans'][p['id']]['status'] = 'started'
        self.path.write_text(json.dumps(state))
        self.now += 10000
        migrated = PlanBook(self.path, clock=lambda: self.now).get(p['id'])
        self.assertEqual(migrated['status'], 'history')
        self.assertNotIn('session', migrated)

    def test_corrupt_and_unsupported_files_are_never_rotated_or_reset(self):
        for raw in (b'{broken', b'{"schema":9,"plans":{}}', b'{"plans":{"bad":{}}}'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                PlanBook(self.path)
            self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)

    def test_now_uses_same_records_and_allows_three_future_plans(self):
        for _ in range(3):
            self.create()
        p = self.create(instant=True)
        self.assertEqual((p['start'], p['status']), (self.now, 'due'))
        with self.assertRaises(ValueError):
            self.create(instant=True)
        self.assertEqual(len(self.book.all()), 4)

    def test_late_is_a_reserved_place_not_duplicate_or_attendance(self):
        p = self.create(capacity=2)
        self.now += 101
        self.book.expire()
        self.book.act(p['id'], 4, 'late')
        with self.assertRaises(ValueError):
            self.book.act(p['id'], 5, 'join')
        p = self.book.act(p['id'], 4, 'join')
        self.assertEqual((p['members'], p['late'], p['status']), ([4], [], 'due'))
        self.assertNotIn('session', p)
        self.book.act(p['id'], 4, 'leave')
        self.book.act(p['id'], 3, 'cancel')

    def test_edit_keeps_history_but_requires_reconfirmation(self):
        p = self.create(capacity=3)
        self.book.act(p['id'], 4, 'late')
        p = self.book.get(p['id'])
        changes = {k: p[k] for k in ('game', 'mode', 'start', 'party', 'capacity')}
        changes.update(start=self.now + 200, mode='PC／Rush', capacity=2)
        p = self.book.act(p['id'], 3, 'edit', changes=changes)
        self.assertEqual((p['members'], p['unconfirmed'], confirmed(p)), ([4], [4], []))
        self.assertEqual(p['changes'][0]['mode'], 'Clubs')
        self.book.act(p['id'], 5, 'join')
        with self.assertRaises(ValueError):
            self.book.act(p['id'], 4, 'join')
        self.book.act(p['id'], 4, 'leave')
        self.assertEqual(self.book.get(p['id'])['unconfirmed'], [])

    def test_owner_voice_link_is_unique_and_actual_session_is_separate(self):
        p = self.create()
        other = self.create(owner=8)
        with self.assertRaises(ValueError):
            self.book.link_voice(p['id'], 8, 500)
        self.book.link_voice(p['id'], 3, 500)
        with self.assertRaises(ValueError):
            self.book.link_voice(other['id'], 8, 500)
        self.book.sync_session(p['id'], 500, 'session-a')
        self.assertIsNone(self.book.sync_session(p['id'], 500, 'session-b', ended=True))
        p = self.book.sync_session(p['id'], 500, 'session-a', ended=True, footprint=900)
        self.assertEqual((p['status'], p['footprint'], p['members']), ('ended', 900, []))
        self.assertEqual(PlanBook(self.path).get(p['id'])['message'], 99)

    def test_unknown_creation_is_not_replayed_and_known_room_recovers(self):
        p = self.create()
        self.book.begin_voice_attempt(p['id'], 3)
        restored = PlanBook(self.path, clock=lambda: self.now)
        with self.assertRaises(ValueError):
            restored.begin_voice_attempt(p['id'], 3)
        p = restored.link_voice(p['id'], 3, 500)
        self.assertNotIn('voice_attempt', p)

    def test_stale_card_refresh_cannot_clear_a_newer_change(self):
        p = self.create()
        old = p.get('revision', 0)
        self.book.act(p['id'], 4, 'join')
        self.book.clean(p['id'], old)
        self.assertTrue(self.book.get(p['id'])['dirty'])

    def test_failed_voice_save_does_not_change_the_record(self):
        p = self.create()
        with patch('features.squad_plans.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.book.link_voice(p['id'], 3, 500)
        self.assertNotIn('voice', self.book.get(p['id']))

    def test_size_edit_keeps_gathering_and_original_time_can_be_retained(self):
        p = self.create()
        self.now += 101
        self.book.expire()
        p = self.book.link_voice(p['id'], 3, 500)
        changes = {k: p[k] for k in ('game', 'mode', 'start', 'party', 'capacity')}
        changes['capacity'] = 6
        p = self.book.act(p['id'], 3, 'edit', changes=changes)
        self.assertEqual((p['status'], p['voice']), ('gathering', 500))
