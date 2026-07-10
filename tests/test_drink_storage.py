from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
