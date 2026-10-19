from __future__ import annotations

import logging
import math

import discord

from core.ui import SafeView
from features.drink_catalog import rarity_label
from features.theme_collections import (
    STYLE_LABELS,
    Theme,
    acknowledge,
    next_target,
    notice_text,
    snapshot,
    themes,
    track,
)

log = logging.getLogger("con9sole-bartender.drink.themes")
PAGE_SIZE = 12


async def deliver_pending_notice(interaction: discord.Interaction) -> None:
    """Use the viewer's own scope; other members' private notices stay unread."""
    try:
        state = snapshot(interaction.guild_id, interaction.user.id)
        if not state["pending"]:
            return
        await interaction.followup.send(
            notice_text(state["pending"]),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        acknowledge(
            interaction.guild_id,
            interaction.user.id,
            [a["award_id"] for a in state["pending"]],
        )
    except Exception:
        log.exception("Private collection notice remains pending")


def progress_text(theme: Theme, state: dict) -> str:
    target = next_target(theme, state)
    if target is None:
        return "🏅 已精通！仲可以慢慢探索酒單其他款式。"
    count = theme.count(state["names"])
    return f"**{min(count, target)} / {target} {theme.unit}**，再探索 {max(0, target - count)} {theme.unit}就達標。"


def build_theme_embed(
    state: dict,
    theme: Theme | None = None,
    *,
    mode: str = "detail",
    page: int = 0,
    own: bool = True,
) -> tuple[discord.Embed, int, int]:
    page_count = 1
    if theme is None:
        embed = discord.Embed(
            title="🗺️ 主題酒單",
            description="三張酒單一齊計進度，唔使逐張報名。\n新手由「吧枱初體驗」開始就得！",
            color=0x4B9B85,
        )
        for item in themes():
            marked = " · 追蹤中" if state["tracked"] == item.key else ""
            embed.add_field(
                name=f"{item.emoji} {item.label}{marked}",
                value=progress_text(item, state),
                inline=False,
            )
    else:
        embed = discord.Embed(title=f"{theme.emoji} {theme.label}", color=0x4B9B85)
        if mode in {"missing", "all"}:
            owned_types = {d.typ for d in theme.owned(state["names"])}
            items = [
                d
                for d in theme.drinks
                if mode == "all"
                or (
                    d.typ not in owned_types
                    if theme.by_style
                    else d.eng not in state["names"]
                )
            ]
            page_count = max(1, math.ceil(len(items) / PAGE_SIZE))
            page = max(0, min(page, page_count - 1))
            label = (
                "完整酒單"
                if mode == "all"
                else "未集類別嘅酒款"
                if theme.by_style
                else "未收藏酒款"
            )
            lines = [f"**{label} · {len(items):,} 款**"]
            for drink in items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
                mark = "✅" if drink.eng in state["names"] else "▫️"
                lines.append(
                    f"{mark} **{discord.utils.escape_markdown(drink.zh)}** · {rarity_label(drink.rarity)}\n{discord.utils.escape_markdown(drink.eng)}"
                )
            if not items:
                lines.append("呢度已經集齊，恭喜！")
            lines.append(f"\n第 {page + 1} / {page_count} 頁｜同一款可計入多張酒單。")
            embed.description = "\n".join(lines)
        elif mode == "stages":
            ids = {a["award_id"] for a in state["awards"]}
            lines = []
            for n in theme.targets:
                stage = (
                    "精通"
                    if n == theme.targets[-1]
                    else "入門完成"
                    if n == theme.targets[0]
                    else "進階"
                )
                award = next(
                    (a for a in state["awards"] if a["award_id"] == theme.award_id(n)),
                    None,
                )
                date = (
                    " · 舊收藏補計"
                    if award and award["backfilled"]
                    else f" · {award['unlocked_at'][:10]}"
                    if award
                    else ""
                )
                lines.append(
                    f"{'🏅' if theme.award_id(n) in ids else '▫️'} {stage}：{n} {theme.unit}{date}"
                )
            embed.description = (
                "\n".join(lines)
                + f"\n\n精通可選稱號：**{theme.title}**\n唔會自動換走你而家嘅稱號。"
            )
        else:
            instructions = {
                "starter": "任意收藏 **3 類酒，每類 1 款**，就完成第一張酒單。",
                "tropical": "收藏酒單內任意 **3 款不同熱帶酒**，就完成第一站。\n莫吉托、戴吉利都計，唔使指定抽中邊款。",
                "classics": "遇到酒單內 **任何 1 款經典**，就可以起步。\n78 款都計，唔使等某一款。呢張適合慢慢儲。",
            }
            embed.description = (
                instructions[theme.key] + "\n\n" + progress_text(theme, state)
            )
            if theme.by_style:
                owned_types = {d.typ for d in theme.owned(state["names"])}
                embed.add_field(
                    name="已探索類別",
                    value="\n".join(
                        f"{'✅' if key in owned_types else '⬜'} {label}"
                        for key, label in STYLE_LABELS.items()
                    ),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="收藏記錄",
                    value=f"酒單內已收藏 {len(theme.owned(state['names']))} / {len(theme.drinks)} 款；唔使全部集齊先算完成。",
                    inline=False,
                )
        if own and state["tracked"] == theme.key:
            embed.add_field(
                name="📍 追蹤中", value="呢張酒單會顯示喺收藏首頁。", inline=False
            )
    if own and state["pending"]:
        embed.add_field(
            name="✨ 收藏新進展", value=notice_text(state["pending"]), inline=False
        )
    embed.set_footer(
        text="舊收藏照計｜同款唔重複計｜追蹤唔會增加抽中機率｜進度唔會重置"
    )
    return embed, page, page_count


class ThemeCollectionView(SafeView):
    def __init__(
        self,
        *,
        owner_id: int,
        guild: discord.Guild | None,
        target_user: discord.User | discord.Member,
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.guild = guild
        self.target_user = target_user
        self.theme: Theme | None = None
        self.mode = "detail"
        self.page = 0

    @property
    def guild_id(self) -> int | None:
        return self.guild.id if self.guild else None

    @property
    def own(self) -> bool:
        return self.owner_id == self.target_user.id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "呢個酒單面板只限發起者使用。", ephemeral=True
        )
        return False

    async def render(self, interaction: discord.Interaction) -> None:
        state = snapshot(self.guild_id, self.target_user.id)
        embed, self.page, pages = build_theme_embed(
            state, self.theme, mode=self.mode, page=self.page, own=self.own
        )
        self.clear_items()
        self.add_item(ThemeSelect(self.theme))
        if self.theme:
            for label, action in (
                ("進度", "detail"),
                ("睇未集類別" if self.theme.by_style else "睇未收藏", "missing"),
                ("完整酒單", "all"),
                ("階段目標", "stages"),
            ):
                self.add_item(ThemeAction(label=label, action=action, row=1))
            if self.own:
                tracked = state["tracked"] == self.theme.key
                self.add_item(
                    ThemeAction(
                        label="取消追蹤" if tracked else "追蹤呢張",
                        action="untrack" if tracked else "track",
                        row=1,
                    )
                )
            if self.mode in {"missing", "all"}:
                self.add_item(
                    ThemeAction(
                        label="上一頁", action="prev", row=2, disabled=self.page == 0
                    )
                )
                self.add_item(
                    ThemeAction(
                        label="下一頁",
                        action="next",
                        row=2,
                        disabled=self.page >= pages - 1,
                    )
                )
        self.add_item(ThemeAction(label="全部主題", action="index", row=3))
        self.add_item(ThemeAction(label="收藏總覽", action="collection", row=3))
        if self.own:
            self.add_item(ThemeAction(label="選用稱號", action="titles", row=3))
        await interaction.edit_original_response(
            embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none()
        )
        if self.own and state["pending"]:
            try:
                acknowledge(
                    self.guild_id,
                    self.target_user.id,
                    [a["award_id"] for a in state["pending"]],
                )
            except Exception:
                log.exception("Theme notices delivered but acknowledgement failed")


class ThemeSelect(discord.ui.Select):
    def __init__(self, selected: Theme | None) -> None:
        super().__init__(
            placeholder="揀一張主題酒單",
            row=0,
            options=[
                discord.SelectOption(
                    label=t.label,
                    emoji=t.emoji,
                    value=t.key,
                    default=selected is not None and selected.key == t.key,
                )
                for t in themes()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ThemeCollectionView):
            return
        await interaction.response.defer()
        view.theme = next(t for t in themes() if t.key == self.values[0])
        view.mode, view.page = "detail", 0
        await view.render(interaction)


class ThemeAction(discord.ui.Button):
    def __init__(
        self, *, label: str, action: str, row: int, disabled: bool = False
    ) -> None:
        super().__init__(
            label=label, style=discord.ButtonStyle.secondary, row=row, disabled=disabled
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ThemeCollectionView):
            return
        if (
            self.action in {"track", "untrack", "titles"}
            and interaction.user.id != view.target_user.id
        ):
            await interaction.response.send_message(
                "只可以更改自己嘅收藏設定。", ephemeral=True
            )
            return
        await interaction.response.defer()
        if self.action in {"collection", "titles"}:
            from features.collection_milestones import collection_snapshot
            from features.drink_embeds import (
                build_drink_collection_embed,
                build_drink_milestones_embed,
            )
            from features.drink_views import CollectionTitleSelect, DrinkCollectionView

            collection_view = DrinkCollectionView(
                owner_id=view.owner_id, guild=view.guild, target_user=view.target_user
            )
            builder = build_drink_collection_embed
            if self.action == "titles":
                builder = build_drink_milestones_embed
                state = collection_snapshot(view.guild_id, view.target_user.id)
                if state["awards"]:
                    collection_view.add_item(CollectionTitleSelect(state))
            await interaction.edit_original_response(
                embed=builder(view.guild, view.target_user),
                view=collection_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if self.action == "index":
            view.theme, view.mode, view.page = None, "detail", 0
        elif self.action in {"track", "untrack"}:
            if view.theme:
                track(
                    view.guild_id,
                    view.target_user.id,
                    view.theme.key if self.action == "track" else None,
                )
        elif self.action in {"prev", "next"}:
            view.page += 1 if self.action == "next" else -1
        else:
            view.mode, view.page = self.action, 0
        await view.render(interaction)
