from __future__ import annotations

import unittest

from discord import app_commands

from core.app_command_errors import _user_message


class AppCommandErrorMessageTests(unittest.TestCase):
    def test_cooldown_message_includes_rounded_wait(self) -> None:
        cooldown = app_commands.Cooldown(1, 30.0)
        error = app_commands.CommandOnCooldown(cooldown, retry_after=4.6)

        self.assertIn("`5` 秒", _user_message(error))

    def test_missing_user_permissions_has_specific_message(self) -> None:
        error = app_commands.MissingPermissions(["manage_guild"])

        self.assertIn("你冇足夠權限", _user_message(error))

    def test_missing_bot_permissions_has_specific_message(self) -> None:
        error = app_commands.BotMissingPermissions(["manage_channels"])

        self.assertIn("Bot 權限不足", _user_message(error))

    def test_unexpected_error_does_not_expose_details(self) -> None:
        error = app_commands.AppCommandError("sensitive internal detail")
        message = _user_message(error)

        self.assertNotIn("sensitive internal detail", message)
        self.assertIn("請稍後再試", message)


if __name__ == "__main__":
    unittest.main()
