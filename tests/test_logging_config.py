from __future__ import annotations

import logging
import unittest

from core.logging_config import resolve_log_level


class LoggingConfigTests(unittest.TestCase):
    def test_known_level_is_resolved_case_insensitively(self) -> None:
        self.assertEqual(resolve_log_level("debug"), logging.DEBUG)

    def test_blank_level_uses_info(self) -> None:
        self.assertEqual(resolve_log_level(""), logging.INFO)

    def test_unknown_level_uses_info(self) -> None:
        self.assertEqual(resolve_log_level("verbose"), logging.INFO)


if __name__ == "__main__":
    unittest.main()
