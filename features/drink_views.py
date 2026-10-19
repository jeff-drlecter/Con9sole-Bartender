from __future__ import annotations

import discord

from core.ui import SafeView
from data.drink_data import RARITY_STYLE
from features.drink_embeds import (
    build_drink_collection_embed,
    build_drink_collection_rarity_embed,
    build_drink_collection_recent_embed,
    build_drink_milestones_embed,
)


class DrinkCollectionView(SafeView):
    def __init__(
        self,
        *,
        owner_id: int,
        guild: discord.Guild | None,
        target_user: discord.Member | discord.User,
    ) -> None:
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
            style = (
                button_styles[index]
                if index < len(button_styles)
                else discord.ButtonStyle.secondary
            )
            self.add_item(
                DrinkCollectionRarityButton(
                    rarity=rarity, label=label, emoji=emoji, style=style, row=0
                )
            )

        self.add_item(DrinkMilestonesButton(row=2))
        self.add_item(DrinkCollectionRecentButton(row=1))
        self.add_item(DrinkCollectionSummaryButton(row=1))
        self.add_item(
            FeatureButton(
                label="排行榜",
                emoji="🏆",
                cog="Drink",
                method="leaderboard_entry",
                row=1,
            )
        )
        self.add_item(
            FeatureButton(
                label="酒保紀錄", emoji="📊", cog="Drink", method="stats_entry", row=1
            )
        )
        self.add_item(
            FeatureButton(
                label="今日小任務",
                emoji="📅",
                cog="DailyBar",
                method="menu_entry",
                row=1,
            )
        )
        self.add_item(
            FeatureButton(
                label="吧枱", emoji="🍸", cog="Menu", method="open_main_menu", row=2
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "呢個酒單收藏面板只限發起者使用。", ephemeral=True
            )
            return False
        return True


class DrinkCollectionRarityButton(discord.ui.Button):
    def __init__(
        self,
        *,
        rarity: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
        row: int,
    ) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.rarity = rarity

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message(
                "❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True
            )
            return

        embed = build_drink_collection_rarity_embed(
            self.view.guild, self.view.target_user, self.rarity
        )
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionRecentButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="最近解鎖", emoji="🕒", style=discord.ButtonStyle.secondary, row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message(
                "❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True
            )
            return

        embed = build_drink_collection_recent_embed(
            self.view.guild, self.view.target_user
        )
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionSummaryButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="總覽", emoji="🍾", style=discord.ButtonStyle.secondary, row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message(
                "❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True
            )
            return

        embed = build_drink_collection_embed(self.view.guild, self.view.target_user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkMilestonesButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="里程碑", emoji="🏅", style=discord.ButtonStyle.primary, row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DrinkCollectionView):
            return
        await interaction.response.defer()
        from features.collection_milestones import collection_snapshot

        snapshot = collection_snapshot(
            view.guild.id if view.guild else None, view.target_user.id
        )
        for child in list(view.children):
            if isinstance(child, CollectionTitleSelect):
                view.remove_item(child)
        if view.owner_id == view.target_user.id and snapshot["awards"]:
            view.add_item(CollectionTitleSelect(snapshot))
        await interaction.edit_original_response(
            embed=build_drink_milestones_embed(view.guild, view.target_user), view=view
        )


class CollectionTitleSelect(discord.ui.Select):
    def __init__(self, snapshot: dict) -> None:
        options = [
            discord.SelectOption(
                label="唔展示稱號", value="none", default=snapshot["selected"] is None
            )
        ]
        awards = snapshot["awards"][-24:]
        selected = next(
            (
                a
                for a in snapshot["awards"]
                if a["milestone_id"] == snapshot["selected"]
            ),
            None,
        )
        if selected and selected not in awards:
            awards = [selected] + awards[-23:]
        options += [
            discord.SelectOption(
                label=a["label"][:100],
                value=a["milestone_id"],
                description=f"{a['unlocked_at'][:10]} 解鎖",
                default=a["milestone_id"] == snapshot["selected"],
            )
            for a in awards
        ]
        super().__init__(
            placeholder="揀一個收藏展示稱號（可選）", options=options, row=3
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if (
            not isinstance(view, DrinkCollectionView)
            or interaction.user.id != view.target_user.id
        ):
            await interaction.response.send_message(
                "只可以更改自己嘅稱號。", ephemeral=True
            )
            return
        await interaction.response.defer()
        from features.collection_milestones import select_title

        if not select_title(interaction.guild_id, interaction.user.id, self.values[0]):
            await interaction.followup.send(
                "呢個稱號未解鎖，請重新開啟收藏。", ephemeral=True
            )
            return
        view.remove_item(self)
        await interaction.edit_original_response(
            embed=build_drink_collection_embed(view.guild, view.target_user), view=view
        )


class FeatureButton(discord.ui.Button):
    def __init__(
        self,
        *,
        label: str,
        emoji: str,
        cog: str,
        method: str,
        row: int,
        custom_id: str | None = None,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            row=row,
            custom_id=custom_id,
        )
        self.cog_name = cog
        self.method = method

    async def callback(self, interaction: discord.Interaction) -> None:
        from core.safe_send import send_or_followup

        cog = interaction.client.get_cog(self.cog_name)
        if cog is None:
            await send_or_followup(
                interaction,
                content="呢個功能暫時未準備好，請稍後再試。",
                ephemeral=True,
            )
            return
        await getattr(cog, self.method)(interaction)


class DrinkResultView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        for label, emoji, cog, method in (
            ("睇收藏", "🍾", "Drink", "collection_entry"),
            ("請人飲", "🥂", "Drink", "gift_drink_entry"),
            ("吧枱", "🍸", "Menu", "open_main_menu"),
        ):
            self.add_item(
                FeatureButton(
                    label=label,
                    emoji=emoji,
                    cog=cog,
                    method=method,
                    row=0,
                    custom_id=f"bartender:result:{method}",
                )
            )
