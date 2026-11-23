import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import discord
from discord import app_commands

from core.command_sync import CommandSync


class CommandSyncTests(unittest.IsolatedAsyncioTestCase):
    guild = discord.Object(id=22)

    def setUp(self):
        self.data = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def worker(self, app_id=11):
        client = discord.Client(intents=discord.Intents.none(), application_id=app_id)
        tree = app_commands.CommandTree(client)
        http = client.http
        http.bulk_upsert_guild_commands = AsyncMock(return_value=[])
        http.bulk_upsert_global_commands = AsyncMock(return_value=[])
        return CommandSync(tree, self.data), http

    def command(self, worker, name="game"):
        @worker.tree.command(name=name, guild=self.guild, description="Pick a game")
        async def play(interaction: discord.Interaction, game: str):
            pass

        return play

    async def test_restart_skips_same_registry_and_resyncs_only_changed_scope(self):
        first, http = self.worker()
        self.command(first)
        self.command(first, "menu")
        await first.sync()
        await first.sync(guild=self.guild)
        http.bulk_upsert_global_commands.assert_awaited_once_with(11, payload=[])
        self.assertEqual(len(http.bulk_upsert_guild_commands.await_args.kwargs["payload"]), 2)

        restarted, http = self.worker()
        self.command(restarted, "menu")
        cmd = self.command(restarted)
        await restarted.sync()
        await restarted.sync(guild=self.guild)
        http.bulk_upsert_global_commands.assert_not_awaited()
        http.bulk_upsert_guild_commands.assert_not_awaited()

        cmd.default_permissions = discord.Permissions(manage_guild=True)
        await restarted.sync(guild=self.guild)
        app_commands.describe(game="Choose from the list")(cmd)
        await restarted.sync(guild=self.guild)
        restarted.tree.remove_command("game", guild=self.guild)
        await restarted.sync(guild=self.guild)
        self.assertEqual(http.bulk_upsert_guild_commands.await_count, 3)
        self.assertEqual([c["name"] for c in http.bulk_upsert_guild_commands.await_args.kwargs["payload"]], ["menu"])
        http.bulk_upsert_global_commands.assert_not_awaited()

    async def test_failed_update_cannot_hide_rollback_or_retry(self):
        worker, http = self.worker()
        await worker.sync(guild=self.guild)
        self.command(worker)
        http.bulk_upsert_guild_commands.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await worker.sync(guild=self.guild)

        rolled_back, http = self.worker()
        await rolled_back.sync(guild=self.guild)
        http.bulk_upsert_guild_commands.assert_awaited_once_with(11, 22, payload=[])
        http.bulk_upsert_guild_commands.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await rolled_back.sync(guild=self.guild, force=True)
        http.bulk_upsert_guild_commands.side_effect = None
        await rolled_back.sync(guild=self.guild)
        self.assertEqual(http.bulk_upsert_guild_commands.await_count, 3)

    async def test_separate_applications_guilds_and_overlapping_calls(self):
        worker, http = self.worker()
        entered, release = asyncio.Event(), asyncio.Event()

        async def wait_for_discord(*args, **kwargs):
            entered.set()
            await release.wait()
            return []

        http.bulk_upsert_guild_commands.side_effect = wait_for_discord
        first = asyncio.create_task(worker.sync(guild=self.guild))
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = asyncio.create_task(worker.sync(guild=self.guild))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        http.bulk_upsert_guild_commands.assert_awaited_once()
        await worker.sync(guild=discord.Object(id=33))
        http.bulk_upsert_guild_commands.assert_awaited_with(11, 33, payload=[])
        other_app, http = self.worker(app_id=44)
        await other_app.sync(guild=self.guild)
        http.bulk_upsert_guild_commands.assert_awaited_once_with(44, 22, payload=[])

    async def test_corrupt_or_unwritten_receipt_retries_on_next_start(self):
        worker, http = self.worker()
        await worker.sync()
        receipt, = self.data.glob("*.json")
        receipt.write_text("{")
        with (patch("core.command_sync.atomic_write_json", side_effect=OSError("full volume")),
              self.assertLogs("con9sole-bartender", level="ERROR")):
            await worker.sync()
        await worker.sync()
        await worker.sync()
        self.assertEqual(http.bulk_upsert_global_commands.await_count, 3)

    async def test_dynamic_translations_always_resync_and_invalidate_previous_receipt(self):
        worker, http = self.worker()
        await worker.sync()
        await worker.tree.set_translator(app_commands.Translator())
        await worker.sync()
        await worker.sync()
        await worker.tree.set_translator(None)
        await worker.sync()
        await worker.sync()
        self.assertEqual(http.bulk_upsert_global_commands.await_count, 4)
