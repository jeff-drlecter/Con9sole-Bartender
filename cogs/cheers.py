from __future__ import annotations

import logging
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.action_guard import claim_action
from core.discord_interactions import require_public_send
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from data.cheers_quotes import (
    CHEERS_COOLDOWN_SECONDS,
    CHEERS_QUOTES,
    CheerQuote,
)
from features.daily_bar import complete_daily_bar_task
from features.drink_views import DrinkResultView
from features.member_picker import open_member_picker, resolve_member

log = logging.getLogger("con9sole-bartender.cheers")

CHEERS_USER_COOLDOWNS: dict[int, float] = {}
CHEER_TARGET_TIMEOUT_SECONDS = 60.0


def get_cheers_retry_after(user_id: int) -> float:
    return max(
        0.0,
        CHEERS_COOLDOWN_SECONDS
        - (time.time() - CHEERS_USER_COOLDOWNS.get(user_id, 0.0)),
    )


def touch_cheers_cooldown(user_id: int) -> None:
    CHEERS_USER_COOLDOWNS[user_id] = time.time()


def pick_quote() -> CheerQuote:
    return random.choice(CHEERS_QUOTES)


class Cheers(commands.Cog):
    """/cheers：由 Bartender 為大家送上一句打氣說話。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _record_usage(
        self, interaction: discord.Interaction, feature: str
    ) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(
                    feature, interaction.user.id, interaction.guild_id
                )
            except Exception:
                log.exception(
                    "Failed to record cheers usage: user=%s feature=%s",
                    interaction.user.id,
                    feature,
                )

    async def _complete_daily_bar(
        self, interaction: discord.Interaction, feature: str
    ) -> None:
        completed = complete_daily_bar_task(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            feature_key=feature,
        )
        if not completed:
            return

        try:
            await interaction.followup.send(
                "📅 每日任務已完成！多謝你參與。",
                ephemeral=True,
            )
        except Exception:
            log.exception(
                "Failed to send daily-bar completion notice: user=%s feature=%s",
                interaction.user.id,
                feature,
            )

    async def _check_cheers_cooldown(self, interaction: discord.Interaction) -> bool:
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

        return True

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: Optional[discord.Member],
    ) -> str:
        giver = interaction.user.mention

        if to and to.id != interaction.user.id:
            return f"🎉 {giver} 為 {to.mention} 送上一句打氣！"

        return f"🎉 {giver} 的打氣時間！"

    async def do_cheers(
        self,
        interaction: discord.Interaction,
        to: discord.Member | discord.User | None = None,
    ) -> bool:
        with claim_action("cheers", interaction.user.id) as claimed:
            if not claimed:
                await send_or_followup(
                    interaction, content="正在送出打氣，請稍候。", ephemeral=True
                )
                return False
            if not await require_public_send(interaction):
                return False
            if to is not None and to.bot:
                await send_or_followup(
                    interaction, content="請揀一位真人會員。", ephemeral=True
                )
                return False
            if not await self._check_cheers_cooldown(interaction):
                return False
            await interaction.response.defer(thinking=True, ephemeral=False)
            if to is not None and to.id != interaction.user.id:
                to = await resolve_member(interaction, to)
                if to is None or to.bot:
                    await interaction.edit_original_response(
                        content="搵唔到呢位真人會員，請重新選擇。"
                    )
                    return False
            quote = pick_quote()
            embed = discord.Embed(
                title="🎉 打氣時間",
                description=f"{self._build_header_line(interaction, to)}\n\n💬 {quote.english}\n\n{quote.chinese}",
                color=0x57F287,
            )
            embed.set_footer(text=quote.author)
            try:
                await interaction.edit_original_response(
                    content=to.mention if to and to.id != interaction.user.id else None,
                    embed=embed,
                    view=DrinkResultView(),
                    allowed_mentions=discord.AllowedMentions(
                        users=[to] if to else False, roles=False, everyone=False
                    ),
                )
            except discord.HTTPException:
                log.exception("Cheer delivery failed: interaction=%s", interaction.id)
                try:
                    await interaction.edit_original_response(
                        content="暫時送唔到打氣，請稍後再試。"
                    )
                except discord.HTTPException:
                    pass
                return False
            touch_cheers_cooldown(interaction.user.id)
            feature = (
                "cheers_target" if to and to.id != interaction.user.id else "cheers"
            )
            await self._record_usage(interaction, feature)
            await self._complete_daily_bar(interaction, feature)
            return True

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_cheers(interaction)

    async def _target_from_picker(
        self, interaction: discord.Interaction, *, to: discord.Member | discord.User
    ) -> bool:
        if to.id == interaction.user.id:
            await send_or_followup(
                interaction,
                content="為自己打氣請用「打氣」；呢度揀一位朋友啦。",
                ephemeral=True,
            )
            return False
        return await self.do_cheers(interaction, to)

    async def cheer_for_member_entry(self, interaction: discord.Interaction) -> None:
        if await self._check_cheers_cooldown(interaction):
            await open_member_picker(
                interaction, deliver=self._target_from_picker, label="🙌 想幫邊位打氣？"
            )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="cheers", description="由 Bartender 送上一句打氣說話")
    @app_commands.describe(to="想打氣嘅對象")
    async def cheers(
        self, interaction: discord.Interaction, to: Optional[discord.Member] = None
    ):
        await self.do_cheers(interaction, to)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cheers(bot))
