from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.sqlite_storage import SQLITE_BUSY_TIMEOUT_MS, connect_sqlite
from data.drink_data import DrinkEntry
from features import drink_storage


class DrinkStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = drink_storage.DATA_DIR
        self.old_stats_db = drink_storage.STATS_DB
        drink_storage.DATA_DIR = Path(self.temp_dir.name)
        drink_storage.STATS_DB = drink_storage.DATA_DIR / "community_stats.sqlite3"
        self.drink = DrinkEntry(
            eng="Test Drink",
            zh="測試飲品",
            desc="test",
            typ="short",
            rarity="Rare",
        )

    def tearDown(self) -> None:
        drink_storage.DATA_DIR = self.old_data_dir
        drink_storage.STATS_DB = self.old_stats_db
        self.temp_dir.cleanup()

    def test_records_and_counts_self_drink(self) -> None:
        drink_storage.record_drink_event(
            guild_id=10,
            event_type=drink_storage.EVENT_SELF_DRINK,
            actor_id=20,
            target_id=20,
            drink=self.drink,
        )

        self.assertEqual(drink_storage.count_self_drinks(10, 20), 1)
        self.assertEqual(drink_storage.count_self_unique_drinks(10, 20), 1)
        self.assertEqual(drink_storage.count_self_drinks(99, 20), 0)

    def test_gift_statistics_and_collection_are_consistent(self) -> None:
        for _ in range(2):
            drink_storage.record_drink_event(
                guild_id=10,
                event_type=drink_storage.EVENT_GIFT_DRINK,
                actor_id=20,
                target_id=30,
                drink=self.drink,
            )

        self.assertEqual(drink_storage.count_given_drinks(10, 20), 2)
        self.assertEqual(drink_storage.count_received_drinks(10, 30), 2)
        self.assertEqual(drink_storage.top_given_target(10, 20), (30, 2))

        rows = drink_storage.fetch_collection_rows(10, 30)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["drink_eng"], "Test Drink")
        self.assertEqual(rows[0]["received_count"], 2)

    def test_database_uses_wal_and_busy_timeout(self) -> None:
        drink_storage.init_drink_events_db()

        with connect_sqlite(drink_storage.STATS_DB) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

        self.assertEqual(journal_mode, "wal")
        self.assertEqual(busy_timeout, SQLITE_BUSY_TIMEOUT_MS)

    def test_record_failure_is_logged_without_breaking_drink_flow(self) -> None:
        with patch("features.drink_storage.connect_sqlite", side_effect=OSError("unavailable")):
            with self.assertLogs("con9sole-bartender.drink.storage", level="ERROR"):
                result = drink_storage.record_drink_event(
                    guild_id=10,
                    event_type=drink_storage.EVENT_SELF_DRINK,
                    actor_id=20,
                    target_id=20,
                    drink=self.drink,
                )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
