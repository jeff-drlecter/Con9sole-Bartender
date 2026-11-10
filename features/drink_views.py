from __future__ import annotations
from features.wording import text as wording_text, view_copy as wording_view

import discord

from core.ui import SafeView
from features.menu_stats import run_stats
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
        self.rarity_page = 0
        self.active_rarity = None
        self.page_lock = __import__("asyncio").Lock()
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
        self.add_item(DrinkThemesButton(row=2))
        self.add_item(FeatureButton(label='我的會員卡',emoji='🎖️',cog='CommunityLevels',method='menu_entry',row=2))
        self.add_item(DrinkCollectionRecentButton(row=1))
        self.add_item(DrinkCollectionSummaryButton(row=1))
        self.add_item(
            FeatureButton(
                label="酒吧排行榜",
                emoji="🏆",
                cog="Drink",
                method="leaderboard_entry",
                row=1,
            )
        )
        self.add_item(
            FeatureButton(
                label="酒吧紀錄", emoji="📊", cog="Drink", method="stats_entry", row=4
            )
        )
        self.add_item(
            FeatureButton(
                label="今日小任務",
                emoji="📅",
                cog="DailyBar",
                method="menu_entry",
                row=4,
            )
        )
        self.add_item(
            FeatureButton(
                label="返回吧枱", emoji="🍸", cog="Menu", method="open_main_menu", row=4
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                wording_text(interaction.user, "呢個酒單收藏面板只限發起者使用。"), ephemeral=True
            )
            return False
        return True


class DrinkThemesButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="主題酒單", emoji="🗺️", style=discord.ButtonStyle.primary, row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DrinkCollectionView):
            return
        await interaction.response.defer()
        from features.theme_views import ThemeCollectionView

        themes_view = ThemeCollectionView(
            owner_id=view.owner_id, guild=view.guild, target_user=view.target_user
        )
        await themes_view.render(interaction)


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

        await interaction.response.defer()
        async with self.view.page_lock:
            self.view.active_rarity = self.rarity
            self.view.rarity_page = 0
            for child in list(self.view.children):
                if isinstance(child, CollectionPageButton):
                    self.view.remove_item(child)
            self.view.add_item(CollectionPageButton(-1))
            self.view.add_item(CollectionPageButton(1))
            embed = await run_stats(build_drink_collection_rarity_embed,
                                   self.view.guild, self.view.target_user, self.rarity, 0)
            await interaction.edit_original_response(embed=embed, view=wording_view(interaction.user, self.view))



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
        await interaction.response.edit_message(embed=embed, view=wording_view(interaction.user, self.view))


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

        await interaction.response.defer()
        for child in list(self.view.children):
            if isinstance(child, CollectionPageButton):
                self.view.remove_item(child)
        self.view.active_rarity = None
        embed = build_drink_collection_embed(self.view.guild, self.view.target_user)
        await interaction.edit_original_response(embed=embed, view=wording_view(interaction.user, self.view))
        if self.view.owner_id == self.view.target_user.id:
            from features.theme_views import deliver_pending_notice

            await deliver_pending_notice(interaction)


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
            embed=build_drink_milestones_embed(view.guild, view.target_user), view=wording_view(interaction.user, view)
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
                description="主題酒單精通"
                if a["milestone_id"].startswith("theme:")
                else f"{a['unlocked_at'][:10]} 解鎖",
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
                wording_text(interaction.user, "只可以更改自己嘅稱號。"), ephemeral=True
            )
            return
        cog=interaction.client.get_cog('TitleRoles')
        if cog is None:
            await interaction.response.send_message('稱號功能暫時未載入，請稍後再試。',ephemeral=True);return
        await cog.preview(interaction,self.values[0])


class CollectionPageButton(discord.ui.Button):
    def __init__(self, direction):
        super().__init__(label="上一頁" if direction < 0 else "下一頁", row=4,
                         style=discord.ButtonStyle.secondary)
        self.direction = direction

    async def callback(self, interaction):
        view = self.view
        if not isinstance(view, DrinkCollectionView) or view.active_rarity is None:
            return
        await interaction.response.defer()
        async with view.page_lock:
            from features.drink_storage import fetch_collection_rows
            from features.drink_constants import COLLECTION_PAGE_LIMIT
            rows = await run_stats(fetch_collection_rows, view.guild.id if view.guild else None,
                                   view.target_user.id, rarity=view.active_rarity)
            last = max(0, (len(rows) - 1) // COLLECTION_PAGE_LIMIT)
            view.rarity_page = max(0, min(last, view.rarity_page + self.direction))
            embed = await run_stats(build_drink_collection_rarity_embed,
                                   view.guild, view.target_user, view.active_rarity, view.rarity_page)
            await interaction.edit_original_response(embed=embed, view=wording_view(interaction.user, view))


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
                content=wording_text(interaction.user, "呢個功能暫時未準備好，請稍後再試。"),
                ephemeral=True,
            )
            return
        await getattr(cog, self.method)(interaction)


class DrinkResultView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        for index, (label, emoji, cog, method) in enumerate((
            ("我的收藏", "🍾", "Drink", "collection_entry"),
            ("請人飲", "🥂", "Drink", "gift_drink_entry"),
            ("我的會員卡", "🎖️", "CommunityLevels", "menu_entry"),
            ("返回吧枱", "🍸", "Menu", "open_main_menu"),
        )):
            self.add_item(
                FeatureButton(
                    label=label,
                    emoji=emoji,
                    cog=cog,
                    method=method,
                    row=index//2,
                    custom_id=f"bartender:result:{method}",
                )
            )


class MemberNavigationView(SafeView):
    def __init__(self,current=None) -> None:
        super().__init__(timeout=180)
        for key,label,emoji,cog,method,row in (
            ('card',"我的會員卡","🎖️","CommunityLevels","menu_entry",0),
            ('collection',"我的收藏","🍾","Drink","collection_entry",0),
            ('task',"今日小任務","📅","DailyBar","menu_entry",1),
            ('total',"等級總榜","🏆","CommunityLevels","leaderboard_entry",1),
            ('weekly',"本週排名","📅","CommunityLevels","weekly_entry",1),
            ('bar',"返回吧枱","🍸","Menu","open_main_menu",2),
        ):
            if key!=current:self.add_item(FeatureButton(label=label,emoji=emoji,cog=cog,method=method,row=row))


class MemberCardView(MemberNavigationView):
    def __init__(self):
        super().__init__(current='card')
        self.add_item(FeatureButton(label='管理稱號',emoji='🏅',cog='TitleRoles',method='menu_entry',row=0))


class LevelBoardView(MemberNavigationView):
    def __init__(self,cog,week,page,has_next):
        super().__init__(current='weekly' if week else 'total')
        for label,delta,disabled in (('上一頁',-1,page<=1),('下一頁',1,not has_next or page>=10000)):
            button=discord.ui.Button(label=label,row=3,disabled=disabled)
            async def move(inter,delta=delta):
                await cog.leaderboard.callback(cog,inter,weekly=bool(week),page=page+delta,period=week)
            button.callback=move;self.add_item(button)
