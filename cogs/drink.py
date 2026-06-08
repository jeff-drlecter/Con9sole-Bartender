from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.safe_send import send_or_followup
from data.drink_data import (
    BARTENDER_ATTACHMENT_NAME,
    DrinkEntry,
    ICON_MAP,
    RARITY_STYLE,
    RECENT_HISTORY_LIMIT,
)
from features.drink_catalog import (
    build_tasting_note,
    pick_rarity,
    pick_weighted_drink,
)
from features.drink_constants import GIFT_DRINK_TARGET_TIMEOUT_SECONDS
from features.drink_embeds import (
    build_drink_collection_embed,
    build_drink_stats_embed,
    build_gift_prompt_embed,
)
from features.drink_result import build_bartender_result_payload
from features.drink_state import (
    get_drink_retry_after,
    get_gift_drink_retry_after,
    load_recent_draw_map,
    save_recent_draws,
    touch_drink_cooldown,
    touch_gift_drink_cooldown,
)
from features.drink_storage import (
    EVENT_GIFT_DRINK,
    EVENT_SELF_DRINK,
    init_drink_events_db,
    record_drink_event,
)
from features.drink_views import (
    DrinkCollectionView,
    GiftDrinkCancelView,
)


@dataclass
class GiftDrinkPending:
    started_at: float
    cancel_event: asyncio.Event


PENDING_GIFT_DRINK_REQUESTS: dict[int, GiftDrinkPending] = {}


