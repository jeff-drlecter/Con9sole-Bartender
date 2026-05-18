from __future__ import annotations

import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config


CONFESSION_COLOR = 0x2B2D31
CONFESSION_COOLDOWN_SECONDS = 30.0

CONFESSION_CHANNEL_ID: Optional[int] = getattr(config, "CONFESSION_CHANNEL_ID", None)

USER_CONFESSION_COOLDOWNS: dict[int, float] = {}


def get_retry_after(user_id: int) -> float:
    now = time.monotonic()
    last_used = USER_CONFESSION_COOLDOWNS.get(user_id, 0.0)
    retry_after = CONFESSION_COOLDOWN_SECONDS - (now - last_used)
    return max(0.0, retry_after)


def touch_cooldown(user_id: int) -> None:
    USER_CONFESSION_COOLDOWNS[user_id] = time.monotonic()


class ConfessionModal(discord.ui.Modal, title="無名告白"):
    confession = discord.ui.TextInput(
        label="你想匿名講啲咩？",
        placeholder="寫低你想講嘅說話……",
        style=discord.TextStyle.paragraph,
        max_length=1200,
        required=True,
    )

    def __init__(self, cog: "Confession") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_confession(
            interaction=interaction,
            content=str(self.confession.value).strip(),
        )


class Confession(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _target_channel(self, interaction: discord.Interaction) -> discord.abc.Messageable | None:
        if CONFESSION_CHANNEL_ID:
            channel = interaction.client.get_channel(CONFESSION_CHANNEL_ID)
            if channel:
                return channel

        return interaction.channel

    async def open_confession_modal(self, interaction: discord.Interaction) -> None:
        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await interaction.response.send_message(
                f"⏳ 請等 {retry_after:.1f} 秒後再投稿。",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(ConfessionModal(self))

    async def submit_confession(self, interaction: discord.Interaction, content: str) -> None:
        if not content:
            await interaction.response.send_message(
                "❌ 投稿內容唔可以係空白。",
                ephemeral=True,
            )
            return

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await interaction.response.send_message(
                f"⏳ 請等 {retry_after:.1f} 秒後再投稿。",
                ephemeral=True,
            )
            return

        target = self._target_channel(interaction)
        if target is None:
            await interaction.response.send_message(
                "❌ 搵唔到可以發送告白嘅頻道。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🕯️ 無名告白",
            description=content,
            color=CONFESSION_COLOR,
        )
        embed.set_footer(text="Nameless Confession • 匿名投稿")

        await target.send(embed=embed)

        touch_cooldown(interaction.user.id)

        await interaction.response.send_message(
            "✅ 你嘅無名告白已送出。",
            ephemeral=True,
        )

    @app_commands.command(name="confess", description="匿名投稿一段無名告白")
    async def confess(self, interaction: discord.Interaction) -> None:
        await self.open_confession_modal(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Confession(bot))
