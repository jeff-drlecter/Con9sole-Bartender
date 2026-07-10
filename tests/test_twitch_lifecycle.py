from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock

try:
    import twitchio  # noqa: F401
except ModuleNotFoundError:
    twitchio_module = types.ModuleType("twitchio")
    twitchio_ext_module = types.ModuleType("twitchio.ext")
    twitchio_commands_module = types.ModuleType("twitchio.ext.commands")
    twitchio_commands_module.Bot = type("Bot", (), {})
    twitchio_ext_module.commands = twitchio_commands_module
    twitchio_module.ext = twitchio_ext_module
    sys.modules["twitchio"] = twitchio_module
    sys.modules["twitchio.ext"] = twitchio_ext_module
    sys.modules["twitchio.ext.commands"] = twitchio_commands_module

from cogs.twitch_relay import TwitchRelay


class TwitchLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cog_unload_closes_client_and_cancels_connect_task(self) -> None:
        relay = object.__new__(TwitchRelay)
        relay.twitch_bot = AsyncMock()
        relay._connect_task = asyncio.create_task(asyncio.sleep(60))
        connect_task = relay._connect_task
        twitch_bot = relay.twitch_bot

        await relay.cog_unload()

        twitch_bot.close.assert_awaited_once()
        self.assertTrue(connect_task.cancelled())
        self.assertIsNone(relay.twitch_bot)
        self.assertIsNone(relay._connect_task)


if __name__ == "__main__":
    unittest.main()
