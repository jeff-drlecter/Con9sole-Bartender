from __future__ import annotations

import logging

import discord

from core.safe_send import send_or_followup

log = logging.getLogger("con9sole-bartender.ui")


async def report_ui_error(interaction: discord.Interaction, error: Exception) -> None:
    log.error(
        "Interaction failed: id=%s",
        interaction.id,
        exc_info=(type(error), error, error.__traceback__),
    )
    content = "暫時完成唔到呢個操作，請稍後再試；如持續出現，請通知管理員。"
    try:
        if (
            interaction.response.type
            == discord.InteractionResponseType.deferred_channel_message
        ):
            await interaction.edit_original_response(content=content)
        else:
            await send_or_followup(interaction, content=content, ephemeral=True)
    except discord.HTTPException:
        log.exception("Could not report UI failure: interaction=%s", interaction.id)


class SafeView(discord.ui.View):
    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await report_ui_error(interaction, error)


class SafeModal(discord.ui.Modal):
    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        await report_ui_error(interaction, error)
