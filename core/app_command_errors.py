from __future__ import annotations

import logging

import discord
from discord import app_commands

from core.safe_send import send_or_followup


log = logging.getLogger("con9sole-bartender.app-commands")


def _user_message(error: app_commands.AppCommandError) -> str:
    if isinstance(error, app_commands.CommandOnCooldown):
        retry_after = max(1, round(error.retry_after))
        return f"⏳ 呢個指令冷卻中，請等約 `{retry_after}` 秒後再試。"

    if isinstance(error, app_commands.BotMissingPermissions):
        return "❌ Bot 權限不足，暫時無法完成呢個操作。請通知管理員檢查 Bot 角色權限。"

    if isinstance(error, app_commands.MissingPermissions):
        return "❌ 你冇足夠權限使用呢個指令。"

    if isinstance(error, app_commands.TransformerError):
        return "❌ 指令參數格式唔正確，請檢查輸入後再試。"

    if isinstance(error, app_commands.CheckFailure):
        return "❌ 你目前唔符合使用呢個指令嘅條件。"

    return "⚠️ 指令執行時發生問題，請稍後再試；如持續出現，請通知管理員。"


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Log slash-command failures and send a safe, useful user response."""
    original = getattr(error, "original", error)
    command_name = interaction.command.qualified_name if interaction.command else "unknown"

    if isinstance(
        error,
        (
            app_commands.CommandOnCooldown,
            app_commands.BotMissingPermissions,
            app_commands.MissingPermissions,
            app_commands.TransformerError,
            app_commands.CheckFailure,
        ),
    ):
        log.info(
            "App command rejected: command=%s user=%s guild=%s error=%s",
            command_name,
            interaction.user.id,
            interaction.guild_id,
            type(error).__name__,
        )
    else:
        log.error(
            "App command failed: command=%s user=%s guild=%s",
            command_name,
            interaction.user.id,
            interaction.guild_id,
            exc_info=(type(original), original, original.__traceback__),
        )

    try:
        await send_or_followup(
            interaction,
            content=_user_message(error),
            ephemeral=True,
        )
    except (discord.NotFound, discord.Forbidden):
        log.warning(
            "Could not respond to failed interaction: command=%s interaction=%s",
            command_name,
            interaction.id,
        )
    except discord.HTTPException:
        log.exception(
            "Discord API rejected error response: command=%s interaction=%s",
            command_name,
            interaction.id,
        )
