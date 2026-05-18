from __future__ import annotations

import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from cogs.menu import build_full_menu_view, build_menu_file
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from data.cheers_quotes import (
    BARTENDER_ATTACHMENT_NAME,
    CHEERS_COOLDOWN_SECONDS,
    CHEERS_QUOTES,
    CheerQuote,
)

CHEERS_USER_COOLDOWNS: dict[int, float] = {}


def get_cheers_retry_after(user_id: int) -> float:
    last_used = CHEERS_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = CHEERS_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cheers_cooldown(user_id: int) -> None:
    CHEERS_USER_COOLDOWNS[user_id] = time.time()


def pick_quote() -> CheerQuote:
    return random.choice(CHEERS_QUOTES)


def build_result_payload(interaction: discord.Interaction, result_embed: discord.Embed) -> dict[str, object]:
    """Compact result embed + bartender thumbnail + Quick Bar buttons."""
    payload: dict[str, object] = {"embed": result_embed}

    menu_view = build_full_menu_view(interaction)
    if menu_view is not None:
        payload["view"] = menu_view

    menu_file = build_menu_file()
    if menu_file is not None:
        result_embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
        payload["file"] = menu_file

    return payload


class Cheers(commands.Cog):
    """/cheers：由 Bartender 為大家送上一句打氣說話。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _record_usage(self, interaction: discord.Interaction) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage("cheers", interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _enforce_cheers_cooldown(self, interaction: discord.Interaction) -> bool:
        # Admin / helpers 無視打氣 cooldown
        if is_admin_or_helper(interaction.user):
            return True

        retry_after = get_cheers_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 打氣時間正在補充能量，請等 {retry_after:.1f} 秒後再試。",
                ephemeral=True,
            )
            return False

        touch_cheers_cooldown(interaction.user.id)
        return True

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: Optional[discord.Member],
    ) -> str:
        giver = interaction.user.mention

        if to and to.id != interaction.user.id:
            return f"🎉 {giver} 為 {to.mention} 送上打氣時間！"

        return f"🎉 {giver} 的打氣時間！"

    async def do_cheers(
        self,
        interaction: discord.Interaction,
        to: Optional[discord.Member] = None,
        *,
        enforce_cooldown: bool = True,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_cheers_cooldown(interaction)
            if not ok:
                return

        await self._record_usage(interaction)

        quote = pick_quote()
        header = self._build_header_line(interaction, to)

        category = quote.category or "general"

        result_embed = discord.Embed(
            title="🎉 打氣時間",
            description=(
                f"{header}\n\n"
                f"**{quote.author} 講過：**\n\n"
                f"**English**\n"
                f"💬 {quote.english}\n\n"
                f"**中文**\n"
                f"➡️ {quote.chinese}\n\n"
                f"**打氣卡**\n"
                f"`🎯 {category}` ｜ `Con9sole-Bartender Cheers`"
            ),
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        )
        result_embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")

        send_kwargs = build_result_payload(interaction, result_embed)

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_cheers(interaction, enforce_cooldown=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="cheers", description="由 Bartender 送上一句打氣說話")
    @app_commands.describe(to="想打氣嘅對象")
    async def cheers(self, interaction: discord.Interaction, to: Optional[discord.Member] = None):
        await self.do_cheers(interaction, to, enforce_cooldown=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cheers(bot))