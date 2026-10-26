"""Offline integration: real extension load/reload and command/view registration.

Discord sync is mocked; all tokens are removed in a fresh subprocess. No bot login.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OfflineLifecycleTests(unittest.TestCase):
    def test_all_extensions_routes_and_ready_reload(self):
        script = """
import asyncio, json
from unittest.mock import AsyncMock
import discord
from bot import Bot
from data.menu_registry import MENU_ITEMS_BY_LAYER

async def run():
    bot = Bot()
    async with bot:
        bot.tree.sync = AsyncMock(return_value=[])
        await bot.setup_hook()
        missing = []
        for items in MENU_ITEMS_BY_LAYER.values():
            for item in items:
                cog = bot.get_cog(item.cog)
                if cog is None or not callable(getattr(cog, item.method, None)):
                    missing.append(item.id)
        bot._ready.set()
        await asyncio.sleep(0)
        before = bot.get_cog("TempVC")._sweeper_task
        await bot.reload_extension("cogs.tempvc")
        await asyncio.sleep(0)
        after = bot.get_cog("TempVC")._sweeper_task
        await bot.reload_extension("cogs.menu")
        await bot.reload_extension("cogs.teams")
        print(json.dumps({"extensions": len(bot.extensions), "missing": missing,
            "sweeper_restarted": before is not None and after is not None and before is not after,
            "command_count": len(bot.tree.get_commands(guild=discord.Object(626378673523785731))) }))
        for name in list(bot.extensions):
            await bot.unload_extension(name)
asyncio.run(run())
"""
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ)
            for name in (
                "DISCORD_TOKEN",
                "DISCORD_BOT_TOKEN",
                "TWITCH_BOT_OAUTH",
                "TWITCH_BOT_USERNAME",
            ):
                env.pop(name, None)
            env.update(
                {
                    "DRINK_DATA_DIR": folder,
                    "STATS_DB_PATH": str(Path(folder) / "stats.sqlite3"),
                    "DRINK_STATE_PATH": str(Path(folder) / "drinks.json"),
                    "ACTIVITY_REMINDER_PATH": str(Path(folder) / "activity.json"),
                    "GAME_ANNOUNCEMENTS_PATH": str(Path(folder) / "games.json"),
                    "SQUAD_CARDS_PATH": str(Path(folder) / "squads.json"),
                    "TWITCH_RELAY_CONFIG": "[]",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(report["extensions"], 18, result.stderr)
        self.assertEqual(report["missing"], [])
        self.assertTrue(report["sweeper_restarted"])
        self.assertEqual(report["command_count"], 26)
