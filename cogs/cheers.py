from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from data.cheers_quotes import (
    BARTENDER_ATTACHMENT_NAME,
    CHEERS_COOLDOWN_SECONDS,
    CHEERS_QUOTES,
    CheerQuote,
)
from features.daily_bar import complete_daily_bar_task
from features.menu_helpers import build_menu_file
from features.menu_views import build_full_menu_view

CHEERS_USER_COOLDOWNS: dict[int, float] = {}
CHEER_TARGET_TIMEOUT_SECONDS = 60.0


@dataclass
class CheerTargetPending:
    started_at: float
    cancel_event: asyncio.Event


PENDING_CHEER_TARGET_REQUESTS: dict[int, CheerTargetPending] = {}


def get_cheers_retry_after(user_id: int) -> float:
    last_used = CHEERS_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = CHEERS_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cheers_cooldown(user_id: int) -> None:
    CHEERS_USER_COOLDOWNS[user_id] = time.time()


def cleanup_pending_cheer_requests() -> None:
    now = time.time()
    expired_user_ids = [
        user_id
        for user_id, pending in PENDING_CHEER_TARGET_REQUESTS.items()
        if now - pending.started_at >= CHEER_TARGET_TIMEOUT_SECONDS
    ]
    for user_id in expired_user_ids:
        pending = PENDING_CHEER_TARGET_REQUESTS.pop(user_id, None)
        if pending is not None and not pending.cancel_event.is_set():
            pending.cancel_event.set()


def pick_quote() -> CheerQuote:
    return random.choice(CHEERS_QUOTES)


def build_result_payload(interaction: discord.Interaction, result_embed: discord.Embed) -> dict[str, object]:
    payload: dict[str, object] = {"embed": result_embed}

    menu_view = build_full_menu_view(interaction)
    if menu_view is not None:
        payload["view"] = menu_view

    menu_file = build_menu_file()
    if menu_file is not None:
        result_embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
        payload["file"] = menu_file

    return payload


def build_cheer_target_prompt_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🙌 幫人打氣",
        description=(
            f"{user.mention}，請喺 **60 秒內** 喺呢個 channel tag 一位你想打氣嘅成員。\n\n"
            "例：`@jeff`\n\n"
            "你亦可以撳下面嘅 **取消** 按鈕。"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜只會讀取你下一個訊息。")
    return embed


class CheerTargetCancelView(discord.ui.View):
    def __init__(self, *, owner_id: int, cancel_event: asyncio.Event) -> None:
        super().__init__(timeout=CHEER_TARGET_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.cancel_event = cancel_event

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個打氣取消按鈕只限發起者使用。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.cancel_event.is_set():
            await interaction.response.send_message("幫人打氣操作已經取消或逾時。", ephemeral=True)
            return

        self.cancel_event.set()
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(content="已取消幫人打氣。", embed=None, view=self)
        self.stop()


class Cheers(commands.Cog):
    """/cheers：由 Bartender 為大家送上一句打氣說話。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _record_usage(self, interaction: discord.Interaction, feature: str) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(feature, interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _complete_daily_bar(self, interaction: discord.Interaction, feature: str) -> None:
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
            pass

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

    async def _enforce_cheers_cooldown(self, interaction: discord.Interaction) -> bool:
        ok = await self._check_cheers_cooldown(interaction)
        if not ok:
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
            return f"🎉 {giver} 為 {to.mention} 送上一句打氣！"

        return f"🎉 {giver} 的打氣時間！"

    async def _wait_for_cheer_target(self, interaction: discord.Interaction) -> discord.Member | None:
        if interaction.channel is None:
            await send_or_followup(interaction, content="❌ 搵唔到目前 channel，請重新試一次。", ephemeral=True)
            return None

        cleanup_pending_cheer_requests()
        if interaction.user.id in PENDING_CHEER_TARGET_REQUESTS:
            await send_or_followup(
                interaction,
                content="⏳ 你已經有一個等待 tag 對象嘅幫人打氣操作。請先完成，或者撳該訊息嘅取消按鈕。",
                ephemeral=True,
            )
            return None

        ok = await self._check_cheers_cooldown(interaction)
        if not ok:
            return None

        cancel_event = asyncio.Event()
        PENDING_CHEER_TARGET_REQUESTS[interaction.user.id] = CheerTargetPending(
            started_at=time.time(),
            cancel_event=cancel_event,
        )

        view = CheerTargetCancelView(owner_id=interaction.user.id, cancel_event=cancel_event)
        await send_or_followup(
            interaction,
            embed=build_cheer_target_prompt_embed(interaction.user),
            view=view,
            ephemeral=True,
        )

        def check(message: discord.Message) -> bool:
            if message.author.bot:
                return False
            if message.author.id != interaction.user.id:
                return False
            if message.channel.id != interaction.channel_id:
                return False
            return True

        message_task = asyncio.create_task(
            self.bot.wait_for(
                "message",
                check=check,
                timeout=CHEER_TARGET_TIMEOUT_SECONDS,
            )
        )
        cancel_task = asyncio.create_task(cancel_event.wait())

        try:
            done, pending_tasks = await asyncio.wait(
                {message_task, cancel_task},
                timeout=CHEER_TARGET_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending_tasks:
                task.cancel()

            if cancel_task in done and cancel_event.is_set():
                return None

            if message_task not in done:
                await interaction.followup.send("⏳ 已逾時，幫人打氣已取消。", ephemeral=True)
                return None

            try:
                message = message_task.result()
            except asyncio.TimeoutError:
                await interaction.followup.send("⏳ 已逾時，幫人打氣已取消。", ephemeral=True)
                return None
        finally:
            PENDING_CHEER_TARGET_REQUESTS.pop(interaction.user.id, None)
            view.stop()

        if message.content.strip().casefold() in {"cancel", "取消", "stop"}:
            await interaction.followup.send("已取消幫人打氣。", ephemeral=True)
            return None

        if len(message.mentions) != 1:
            await interaction.followup.send("❌ 請只 tag 一位成員。", ephemeral=True)
            return None

        target = message.mentions[0]
        if not isinstance(target, discord.Member):
            if interaction.guild is not None:
                target = interaction.guild.get_member(target.id)

        if target is None or not isinstance(target, discord.Member):
            await interaction.followup.send("❌ 搵唔到呢位成員，請重新試一次。", ephemeral=True)
            return None

        if target.id == interaction.user.id:
            await interaction.followup.send("🎉 想為自己打氣可以直接用打氣時間，幫人打氣請 tag 另一位成員。", ephemeral=True)
            return None

        if target.bot:
            await interaction.followup.send("🤖 酒保暫時唔向 bot 打氣，請 tag 一位真人成員。", ephemeral=True)
            return None

        return target

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

        usage_feature = "cheers_target" if to and to.id != interaction.user.id else "cheers"
        await self._record_usage(interaction, usage_feature)

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

        await self._complete_daily_bar(interaction, usage_feature)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_cheers(interaction, enforce_cooldown=True)

    async def cheer_for_member_entry(self, interaction: discord.Interaction) -> None:
        target = await self._wait_for_cheer_target(interaction)
        if target is None:
            return

        touch_cheers_cooldown(interaction.user.id)

        await self.do_cheers(
            interaction,
            to=target,
            enforce_cooldown=False,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="cheers", description="由 Bartender 送上一句打氣說話")
    @app_commands.describe(to="想打氣嘅對象")
    async def cheers(self, interaction: discord.Interaction, to: Optional[discord.Member] = None):
        await self.do_cheers(interaction, to, enforce_cooldown=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cheers(bot))
