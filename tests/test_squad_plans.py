import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from features.squad_plans import HK, PlanBook, counts, parse_start


class ScheduledSquadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 11, 12, 21, 0, tzinfo=HK)
        self.clock = self.now.timestamp()
        self.path = Path(self.temp.name) / 'plans.json'
        self.book = PlanBook(self.path, lambda: self.clock)

    def create(self, **changes):
        values = dict(guild=1, channel=2, owner=3, game='FC', mode='Clubs',
                      start=self.clock + 3600, party=3, capacity=4)
        values.update(changes)
        p = self.book.create(**values)
        self.book.publish(p['id'], 9)
        return p['id']

    def test_local_dates_do_not_silently_roll_over(self):
        self.assertEqual(parse_start('今晚22：00', self.now), int(self.clock + 3600))
        self.assertEqual(parse_start('明天22:00', self.now), int(self.clock + 25 * 3600))
        self.assertEqual(parse_start('2026-11-13 22:00', self.now), int(self.clock + 25 * 3600))
        for value in ['20:00', '今晚10點', '25:00', '2026-02-31 22:00', '2026-12-01 22:00']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_start(value, self.now)

    def test_party_includes_host_and_capacity_is_optional(self):
        self.assertEqual(counts('3', '2'), (3, 5))
        self.assertEqual(counts('1', ''), (1, None))
        for party, missing in [('0', ''), ('3', '0'), ('abc', '2'), ('100', '1')]:
            with self.assertRaises(ValueError):
                counts(party, missing)

    def test_duplicate_host_and_full_rsvps(self):
        key = self.create()
        with self.assertRaises(ValueError):
            self.book.act(key, 3, 'join')
        self.book.act(key, 4, 'join')
        for user in [4, 5]:
            with self.assertRaises(ValueError):
                self.book.act(key, user, 'join')
        self.book.act(key, 4, 'leave')
        self.book.act(key, 5, 'join')
        self.assertEqual(self.book.get(key)['members'], [5])

    def test_last_place_is_atomic(self):
        key = self.create()
        def attempt(user):
            try:
                self.book.act(key, user, 'join')
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(10, 30)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(PlanBook(self.path).get(key)['members']), 1)

    def test_only_host_edits_admin_can_cancel(self):
        key = self.create()
        p = self.book.get(key)
        changes = {k: p[k] for k in ['game', 'mode', 'start', 'party', 'capacity']}
        with self.assertRaises(ValueError):
            self.book.act(key, 8, 'edit', changes=changes, admin=True)
        with self.assertRaises(ValueError):
            self.book.act(key, 8, 'cancel')
        self.book.act(key, 8, 'cancel', admin=True)
        with self.assertRaises(ValueError):
            self.book.act(key, 4, 'join')

    def test_edit_keeps_rsvps_and_rejects_overfill(self):
        key = self.create()
        self.book.act(key, 4, 'join')
        p = self.book.get(key)
        changes = {k: p[k] for k in ['game', 'mode', 'start', 'party', 'capacity']}
        changes.update(mode='Rush', capacity=5)
        self.book.act(key, 3, 'edit', changes=changes)
        self.book.act(key, 5, 'join')
        changes['capacity'] = 4
        with self.assertRaises(ValueError):
            self.book.act(key, 3, 'edit', changes=changes)
        self.assertEqual(self.book.get(key)['members'], [4, 5])

    def test_expiry_survives_restart_and_marks_card_dirty(self):
        key = self.create()
        self.clock += 3601
        self.book = PlanBook(self.path, lambda: self.clock)
        with self.assertRaises(ValueError):
            self.book.act(key, 4, 'join')
        self.book.expire()
        self.assertEqual(self.book.get(key)['status'], 'started')
        self.assertTrue(self.book.get(key)['dirty'])

    def test_ambiguous_post_is_not_published_or_replayed(self):
        p = self.book.create(guild=1, channel=2, owner=3, game='FC', mode='',
                             start=self.clock + 3600, party=1, capacity=None)
        restarted = PlanBook(self.path, lambda: self.clock)
        self.assertEqual(restarted.get(p['id'])['status'], 'posting')
        self.assertIsNone(restarted.get(p['id'])['message'])
        with self.assertRaises(ValueError):
            restarted.act(p['id'], 4, 'join')

    def test_storage_failure_does_not_accept_a_phantom_rsvp(self):
        key = self.create()
        with patch('features.squad_plans.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.book.act(key, 4, 'join')
        self.assertEqual(self.book.get(key)['members'], [])

    def test_limit_active_plans(self):
        for _ in range(3):
            self.create()
        with self.assertRaises(ValueError):
            self.create()


if __name__ == '__main__':
    unittest.main()
