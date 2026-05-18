from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
import random
import time
from typing import Deque, Dict, List

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from cogs.menu import build_full_menu_view, build_menu_file
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from data.drink_data import (
    ALL_DRINKS,
    BARTENDER_ATTACHMENT_NAME,
    DRINK_COOLDOWN_SECONDS,
    DrinkEntry,
    ICON_MAP,
    RARITY_STYLE,
    RECENT_HISTORY_LIMIT,
    SEASONAL_DRINKS,
    TASTING_LINES,
)

DRINK_USER_COOLDOWNS: dict[int, float] = {}


def build_tasting_note(drink: DrinkEntry) -> str:
    base = drink.desc.rstrip("。")
    return f"{base}。{random.choice(TASTING_LINES)}"


def get_drink_retry_after(user_id: int) -> float:
    last_used = DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_drink_cooldown(user_id: int) -> None:
    DRINK_USER_COOLDOWNS[user_id] = time.time()


def current_seasonal_pool() -> List[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return pool
    return []


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


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

    async def _record_usage(self, interaction: discord.Interaction) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage("drink", interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _enforce_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        if is_admin_or_helper(interaction.user):
            return True

        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False

        touch_drink_cooldown(interaction.user.id)
        return True

    def _pick_rarity(self) -> str:
        labels = list(RARITY_STYLE.keys())
        weights = [RARITY_STYLE[label]["weight"] for label in labels]
        return random.choices(labels, weights=weights, k=1)[0]

    def _build_pool_for_rarity(self, rarity: str) -> List[DrinkEntry]:
        pool = [drink for drink in ALL_DRINKS if drink.rarity == rarity]
        seasonal = [drink for drink in current_seasonal_pool() if drink.rarity == rarity]
        return pool + seasonal

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        pool = self._build_pool_for_rarity(rarity)
        if not pool:
            pool = ALL_DRINKS + current_seasonal_pool()

        recent = set(self.user_recent_draws[user_id])
        candidates = [drink for drink in pool if drink.eng not in recent]
        chosen = random.choice(candidates or pool)
        self.user_recent_draws[user_id].append(chosen.eng)
        return chosen

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None,
        drink: DrinkEntry,
    ) -> str:
        icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])
        giver = interaction.user.mention
        receiver = (to or interaction.user).mention

        if to and to.id != interaction.user.id:
            return f"{icon} {giver} 為 {receiver} 點了一杯 **{drink.eng}（{drink.zh}）**。"

        return f"{icon} {giver} 在吧枱前點了一杯 **{drink.eng}（{drink.zh}）**。"

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_drink_cooldown(interaction)
            if not ok:
                return

        await self._record_usage(interaction)

        rarity = self._pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 **限定供應：** {drink.limited_tag}" if drink.limited_tag else ""
        tasting_note = build_tasting_note(drink)
        style_icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])

        rarity_line = f"{rarity_meta['emoji']} {rarity_meta['label']}"
        style_line = f"{style_icon} {drink.typ}"
        rotation_line = f"已避開最近 {RECENT_HISTORY_LIMIT} 杯"

        result_embed = discord.Embed(
            title="🍹 Bartender’s Pick",
            description=(
                f"{header}\n\n"
                f"**品飲筆記**\n"
                f"➡️ {tasting_note}{limited_text}\n\n"
                f"**吧枱卡**\n"
                f"`{rarity_line}` ｜ `{style_line}` ｜ `{rotation_line}`"
            ),
            color=rarity_meta["color"],
            timestamp=discord.utils.utcnow(),
        )
        result_embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")

        send_kwargs = build_result_payload(interaction, result_embed)

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_drink(interaction, enforce_cooldown=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="由酒保為你或指定成員調一杯特選飲品")
    @app_commands.describe(to="收酒嘅人")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None):
        await self.do_drink(interaction, to, enforce_cooldown=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
