from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.config_validation import REQUIRED_POSITIVE_INT_SETTINGS, validate_config


def valid_settings() -> SimpleNamespace:
    values = {name: index + 1 for index, name in enumerate(REQUIRED_POSITIVE_INT_SETTINGS)}
    values["HELPER_ROLE_IDS"] = [100, 200]
    return SimpleNamespace(**values)


class ConfigValidationTests(unittest.TestCase):
    def test_valid_settings_have_no_warnings(self) -> None:
        self.assertEqual(validate_config(valid_settings()), [])

    def test_missing_and_non_positive_ids_are_reported(self) -> None:
        settings = valid_settings()
        settings.GUILD_ID = 0
        del settings.LOG_CHANNEL_ID

        warnings = validate_config(settings)

        self.assertTrue(any("GUILD_ID" in warning for warning in warnings))
        self.assertTrue(any("LOG_CHANNEL_ID" in warning for warning in warnings))

    def test_boolean_is_not_accepted_as_discord_id(self) -> None:
        settings = valid_settings()
        settings.VERIFIED_ROLE_ID = True

        self.assertTrue(any("VERIFIED_ROLE_ID" in warning for warning in validate_config(settings)))

    def test_invalid_helper_role_collection_is_reported(self) -> None:
        settings = valid_settings()
        settings.HELPER_ROLE_IDS = [100, "bad"]

        self.assertTrue(any("HELPER_ROLE_IDS" in warning for warning in validate_config(settings)))


if __name__ == "__main__":
    unittest.main()
