import asyncio
import hashlib
import json
import logging
from pathlib import Path

import discord
from discord import app_commands

from core.json_storage import atomic_write_json, load_json_object

log = logging.getLogger("con9sole-bartender.command-sync")


class CommandSync:
    """Track successful Discord bulk overwrites for this single-writer bot."""

    def __init__(self, tree: app_commands.CommandTree, data_dir: Path):
        self.tree = tree
        self.data_dir = data_dir
        self.lock = asyncio.Lock()

    async def sync(self, *, guild: discord.Object | None = None, force: bool = False) -> None:
        async with self.lock:
            app_id = self.tree.client.application_id
            if app_id is None:
                await self.tree.sync(guild=guild)
                return

            scope = guild.id if guild else "global"
            receipt = self.data_dir / f"command-sync-v1-{app_id}-{scope}.json"
            digest = None
            # A translator can supply different strings on each invocation.
            if self.tree.translator is None:
                payload = [cmd.to_dict(self.tree) for cmd in self.tree.get_commands(guild=guild)]
                payload.sort(key=lambda cmd: (cmd["type"], cmd["name"]))
                encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                digest = hashlib.sha256(encoded).hexdigest()

            if digest is not None and not force:
                try:
                    previous = load_json_object(receipt, dict)
                except OSError:
                    previous = {}
                if previous.get("sha256") == digest:
                    log.info("App commands unchanged; skipped sync scope=%s", scope)
                    return

            # Discord may apply a request even if the response never arrives.
            # Invalidate first so retries and rollbacks cannot trust the old receipt.
            receipt.unlink(missing_ok=True)
            await self.tree.sync(guild=guild)
            log.info("App commands synced scope=%s", scope)
            if digest is not None:
                try:
                    atomic_write_json(receipt, {"sha256": digest})
                except OSError:
                    log.exception("Could not save command sync receipt scope=%s; will retry", scope)
