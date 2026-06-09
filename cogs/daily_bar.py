from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.safe_send import send_or_followup
from features.daily_bar import build_daily_bar_embed


class DailyBar(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _record_usage(self, interaction: discord.Interaction) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage("daily_bar", interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction)
        embed = build_daily_bar_embed(interaction.guild_id, user=interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="daily_bar", description="View today's bar task")
    async def daily_bar(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction)
        embed = build_daily_bar_embed(interaction.guild_id, user=interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyBar(bot))
