from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.storage_paths import resolve_data_dir


class StoragePathTests(unittest.TestCase):
    def test_existing_configured_directory_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = Path(temp_dir)

            self.assertEqual(resolve_data_dir(str(configured)), configured)

    def test_missing_configured_directory_uses_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback = Path(temp_dir)
            missing = fallback / "missing"

            self.assertEqual(resolve_data_dir(str(missing), fallback=fallback), fallback)


if __name__ == "__main__":
    unittest.main()
