from __future__ import annotations
import os
import asyncio
import logging
import pkgutil
import importlib
import discord
from discord.ext import commands

import config

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("con9sole-bartender")

# ---------- Intents ----------
intents = discord.Intents.default()
intents.members = True           # 成員事件（join/leave/role/nick 更新）
intents.guilds = True
intents.messages = True
intents.message_content = False  # 如需讀取訊息文字可開
intents.voice_states = True      # 語音房事件

# ---------- Bot ----------
class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned_or("/"), intents=intents)

    async def setup_hook(self) -> None:
        # 自動載入 cogs 目錄下的所有 .py（排除 __init__ 及以下劃線開頭）
        loaded = []
        for modinfo in pkgutil.iter_modules(["cogs"]):
            name = modinfo.name
            if name.startswith("_"):
                continue
            full = f"cogs.{name}"
            try:
                await self.load_extension(full)
                loaded.append(full)
                log.info("Loaded extension: %s", full)
            except Exception as e:  # 不阻斷啟動，寫 log 方便排查
                log.exception("Failed loading %s: %r", full, e)
        if not loaded:
            log.warning("No cogs loaded from ./cogs")

        # Slash 指令同步（guild-scoped 較快；沒設置則全域）
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

# ---------- 健康檢查指令 ----------
@commands.hybrid_command(name="ping", description="Test bot latency")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply(f"Pong! {round(ctx.bot.latency * 1000)}ms")

# ---------- Main ----------
async def main() -> None:
    bot = Bot()
    bot.add_command(ping)
    token = os.getenv("DISCORD_TOKEN", getattr(config, "DISCORD_TOKEN", ""))
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set in env or config")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
