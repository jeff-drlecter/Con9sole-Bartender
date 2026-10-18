from __future__ import annotations

import discord

from core.safe_send import send_or_followup


async def require_public_send(interaction: discord.Interaction) -> bool:
    """Do not use the bot to post into channels the requesting member cannot use."""
    if interaction.guild is None or interaction.channel is None:
        await send_or_followup(
            interaction, content="請喺伺服器文字頻道內使用。", ephemeral=True
        )
        return False
    permissions = interaction.permissions
    can_send = (
        permissions.send_messages_in_threads
        if isinstance(interaction.channel, discord.Thread)
        else permissions.send_messages
    )
    if not permissions.view_channel or not can_send:
        await send_or_followup(
            interaction,
            content="你未有喺呢度發言嘅權限，請換一個可以聊天嘅頻道。",
            ephemeral=True,
        )
        return False
    return True
