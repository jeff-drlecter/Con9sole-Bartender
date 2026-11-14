import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.backup_runtime import backup


class RuntimeBackupTests(unittest.TestCase):
    def test_live_wal_json_readback_restore_and_no_backup_recursion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'stats.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE receipts (id TEXT PRIMARY KEY)')
                db.execute("INSERT INTO receipts VALUES ('never-replay')")
                db.commit()
                (root / 'plans.json').write_text('{"reminders": [5]}')
                folder, manifest = backup(root, 'a' * 40, environ={})
                self.assertTrue(manifest['ready'])
                self.assertFalse(any(f['path'].endswith('-wal') for f in manifest['files']))
                with sqlite3.connect(folder / 'stores' / 'stats.sqlite3') as restored:
                    self.assertEqual(restored.execute('SELECT id FROM receipts').fetchall(), [('never-replay',)])
                self.assertEqual(json.loads((folder / 'stores' / 'plans.json').read_text()), {'reminders': [5]})
                _, second = backup(root, 'b' * 40, environ={})
                self.assertEqual(len(manifest['files']), len(second['files']))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], 1)

    def test_empty_invalid_json_external_override_or_symlink_cannot_be_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                backup(root, 'a' * 40, environ={})
            (root / 'plans.json').write_text('{bad')
            with self.assertRaises(RuntimeError):
                backup(root, 'a' * 40, environ={})
            self.assertFalse(list((root / 'release_backups').rglob('manifest.json')))
            with self.assertRaises(ValueError):
                backup(root, 'a' * 40, environ={'STATS_DB_PATH': '/outside/stats.sqlite3'})
            (root / 'plans.json').write_text('{}')
            (root / 'link').symlink_to(root / 'plans.json')
            with self.assertRaises(ValueError):
                backup(root, 'a' * 40, environ={})
