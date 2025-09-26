from __future__ import annotations
import os
import asyncio
import logging
import pathlib
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
        # 自動載入 cogs：只掃真 .py，避免 .py.old / .bak
        import cogs  # 以已安裝 package 取目錄，避免 cwd 不同

        cogs_dir = pathlib.Path(cogs.__file__).parent
        loaded: list[str] = []

        if not cogs_dir.exists():
            log.warning("cogs directory not found at %s", cogs_dir)
        else:
            for fn in os.listdir(cogs_dir):
                if not fn.endswith(".py"):
                    continue
                if fn.startswith("_"):
                    continue
                stem = fn[:-3]  # 去掉 .py
                # 防止 message_audit.py.old 這類帶點號的檔名被誤讀
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

        # Slash 指令同步（guild-scoped 較快）
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

# ---------- Token loader（支援多種變數名與 config） ----------

def _get_token() -> str:
    """Return Discord bot token from env or config using flexible keys.

    Priority: env(DISCORD_TOKEN) -> env(DISCORD_BOT_TOKEN) ->
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
    bot.add_command(ping)

    token = _get_token()
    if not token:
        raise RuntimeError("DISCORD_TOKEN/DISCORD_BOT_TOKEN not set in env or config")

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