def cleanup_pending_gift_requests() -> None:
    now = time.time()
    expired_user_ids = [
        user_id
        for user_id, pending in PENDING_GIFT_DRINK_REQUESTS.items()
        if now - pending.started_at >= GIFT_DRINK_TARGET_TIMEOUT_SECONDS
    ]
    for user_id in expired_user_ids:
        pending = PENDING_GIFT_DRINK_REQUESTS.pop(user_id, None)
        if pending is not None and not pending.cancel_event.is_set():
            pending.cancel_event.set()


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

        for user_id, drinks in load_recent_draw_map().items():
            self.user_recent_draws[user_id] = deque(
                [str(item) for item in drinks][-RECENT_HISTORY_LIMIT:],
                maxlen=RECENT_HISTORY_LIMIT,
            )

        init_drink_events_db()

    async def _record_usage(self, interaction: discord.Interaction, feature: str = "drink") -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(feature, interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _check_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

    async def _check_gift_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_gift_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在準備賜酒，請等 {retry_after:.1f} 秒後再試。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

    async def _enforce_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        ok = await self._check_drink_cooldown(interaction)
        if not ok:
            return False

        touch_drink_cooldown(interaction.user.id)
        return True

    async def _enforce_gift_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        ok = await self._check_gift_drink_cooldown(interaction)
        if not ok:
            return False

        touch_gift_drink_cooldown(interaction.user.id)
        return True

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        recent = set(self.user_recent_draws[user_id])
        chosen = pick_weighted_drink(rarity=rarity, recent_drink_names=recent)

        self.user_recent_draws[user_id].append(chosen.eng)
        save_recent_draws(user_id, list(self.user_recent_draws[user_id]))

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
        drink_name = f"**{drink.eng}（{drink.zh}）**"

        if to and to.id != interaction.user.id:
            return f"{icon} {giver} 賜一杯 {drink_name} 給 {receiver}。"

        return f"{icon} Bartender Special：酒保為 {giver} 調製了一杯 {drink_name}。"

    async def _wait_for_gift_target(self, interaction: discord.Interaction) -> discord.Member | None:
        if interaction.channel is None:
            await send_or_followup(interaction, content="❌ 搵唔到目前 channel，請重新試一次。", ephemeral=True)
            return None

        cleanup_pending_gift_requests()
        if interaction.user.id in PENDING_GIFT_DRINK_REQUESTS:
            await send_or_followup(
                interaction,
                content="⏳ 你已經有一個等待 tag 對象嘅賜酒操作。請先完成，或者撳該訊息嘅取消按鈕。",
                ephemeral=True,
            )
            return None

        # Opening the gift prompt must NOT consume cooldown.
        # Cancel / timeout / invalid target must NOT consume cooldown.
        # Gift cooldown is separate from self-drink cooldown.
        # Cooldown is consumed only when a valid target is confirmed and the drink is actually sent.
        ok = await self._check_gift_drink_cooldown(interaction)
        if not ok:
            return None

        cancel_event = asyncio.Event()
        PENDING_GIFT_DRINK_REQUESTS[interaction.user.id] = GiftDrinkPending(
            started_at=time.time(),
            cancel_event=cancel_event,
        )

        view = GiftDrinkCancelView(owner_id=interaction.user.id, cancel_event=cancel_event)
        await send_or_followup(
            interaction,
            embed=build_gift_prompt_embed(interaction.user),
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
                timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS,
            )
        )
        cancel_task = asyncio.create_task(cancel_event.wait())

        try:
            done, pending_tasks = await asyncio.wait(
                {message_task, cancel_task},
                timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending_tasks:
                task.cancel()

            if cancel_task in done and cancel_event.is_set():
                return None

            if message_task not in done:
                await interaction.followup.send("⏳ 已逾時，賜酒已取消。", ephemeral=True)
                return None

            try:
                message = message_task.result()
            except asyncio.TimeoutError:
                await interaction.followup.send("⏳ 已逾時，賜酒已取消。", ephemeral=True)
                return None
        finally:
            PENDING_GIFT_DRINK_REQUESTS.pop(interaction.user.id, None)
            view.stop()

        if message.content.strip().casefold() in {"cancel", "取消", "stop"}:
            await interaction.followup.send("已取消賜酒。", ephemeral=True)
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
            await interaction.followup.send("🍹 想自己飲可以直接用調酒，賜酒請 tag 另一位成員。", ephemeral=True)
            return None

        if target.bot:
            await interaction.followup.send("🤖 酒保暫時唔向 bot 賜酒，請 tag 一位真人成員。", ephemeral=True)
            return None

        return target

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
        feature: str | None = None,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_drink_cooldown(interaction)
            if not ok:
                return

        is_gift = bool(to and to.id != interaction.user.id)
        event_type = EVENT_GIFT_DRINK if is_gift else EVENT_SELF_DRINK
        usage_feature = feature or ("drink_gift" if is_gift else "drink")

        await self._record_usage(interaction, feature=usage_feature)

        rarity = pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        record_drink_event(
            guild_id=interaction.guild_id,
            event_type=event_type,
            actor_id=interaction.user.id,
            target_id=to.id if is_gift and to is not None else interaction.user.id,
            drink=drink,
        )

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 **限定供應：** {drink.limited_tag}" if drink.limited_tag else ""
        tasting_note = build_tasting_note(drink)
        style_icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])

        rarity_line = f"{rarity_meta['emoji']} {rarity_meta['label']}"
        style_line = f"{style_icon} {drink.typ}"
        rotation_line = f"最近 {RECENT_HISTORY_LIMIT} 杯低機率重複"

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

        send_kwargs = build_bartender_result_payload(
            interaction,
            result_embed,
            attachment_name=BARTENDER_ATTACHMENT_NAME,
        )

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_drink(interaction, enforce_cooldown=True)

    async def gift_drink_entry(self, interaction: discord.Interaction) -> None:
        # Menu gift flow:
        # 1. Open prompt without consuming cooldown.
        # 2. Cancel / timeout / invalid tag does not consume cooldown.
        # 3. Gift cooldown is separate from self-drink cooldown.
        # 4. A valid target consumes gift cooldown only.
        # 5. do_drink(... enforce_cooldown=False) prevents self-drink cooldown from blocking gifts.
        target = await self._wait_for_gift_target(interaction)
        if target is None:
            return

        touch_gift_drink_cooldown(interaction.user.id)

        await self.do_drink(
            interaction,
            to=target,
            enforce_cooldown=False,
            feature="drink_gift",
        )

    async def stats_entry(self, interaction: discord.Interaction) -> None:
        embed = build_drink_stats_embed(interaction.guild, interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    async def collection_entry(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, interaction.user)
        view = DrinkCollectionView(owner_id=interaction.user.id, guild=interaction.guild, target_user=interaction.user)
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="由酒保為你或指定成員調一杯特選飲品")
    @app_commands.describe(to="收酒嘅人；留空即係自己叫酒")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None) -> None:
        if to is not None and to.id != interaction.user.id:
            ok = await self._enforce_gift_drink_cooldown(interaction)
            if not ok:
                return

            await self.do_drink(
                interaction,
                to,
                enforce_cooldown=False,
                feature="drink_gift",
            )
            return

        await self.do_drink(interaction, to, enforce_cooldown=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_stats", description="查看自己或指定成員的酒保紀錄")
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        embed = build_drink_stats_embed(interaction.guild, target)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_collection", description="查看自己或指定成員的酒單收藏")
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_collection(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, target)
        view = DrinkCollectionView(owner_id=interaction.user.id, guild=interaction.guild, target_user=target)
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Drink(bot))
