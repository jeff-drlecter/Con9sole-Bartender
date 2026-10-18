from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Deque, Dict

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.action_guard import claim_action
from core.discord_interactions import require_public_send
from core.safe_send import send_or_followup
from data.drink_data import (
    ICON_MAP,
    RARITY_STYLE,
    RECENT_HISTORY_LIMIT,
    DrinkEntry,
)
from features.daily_bar import complete_daily_bar_task
from features.drink_catalog import (
    build_tasting_note,
    pick_rarity,
    pick_weighted_drink,
)
from features.drink_embeds import (
    build_drink_collection_embed,
    build_drink_stats_embed,
)
from features.drink_leaderboard import (
    DrinkLeaderboardView,
    build_drink_leaderboard_embed,
)
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
    has_collected_drink,
    init_drink_events_db,
    record_drink_event,
)
from features.drink_views import (
    DrinkCollectionView,
    DrinkResultView,
)
from features.member_picker import open_member_picker, resolve_member

log = logging.getLogger("con9sole-bartender.drink")


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(
            lambda: deque(maxlen=RECENT_HISTORY_LIMIT)
        )

        for user_id, drinks in load_recent_draw_map().items():
            self.user_recent_draws[user_id] = deque(
                [str(item) for item in drinks][-RECENT_HISTORY_LIMIT:],
                maxlen=RECENT_HISTORY_LIMIT,
            )

        init_drink_events_db()

    async def cog_load(self) -> None:
        self.bot.add_view(DrinkResultView())

    async def _record_usage(
        self, interaction: discord.Interaction, feature: str = "drink"
    ) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(
                    feature, interaction.user.id, interaction.guild_id
                )
            except Exception:
                log.exception(
                    "Failed to record drink usage: user=%s feature=%s",
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

    async def _check_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

    async def _check_gift_drink_cooldown(
        self, interaction: discord.Interaction
    ) -> bool:
        retry_after = get_gift_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在準備賜酒，請等 {retry_after:.1f} 秒後再試。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

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

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | discord.User | None = None,
    ) -> bool:
        with claim_action("drink", interaction.user.id) as claimed:
            if not claimed:
                await send_or_followup(
                    interaction,
                    content="🍹 酒保正在送出你嗰杯，請稍候。",
                    ephemeral=True,
                )
                return False
            if not await require_public_send(interaction):
                return False
            is_gift = to is not None and to.id != interaction.user.id
            if to is not None and to.bot:
                await send_or_followup(
                    interaction, content="請揀一位真人會員。", ephemeral=True
                )
                return False
            check = (
                self._check_gift_drink_cooldown
                if is_gift
                else self._check_drink_cooldown
            )
            if not await check(interaction):
                return False
            # Acknowledge before fetching a member or touching storage.
            await interaction.response.defer(thinking=True, ephemeral=False)
            if is_gift:
                to = await resolve_member(interaction, to)
                if to is None or to.bot:
                    await interaction.edit_original_response(
                        content="搵唔到呢位真人會員，請重新選擇。"
                    )
                    return False
            else:
                to = None
            recent = set(self.user_recent_draws[interaction.user.id])
            drink = pick_weighted_drink(rarity=pick_rarity(), recent_drink_names=recent)
            try:
                is_new = not has_collected_drink(
                    interaction.guild_id, (to or interaction.user).id, drink.eng
                )
            except Exception:
                log.exception("Could not read collection before delivery")
                is_new = False
            meta = RARITY_STYLE[drink.rarity]
            result_embed = discord.Embed(
                title=f"🍹 {drink.eng} · {drink.zh}",
                description=f"{self._build_header_line(interaction, to, drink)}\n\n{build_tasting_note(drink)}",
                color=meta["color"],
            )
            result_embed.set_footer(
                text=f"{meta['emoji']} {meta['label']} · {drink.typ}"
            )
            if is_new:
                result_embed.add_field(
                    name="✨ 新收藏",
                    value="呢款已為收酒者解鎖，隨時打開酒櫃睇。",
                    inline=False,
                )
            try:
                await interaction.edit_original_response(
                    content=to.mention if to else None,
                    embed=result_embed,
                    view=DrinkResultView(),
                    allowed_mentions=discord.AllowedMentions(
                        users=[to] if to else False, roles=False, everyone=False
                    ),
                )
            except discord.HTTPException:
                log.exception(
                    "Drink result delivery failed: interaction=%s", interaction.id
                )
                # No cooldown, draw history or drink event is committed on delivery failure.
                try:
                    await interaction.edit_original_response(
                        content="暫時送唔到呢杯，請稍後再試。"
                    )
                except discord.HTTPException:
                    pass
                return False
            usage_feature = "drink_gift" if is_gift else "drink"
            if is_gift:
                touch_gift_drink_cooldown(interaction.user.id)
            else:
                touch_drink_cooldown(interaction.user.id)
            self.user_recent_draws[interaction.user.id].append(drink.eng)
            save_recent_draws(
                interaction.user.id, list(self.user_recent_draws[interaction.user.id])
            )
            recorded = record_drink_event(
                guild_id=interaction.guild_id,
                event_type=EVENT_GIFT_DRINK if is_gift else EVENT_SELF_DRINK,
                actor_id=interaction.user.id,
                target_id=(to or interaction.user).id,
                drink=drink,
            )
            if recorded is False:
                await interaction.followup.send("飲品已送出，但收藏紀錄暫時保存唔到；請通知管理員，唔使重複叫酒。", ephemeral=True)
            await self._record_usage(interaction, feature=usage_feature)
            await self._complete_daily_bar(interaction, usage_feature)
            return True

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_drink(interaction)

    async def _gift_from_picker(
        self, interaction: discord.Interaction, *, to: discord.User | discord.Member
    ) -> bool:
        if to.id == interaction.user.id:
            await send_or_followup(
                interaction,
                content="自己飲請用「飲一杯」；呢度揀一位朋友啦。",
                ephemeral=True,
            )
            return False
        return await self.do_drink(interaction, to=to)

    async def gift_drink_entry(self, interaction: discord.Interaction) -> None:
        if await self._check_gift_drink_cooldown(interaction):
            await open_member_picker(
                interaction, deliver=self._gift_from_picker, label="🥂 想請邊位飲？"
            )

    async def stats_entry(self, interaction: discord.Interaction) -> None:
        embed = build_drink_stats_embed(interaction.guild, interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    async def collection_entry(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, interaction.user)
        view = DrinkCollectionView(
            owner_id=interaction.user.id,
            guild=interaction.guild,
            target_user=interaction.user,
        )
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)
        await self._complete_daily_bar(interaction, "drink_collection")

    async def leaderboard_entry(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction, feature="drink_leaderboard")
        embed = build_drink_leaderboard_embed(
            interaction.guild, requested_by=interaction.user
        )
        view = DrinkLeaderboardView(
            guild=interaction.guild, requested_by=interaction.user
        )
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="drink", description="由酒保為你或指定成員調一杯特選飲品"
    )
    @app_commands.describe(to="收酒嘅人；留空即係自己叫酒")
    async def drink(
        self, interaction: discord.Interaction, to: discord.Member | None = None
    ) -> None:
        await self.do_drink(interaction, to)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="drink_stats", description="查看自己或指定成員的酒保紀錄"
    )
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_stats(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        embed = build_drink_stats_embed(interaction.guild, target)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="drink_collection", description="查看自己或指定成員的酒單收藏"
    )
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_collection(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, target)
        view = DrinkCollectionView(
            owner_id=interaction.user.id, guild=interaction.guild, target_user=target
        )
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)
        if target.id == interaction.user.id:
            await self._complete_daily_bar(interaction, "drink_collection")

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_leaderboard", description="查看酒保排行榜")
    async def drink_leaderboard(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction, feature="drink_leaderboard")
        embed = build_drink_leaderboard_embed(
            interaction.guild, requested_by=interaction.user
        )
        view = DrinkLeaderboardView(
            guild=interaction.guild, requested_by=interaction.user
        )
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Drink(bot))
