from __future__ import annotations

import asyncio
import logging
import os
import pathlib

import discord
from discord.ext import commands

import config

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("con9sole-bartender")

# ---------- Intents ----------
intents = discord.Intents.default()
intents.members = True           # 成員事件：join / leave / role / nick 更新
intents.guilds = True
intents.messages = True
intents.voice_states = True      # 語音房事件
intents.message_content = True   # tag bot 出 menu / 讀 message content


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or("/"),
            intents=intents,
        )

    async def setup_hook(self) -> None:
        # 自動載入 cogs：只掃真 .py，避免 .py.old / .bak
        import cogs  # 以已安裝 package 取目錄，避免 cwd 不同

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

                stem = fn[:-3]  # 去掉 .py

                # 防止 message_audit.py.old / xxx.bak.py 呢類帶點號檔名被誤讀
                if "." in stem:
                    continue

                full = f"cogs.{stem}"
                try:
                    await self.load_extension(full)
                    loaded.append(full)
                    log.info("Loaded extension: %s", full)
                except Exception as e:
                    log.exception("Failed loading %s: %r", full, e)

        if not loaded:
            log.warning("No cogs loaded from %s", cogs_dir)

        # Slash 指令同步
        # 重要：清走舊 global commands，避免 bot.py 舊 /ping 或其他歷史 global command 留喺 Discord UI。
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Global app commands cleared")
        except Exception as e:
            log.exception("Global app command clear failed: %r", e)

        try:
            if getattr(config, "GUILD_ID", None):
                guild_obj = discord.Object(id=config.GUILD_ID)
                await self.tree.sync(guild=guild_obj)
                log.info("App commands synced to guild %s", config.GUILD_ID)
            else:
                await self.tree.sync()
                log.info("App commands synced globally")
        except Exception as e:
            log.exception("Slash command sync failed: %r", e)

    async def on_ready(self) -> None:
        log.info("✅ Logged in as %s (%s)", self.user, self.user and self.user.id)


# ---------- Token loader（支援多種變數名與 config） ----------
def _get_token() -> str:
    """Return Discord bot token from env or config using flexible keys.

    Priority:
    env(DISCORD_TOKEN) -> env(DISCORD_BOT_TOKEN) ->
    config.DISCORD_TOKEN -> config.DISCORD_BOT_TOKEN
    """
    return (
        os.getenv("DISCORD_TOKEN")
        or os.getenv("DISCORD_BOT_TOKEN")
        or getattr(config, "DISCORD_TOKEN", "")
        or getattr(config, "DISCORD_BOT_TOKEN", "")
    )


# ---------- Main ----------
async def main() -> None:
    bot = Bot()

    token = _get_token()
    if not token:
        raise RuntimeError("DISCORD_TOKEN/DISCORD_BOT_TOKEN not set in env or config")

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
