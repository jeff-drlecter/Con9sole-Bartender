import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.sqlite_storage import connect_sqlite


class ConnectionLifecycleTests(unittest.TestCase):
    def test_context_commits_and_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "db.sqlite3"
            with connect_sqlite(path) as conn:
                conn.execute("CREATE TABLE items (value INTEGER)")
                conn.execute("INSERT INTO items VALUES (1)")
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
            with connect_sqlite(path) as fresh:
                self.assertEqual(
                    fresh.execute("SELECT value FROM items").fetchall(), [(1,)]
                )

    def test_context_rolls_back_and_closes_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "db.sqlite3"
            with connect_sqlite(path) as conn:
                conn.execute("CREATE TABLE items (value INTEGER)")
            with self.assertRaises(RuntimeError):
                with connect_sqlite(path) as conn:
                    conn.execute("INSERT INTO items VALUES (1)")
                    raise RuntimeError("fail")
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
            with connect_sqlite(path) as fresh:
                self.assertEqual(fresh.execute("SELECT * FROM items").fetchall(), [])
