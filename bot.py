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

    async def on_message(self, message: discord.Message) -> None:
        """全局 fallback：純 tag bot 時叫出 Menu。

        放喺 bot.py 主 Bot class，比單靠 Cog listener 更穩陣。
        注意：最後一定要 process_commands，避免影響 prefix / hybrid commands。
        """
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

            # 只接受純 tag bot，例如：@Con9sole-Bartender
            # 避免「@Bot hello」呢類普通對話都彈 Menu。
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

                # 後備方案：如果 menu.py 未有 send_mention_menu，都盡量直接用現有 helper 出 Menu。
                try:
                    import cogs.menu as menu_module

                    await message.reply(
                        embed=menu_module.build_main_menu_embed(message.author),
                        view=menu_module.MainMenuView(menu_cog) if menu_cog else None,
                        file=menu_module.build_menu_file(),
                        mention_author=False,
                    )
                    return
                except Exception:
                    log.exception("Failed to send mention menu fallback")

        await self.process_commands(message)


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
