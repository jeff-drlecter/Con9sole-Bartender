from __future__ import annotations

import asyncio

import discord

from data.drink_data import RARITY_STYLE
from features.drink_constants import GIFT_DRINK_TARGET_TIMEOUT_SECONDS
from features.drink_embeds import (
    build_drink_collection_embed,
    build_drink_collection_rarity_embed,
    build_drink_collection_recent_embed,
)


class DrinkCollectionView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild: discord.Guild | None, target_user: discord.Member | discord.User) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.guild = guild
        self.target_user = target_user
        self._add_rarity_buttons()

    def _add_rarity_buttons(self) -> None:
        button_styles = [
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.primary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.danger,
        ]
        for index, rarity in enumerate(list(RARITY_STYLE.keys())[:4]):
            meta = RARITY_STYLE.get(rarity, {})
            label = str(meta.get("label", rarity))[:80]
            emoji = str(meta.get("emoji", "🍸"))
            style = button_styles[index] if index < len(button_styles) else discord.ButtonStyle.secondary
            self.add_item(DrinkCollectionRarityButton(rarity=rarity, label=label, emoji=emoji, style=style, row=0))

        self.add_item(DrinkCollectionRecentButton(row=1))
        self.add_item(DrinkCollectionSummaryButton(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個酒單收藏面板只限發起者使用。", ephemeral=True)
            return False
        return True


class DrinkCollectionRarityButton(discord.ui.Button):
    def __init__(self, *, rarity: str, label: str, emoji: str, style: discord.ButtonStyle, row: int) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.rarity = rarity

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_rarity_embed(self.view.guild, self.view.target_user, self.rarity)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionRecentButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(label="最近解鎖", emoji="🕒", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_recent_embed(self.view.guild, self.view.target_user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionSummaryButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(label="總覽", emoji="🍾", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_embed(self.view.guild, self.view.target_user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class GiftDrinkCancelView(discord.ui.View):
    def __init__(self, *, owner_id: int, cancel_event: asyncio.Event) -> None:
        super().__init__(timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.cancel_event = cancel_event

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個賜酒取消按鈕只限發起者使用。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.cancel_event.is_set():
            await interaction.response.send_message("賜酒操作已經取消或逾時。", ephemeral=True)
            return

        self.cancel_event.set()
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(content="已取消賜酒。", embed=None, view=self)
        self.stop()
