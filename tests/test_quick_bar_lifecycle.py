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
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
import config
from bot import Bot
from data.menu_registry import MENU_ITEMS_BY_LAYER

async def run():
    bot = Bot()
    async with bot:
        bot._connection.application_id = 101
        bot.http.bulk_upsert_global_commands = AsyncMock(return_value=[])
        bot.http.bulk_upsert_guild_commands = AsyncMock(return_value=[])
        await bot.setup_hook()
        assert "cogs.gta_translation" in bot.extensions and bot.get_cog("GTATranslation") is None
        bot.http.bulk_upsert_global_commands.assert_awaited_once_with(101, payload=[])
        bot.http.bulk_upsert_guild_commands.assert_awaited_once()
        guild = discord.Object(config.GUILD_ID)
        assert len(bot.http.bulk_upsert_guild_commands.await_args.kwargs["payload"]) == len(bot.tree.get_commands(guild=guild))
        await bot.command_sync.sync(guild=guild)
        bot.http.bulk_upsert_guild_commands.assert_awaited_once()
        assert (await bot.get_cog("Reload")._sync_guild_commands()) == (True, "")
        assert bot.http.bulk_upsert_guild_commands.await_count == 2
        missing = []
        for items in MENU_ITEMS_BY_LAYER.values():
            for item in items:
                cog = bot.get_cog(item.cog)
                if cog is None or not callable(getattr(cog, item.method, None)):
                    missing.append(item.id)
        bot._ready.set()
        await asyncio.sleep(0)
        previous_alerts = bot.get_cog("StreamAlerts")
        previous_poll = previous_alerts.poll.get_task()
        # Discord retains a separate view for each posted /stream_panel message.
        from cogs.stream_alerts import StreamPanel
        posted_panel = StreamPanel()
        bot.add_view(posted_panel, message_id=202)
        await bot.reload_extension("cogs.stream_alerts")
        alerts = bot.get_cog("StreamAlerts")
        assert previous_poll.cancelled(), "old Twitch alerts poll survived reload"
        assert previous_alerts.session.closed, "old Twitch HTTP session survived reload"
        assert previous_alerts.panel_view.is_finished()
        assert alerts.poll.is_running() and not alerts.session.closed
        assert alerts.panel_view in bot.persistent_views
        alerts.menu_entry = AsyncMock()
        inter = SimpleNamespace(client=bot)
        await posted_panel.open.callback(inter)
        alerts.menu_entry.assert_awaited_once_with(inter)
        maintenance_before = bot.get_cog("Maintenance").poll.get_task()
        await bot.reload_extension("cogs.maintenance")
        maintenance_after = bot.get_cog("Maintenance").poll.get_task()
        before = bot.get_cog("TempVC")._sweeper_task
        await bot.reload_extension("cogs.tempvc")
        await asyncio.sleep(0)
        after = bot.get_cog("TempVC")._sweeper_task
        await bot.reload_extension("cogs.menu")
        await bot.reload_extension("cogs.teams")
        directory = bot.tree.get_command("community", guild=discord.Object(config.GUILD_ID))
        directory_before = directory
        await bot.reload_extension("cogs.community_directory")
        directory = bot.tree.get_command("community", guild=discord.Object(config.GUILD_ID))
        print(json.dumps({"extensions": len(bot.extensions), "missing": missing,\n            "community_commands": sorted(c.name for c in directory.commands),
            "revoke_verified": bot.tree.get_command("撤回會員驗證", guild=discord.Object(config.GUILD_ID)) is not None,
            "chinese_directory": bot.tree.get_command("公會", guild=discord.Object(config.GUILD_ID)) is not None,
            "community_reloaded": directory is not directory_before,
            "community_global": bot.tree.get_command("community") is not None,
            "plans_loaded": bot.get_cog("SquadPlans") is not None,
            "sweeper_restarted": before is not None and after is not None and before is not after,
            "maintenance_restarted": maintenance_before is not maintenance_after and maintenance_before.cancelling() > 0,
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
                "GTA_TRANSLATION_API_KEY",
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
                    "RSS_TRIAL_STOP": "1",
                    "HELPER_SANDBOX": "",
                    "RSS_DELIVERY_SOURCES": "",
                    "RSS_DIGEST_CONFIG": "",
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
        self.assertEqual(report["extensions"], 38, result.stderr)
        self.assertEqual(report["missing"], [])
        self.assertTrue(report["plans_loaded"])
        self.assertTrue(report["sweeper_restarted"])
        self.assertTrue(report["maintenance_restarted"])
        self.assertEqual(report["command_count"], 68)
        self.assertTrue(report["revoke_verified"])

        self.assertEqual(report["community_commands"], ["archive", "create", "edit", "list", "restore", "show"])
        self.assertTrue(report["community_reloaded"])
        self.assertTrue(report["chinese_directory"])
        self.assertFalse(report["community_global"])
