from __future__ import annotations

import asyncio
import logging
import os
import pathlib

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.app_command_errors import handle_app_command_error
from core.config_validation import validate_config
from core.logging_config import configure_logging

configure_logging()
log = logging.getLogger("con9sole-bartender")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.voice_states = True
intents.message_content = True


class Con9soleCommandTree(app_commands.CommandTree):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await handle_app_command_error(interaction, error)


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or("/"),
            intents=intents,
            tree_cls=Con9soleCommandTree,
        )

    async def setup_hook(self) -> None:
        for warning in validate_config():
            log.warning("Configuration issue: %s", warning)

        import cogs

        cogs_dir = pathlib.Path(cogs.__file__).parent
        loaded: list[str] = []

        if not cogs_dir.exists():
            log.warning("cogs directory not found at %s", cogs_dir)
        else:
            for fn in sorted(os.listdir(cogs_dir)):
                if not fn.endswith(".py"):
                    continue
                if fn.startswith("_"):
                    continue

                stem = fn[:-3]
                if "." in stem:
                    continue

                full = f"cogs.{stem}"
                try:
                    await self.load_extension(full)
                    loaded.append(full)
                    log.info("Loaded extension: %s", full)
                except Exception as exc:
                    log.exception("Failed loading %s: %r", full, exc)

        if not loaded:
            log.warning("No cogs loaded from %s", cogs_dir)

        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Global app commands cleared")
        except Exception as exc:
            log.exception("Global app command clear failed: %r", exc)

        try:
            if getattr(config, "GUILD_ID", None):
                guild_obj = discord.Object(id=config.GUILD_ID)
                await self.tree.sync(guild=guild_obj)
                log.info("App commands synced to guild %s", config.GUILD_ID)
            else:
                await self.tree.sync()
                log.info("App commands synced globally")
        except Exception as exc:
            log.exception("Slash command sync failed: %r", exc)

    async def on_ready(self) -> None:
        log.info("✅ Logged in as %s (%s)", self.user, self.user and self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.guild is None:
            await self.process_commands(message)
            return

        if self.user is None:
            await self.process_commands(message)
            return

        bot_was_mentioned = self.user in message.mentions

        if bot_was_mentioned:
            raw_content = (message.content or "").strip()
            mention_forms = {
                f"<@{self.user.id}>",
                f"<@!{self.user.id}>",
            }

            is_pure_mention = False
            if raw_content in mention_forms:
                is_pure_mention = True
            else:
                cleaned = raw_content
                for mention_text in mention_forms:
                    cleaned = cleaned.replace(mention_text, "")
                if cleaned.strip() == "":
                    is_pure_mention = True

            if is_pure_mention:
                menu_cog = self.get_cog("Menu")

                if menu_cog and hasattr(menu_cog, "send_mention_menu"):
                    try:
                        await menu_cog.send_mention_menu(message)
                        return
                    except Exception:
                        log.exception("Failed to send mention menu via Menu.send_mention_menu")

                try:
                    from features.menu_embeds import build_quick_bar_embed
                    from features.menu_helpers import build_menu_file
                    from features.menu_views import QuickBarView

                    kwargs: dict[str, object] = {
                        "embed": build_quick_bar_embed(message.author),
                        "mention_author": False,
                    }
                    if menu_cog is not None:
                        kwargs["view"] = QuickBarView(menu_cog)

                    menu_file = build_menu_file()
                    if menu_file is not None:
                        kwargs["file"] = menu_file

                    await message.reply(**kwargs)
                    return
                except Exception:
                    log.exception("Failed to send mention menu fallback")

        await self.process_commands(message)


def _get_token() -> str:
    return (
        os.getenv("DISCORD_TOKEN")
        or os.getenv("DISCORD_BOT_TOKEN")
        or getattr(config, "DISCORD_TOKEN", "")
        or getattr(config, "DISCORD_BOT_TOKEN", "")
    )


async def main() -> None:
    bot = Bot()

    token = _get_token()
    if not token:
        raise RuntimeError("DISCORD_TOKEN/DISCORD_BOT_TOKEN not set in env or config")

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
