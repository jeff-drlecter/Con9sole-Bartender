"""Independent migration audit: continuity and recovery failure boundaries."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.sqlite_storage import connect_sqlite
from features.community_levels import Ledger, threshold
from features.level_migration import apply_snapshot, create_backup, restore_backup, role_restore_plan, validate_snapshot


class MigrationAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / 'live.sqlite3')
        self.ledger.configure(1, mode='off')
        self.snapshot = dict(schema=1, source='amari', guild_id='1',
            captured_at='2026-11-06T15:00:00Z', cutover_at='2026-11-06T15:00:00Z',
            source_frozen_at='2026-11-06T15:00:00Z',
            weekly_period='Frozen Amari manual counter; historical start unknown',
            users=[dict(user_id='10', total_xp=threshold(15)+7, level=15,
                        level_xp=7, weekly_xp=9999),
                   dict(user_id='11', total_xp=0, level=0, level_xp=0, weekly_xp=0)])
        self.kwargs = dict(guild=1, roster_ids=[10, 11], expected_count=2,
                           backup_path=self.root / 'before.sqlite3')
        self.cutover = validate_snapshot(self.snapshot, guild=1,
                                         roster_ids=[10, 11], expected_count=2)['cutover']

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self):
        self.ledger.configure(1, mode='off')
        return apply_snapshot(self.ledger, self.snapshot, **self.kwargs, commit=True)

    def test_import_preserves_last_shared_activity_cooldown(self):
        self.ledger.configure(1, mode='preview')
        self.ledger.award(1, 10, 'activity', 'post', self.cutover+120)
        self.apply()
        self.ledger.configure(1, mode='preview')
        self.assertIsNone(self.ledger.award(1, 10, 'text', 'too-soon', self.cutover+121))
        self.assertIsNotNone(self.ledger.award(1, 10, 'text', 'later', self.cutover+180))

    def test_import_preserves_same_day_activity_cap(self):
        self.ledger.configure(1, mode='preview', activity_daily_cap=1)
        self.ledger.award(1, 10, 'activity', 'post', self.cutover+120)
        self.apply()
        self.ledger.configure(1, mode='preview')
        self.assertIsNone(self.ledger.award(1, 10, 'activity', 'over-cap', self.cutover+240))
        self.assertIsNotNone(self.ledger.award(1, 10, 'activity', 'tomorrow', self.cutover+86400))

    def test_post_cutover_adjustment_is_never_silently_lost(self):
        self.ledger.configure(1, mode='preview')
        self.ledger.award(1, 10, 'text', 'post', self.cutover+120)
        self.ledger.adjust(1, 10, 99, 100, 'confirmed post-cutover correction', self.cutover+180)
        self.ledger.configure(1, mode='off')
        original = self.ledger.profile(1, 10)['total']
        try:
            self.apply()
        except ValueError:
            # Requiring a reviewed adjustment policy is safer than discarding the correction.
            self.assertEqual(self.ledger.profile(1, 10)['total'], original)
        else:
            self.assertEqual(self.ledger.profile(1, 10)['total'], threshold(15)+7+1+100)

    def test_incompatible_same_named_schema_cannot_replace_live(self):
        self.ledger.adjust(1, 10, 99, 123, 'initial', self.cutover-1)
        backup = self.root / 'malformed.sqlite3'
        create_backup(self.ledger, backup)
        with connect_sqlite(backup) as db:
            db.execute('ALTER TABLE xp DROP COLUMN text')
        sha = hashlib.sha256(backup.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            restore_backup(self.ledger, backup, expected_sha=sha, guild=1,
                           checkpoint_path=self.root/'must-not-touch.sqlite3')
        self.assertEqual(self.ledger.profile(1, 10)['total'], 123)

    def test_independent_manifest_cannot_be_replaced_by_snapshot_subset(self):
        partial = copy.deepcopy(self.snapshot)
        partial['users'] = partial['users'][:1]
        partial['expected_user_ids'] = ['10']
        with self.assertRaises(ValueError):
            validate_snapshot(partial, guild=1, roster_ids=[10, 11], expected_count=2)

    def test_role_restore_normalizes_user_ids_before_diffing(self):
        result = role_restore_plan({'10': [50]}, {10: [150, 999]}, [50, 150])
        self.assertEqual(result, [dict(user_id=10, add=[50], remove=[150])])

    def test_role_restore_rejects_duplicate_normalized_member_ids(self):
        with self.assertRaises(ValueError):
            role_restore_plan({'10': [50], 10: [150]}, {}, [50, 150])

    def test_import_does_not_erase_other_guild_data(self):
        self.ledger.configure(2, mode='preview')
        self.ledger.award(2, 99, 'text', 'other-server', self.cutover+1)
        self.apply()
        self.assertEqual(self.ledger.profile(2, 99)['total'], 1)
        self.assertEqual(self.ledger.settings(2)['mode'], 'preview')

    def test_backup_wal_overlay_cannot_bypass_verified_checksum(self):
        self.ledger.adjust(1, 10, 99, 123, 'initial', self.cutover-1)
        backup = self.root/'overlay.sqlite3'
        sha = create_backup(self.ledger, backup)
        connection = sqlite3.connect(backup)
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('UPDATE xp SET total=999 WHERE guild=1 AND user=10')
            connection.commit()
            # The original bug hashed only the main file, then restored unverified WAL content.
            with self.assertRaises(ValueError):
                restore_backup(self.ledger, backup, expected_sha=sha, guild=1,
                               checkpoint_path=self.root/'overlay-checkpoint.sqlite3')
            self.assertEqual(self.ledger.profile(1, 10)['total'], 123)
        finally:
            connection.close()

    def test_restore_forces_off_even_if_backup_was_active(self):
        self.ledger.configure(1, mode='active')
        self.ledger.award(1, 10, 'text', 'before', self.cutover-1)
        backup = self.root/'active-backup.sqlite3'
        sha = create_backup(self.ledger, backup)
        self.ledger.configure(1, mode='off')
        self.ledger.adjust(1, 10, 99, 200, 'after', self.cutover+1)
        restore_backup(self.ledger, backup, expected_sha=sha, guild=1,
                       checkpoint_path=self.root/'checkpoint.sqlite3')
        self.assertEqual(self.ledger.settings(1)['mode'], 'off')
        self.assertEqual(self.ledger.profile(1, 10)['total'], 1)
        self.assertEqual(Ledger(self.root/'checkpoint.sqlite3').profile(1, 10)['total'], 201)


if __name__ == '__main__':
    unittest.main()
