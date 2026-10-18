import unittest

import discord

from core.ui import report_ui_error
from quick_bar_fakes import interaction


class UIErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_new_response_is_completed_without_exposing_error(self):
        i = interaction()
        i.response.type = discord.InteractionResponseType.deferred_channel_message
        with self.assertLogs("con9sole-bartender.ui", level="ERROR"):
            await report_ui_error(i, RuntimeError("private diagnostic detail"))
        payload = i.edit_original_response.await_args.kwargs
        self.assertNotIn("private diagnostic", payload["content"])

    async def test_deferred_card_update_does_not_overwrite_public_card(self):
        i = interaction()
        i.response.is_done.return_value = True
        i.response.type = discord.InteractionResponseType.deferred_message_update
        with self.assertLogs("con9sole-bartender.ui", level="ERROR"):
            await report_ui_error(i, RuntimeError("failure"))
        i.edit_original_response.assert_not_awaited()
        self.assertTrue(i.followup.send.await_args.kwargs["ephemeral"])
