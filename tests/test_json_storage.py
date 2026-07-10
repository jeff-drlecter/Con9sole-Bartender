from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.json_storage import atomic_write_json, load_json_object


class JsonStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "state.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_atomic_round_trip_preserves_unicode(self) -> None:
        expected = {"message": "廣東話", "items": [1, 2, 3]}

        atomic_write_json(self.path, expected)

        self.assertEqual(load_json_object(self.path, dict), expected)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), expected)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_missing_file_returns_fresh_default(self) -> None:
        first = load_json_object(self.path, lambda: {"items": []})
        first["items"].append("changed")

        second = load_json_object(self.path, lambda: {"items": []})

        self.assertEqual(second, {"items": []})

    def test_malformed_file_is_rotated_before_default_is_used(self) -> None:
        self.path.write_text("{not valid json", encoding="utf-8")

        with self.assertLogs("con9sole-bartender.storage.json", level="ERROR"):
            loaded = load_json_object(self.path, lambda: {"version": 2})

        self.assertEqual(loaded, {"version": 2})
        self.assertFalse(self.path.exists())
        backups = list(self.path.parent.glob("state.json.corrupt.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{not valid json")

    def test_non_object_root_is_rotated(self) -> None:
        self.path.write_text("[]", encoding="utf-8")

        with self.assertLogs("con9sole-bartender.storage.json", level="ERROR"):
            loaded = load_json_object(self.path, dict)

        self.assertEqual(loaded, {})
        self.assertEqual(len(list(self.path.parent.glob("state.json.corrupt.*"))), 1)


if __name__ == "__main__":
    unittest.main()
