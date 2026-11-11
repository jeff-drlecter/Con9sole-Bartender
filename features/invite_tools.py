from __future__ import annotations
from collections.abc import Callable
import discord
from core.safe_send import send_or_followup


async def create_invite_link_from_button(
    interaction: discord.Interaction,
    *,
    can_use_admin_func: Callable[[discord.Member | discord.User], bool],
) -> None:
    cog = interaction.client.get_cog("Invites")
    if cog is None:
        await send_or_followup(interaction, content="邀請功能暫時未準備好，請稍後再試。", ephemeral=True)
        return
    await cog.menu_entry(interaction)
