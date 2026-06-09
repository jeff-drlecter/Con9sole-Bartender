from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.safe_send import send_or_followup
from features.daily_bar import (
    build_daily_bar_embed,
    get_daily_bar_completion,
    get_daily_bar_task,
)


TASK_ACTIONS: dict[str, tuple[str, str]] = {
    "drink": ("Drink", "menu_entry"),
    "drink_gift": ("Drink", "gift_drink_entry"),
    "cheers": ("Cheers", "menu_entry"),
    "cheers_target": ("Cheers", "cheer_for_member_entry"),
    "drink_collection": ("Drink", "collection_entry"),
}


class DailyBarActionButton(discord.ui.Button):
    def __init__(self, *, task_key: str, emoji: str, completed: bool) -> None:
        super().__init__(
            label="已完成" if completed else "去做任務",
            emoji="✅" if completed else emoji,
            style=discord.ButtonStyle.success if completed else discord.ButtonStyle.primary,
            disabled=completed,
            custom_id=f"bartender:daily_bar:action:{task_key}",
        )
        self.task_key = task_key

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.task_key not in TASK_ACTIONS:
            await interaction.response.send_message("❌ 呢個每日任務暫時未設定動作。", ephemeral=True)
            return

        cog_name, method_name = TASK_ACTIONS[self.task_key]
        target = interaction.client.get_cog(cog_name)
        if target is None:
            await interaction.response.send_message(f"❌ `{cog_name}` 功能未載入。", ephemeral=True)
            return

        method = getattr(target, method_name, None)
        if method is None or not callable(method):
            await interaction.response.send_message(f"❌ `{cog_name}` 未提供 `{method_name}` 入口。", ephemeral=True)
            return

        await method(interaction)


class DailyBarView(discord.ui.View):
    def __init__(self, *, guild_id: int | None, user_id: int) -> None:
        super().__init__(timeout=180)
        task = get_daily_bar_task(guild_id)
        completed = get_daily_bar_completion(guild_id, user_id) is not None
        self.add_item(DailyBarActionButton(task_key=task.key, emoji=task.emoji, completed=completed))


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

    async def _send_daily_bar(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction)
        embed = build_daily_bar_embed(interaction.guild_id, user=interaction.user)
        view = DailyBarView(guild_id=interaction.guild_id, user_id=interaction.user.id)
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self._send_daily_bar(interaction)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="daily_bar", description="View today's bar task")
    async def daily_bar(self, interaction: discord.Interaction) -> None:
        await self._send_daily_bar(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyBar(bot))
