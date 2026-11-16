from pathlib import Path
import tempfile
import unittest

from features.member_hints import HintStore, TIPS
from scripts.verify_member_hints import inspect
from types import SimpleNamespace


class HintsRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'member_hints.sqlite3'

    def test_missing_lazy_store_is_reported_without_creation(self):
        self.assertEqual(inspect(self.path, self.root, enabled=True)['store'], 'not_created_yet')
        self.assertFalse(self.path.exists())

    def test_real_store_is_checked_without_consuming_quota_or_editing_data(self):
        HintStore(self.path).reserve(1, 'private', 2, 3, list(TIPS), now=10000,
            rng=SimpleNamespace(random=lambda:0, choice=lambda tips:tips[0]))
        before = self.path.read_bytes()
        result = inspect(self.path, self.root, enabled=True)
        self.assertEqual(result['store'], 'integrity_checked_read_only')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('guild', result)

    def test_disabled_or_unbacked_path_fails_without_creating_files(self):
        for path, enabled in ((self.path, False), (self.root / 'other' / 'hints.db', True)):
            with self.assertRaises(ValueError):
                inspect(path, self.root, enabled=enabled)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_database_fails_without_repair(self):
        self.path.write_bytes(b'invalid')
        with self.assertRaises(Exception):
            inspect(self.path, self.root, enabled=True)
        self.assertEqual(self.path.read_bytes(), b'invalid')
