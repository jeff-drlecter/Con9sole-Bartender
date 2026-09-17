from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup
from features.update_publisher import (
    AnnouncementDraft,
    MAX_PENDING_GAMES,
    PendingGame,
    build_announcement_embed,
    game_name_from_forum,
    game_draft_from_pending,
    get_pending_games,
    mark_games_published,
    record_created_game,
)


log = logging.getLogger("con9sole-bartender.update-publisher")
MAX_GAMES_PER_DRAFT = 10


def _publisher_access_allowed(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None and is_admin_or_helper(interaction.user)


def _publisher_intro() -> discord.Embed:
    return discord.Embed(
        title="📣 Update Publisher",
        description=(
            "建立草稿、先睇預覽，再由你手動發佈。\n"
            "新遊戲只會記錄喺待公告清單，**唔會自動出 Post**。"
        ),
        color=0x5865F2,
    )


class PublisherStartView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild_id: int) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢份草稿工具只限開啟者使用。", ephemeral=True)
            return False
        if not _publisher_access_allowed(interaction):
            await interaction.response.send_message("❌ 需要 Admin、Manage Server 或 Helper 權限。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="功能更新", emoji="✨", style=discord.ButtonStyle.primary)
    async def feature_draft(self, interaction: discord.Interaction, _: discord.ui.Button["PublisherStartView"]) -> None:
        await interaction.response.send_modal(FeatureDraftModal(owner_id=self.owner_id, guild_id=self.guild_id))

    @discord.ui.button(label="遊戲更新", emoji="🎮", style=discord.ButtonStyle.success)
    async def game_draft(self, interaction: discord.Interaction, _: discord.ui.Button["PublisherStartView"]) -> None:
        pending_games = get_pending_games(self.guild_id)
        if not pending_games:
            await interaction.response.send_message(
                "暫時冇待公告的新遊戲；可以撳「補錄現有 Forum」揀返已建立的專區。",
                ephemeral=True,
            )
            return

        selectable_games = pending_games[-25:]
        await interaction.response.send_message(
            "揀今次要放入草稿的遊戲（最多 10 項）。",
            view=PendingGameSelectionView(
                owner_id=self.owner_id,
                guild_id=self.guild_id,
                games=selectable_games,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="補錄現有 Forum", emoji="➕", style=discord.ButtonStyle.secondary)
    async def backfill_forums(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button["PublisherStartView"],
    ) -> None:
        await interaction.response.send_message(
            "揀返已建立但未被記錄的遊戲 Forum（最多 10 個）。",
            view=ForumBackfillView(owner_id=self.owner_id, guild_id=self.guild_id),
            ephemeral=True,
        )


class PendingGameSelect(discord.ui.Select):
    def __init__(self, games: list[PendingGame]) -> None:
        self.games_by_id = {game.id: game for game in games}
        options = [
            discord.SelectOption(
                label=game.name[:100],
                value=game.id,
                description=game.detail[:100],
            )
            for game in games
        ]
        super().__init__(
            placeholder="選擇待公告遊戲",
            min_values=1,
            max_values=min(MAX_GAMES_PER_DRAFT, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_games = [self.games_by_id[game_id] for game_id in self.values if game_id in self.games_by_id]
        await send_draft_preview(interaction, game_draft_from_pending(selected_games), selected_games)


class PendingGameSelectionView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild_id: int, games: list[PendingGame]) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.add_item(PendingGameSelect(games))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id and _publisher_access_allowed(interaction):
            return True
        await interaction.response.send_message("❌ 呢個選單只限建立者使用。", ephemeral=True)
        return False


class ExistingForumSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="選擇遊戲 Forum",
            channel_types=[discord.ChannelType.forum],
            min_values=1,
            max_values=MAX_GAMES_PER_DRAFT,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ 呢個功能只可喺伺服器內使用。", ephemeral=True)
            return

        recorded_games: list[PendingGame] = []
        for selected in self.values:
            forum = guild.get_channel(selected.id)
            if not isinstance(forum, discord.ForumChannel):
                continue
            recorded_games.append(
                record_created_game(
                    guild_id=guild.id,
                    name=game_name_from_forum(forum.name),
                    detail=f"{forum.mention} 已開放，歡迎入嚟一齊玩。",
                    source_key=f"forum:{forum.id}",
                )
            )

        if not recorded_games:
            await interaction.response.send_message("❌ 未能補錄所選 Forum。", ephemeral=True)
            return
        await send_draft_preview(interaction, game_draft_from_pending(recorded_games), recorded_games)


class ForumBackfillView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild_id: int) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.add_item(ExistingForumSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id and _publisher_access_allowed(interaction):
            return True
        await interaction.response.send_message("❌ 呢個選單只限建立者使用。", ephemeral=True)
        return False


class FeatureDraftModal(discord.ui.Modal, title="功能更新草稿"):
    announcement_title = discord.ui.TextInput(
        label="標題",
        default="✨ 功能更新",
        max_length=256,
    )
    announcement_body = discord.ui.TextInput(
        label="內容",
        placeholder="簡短講解今次有咩更新。",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, *, owner_id: int, guild_id: int) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = AnnouncementDraft(
            kind="feature",
            title=self.announcement_title.value.strip(),
            body=self.announcement_body.value.strip(),
        )
        await send_draft_preview(interaction, draft, [])


class EditDraftModal(discord.ui.Modal, title="編輯公告草稿"):
    announcement_title = discord.ui.TextInput(label="標題", max_length=256)
    announcement_body = discord.ui.TextInput(
        label="內容",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, view: "DraftReviewView") -> None:
        super().__init__()
        self.review_view = view
        self.announcement_title.default = view.draft.title
        self.announcement_body.default = view.draft.body

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.review_view.draft = AnnouncementDraft(
            kind=self.review_view.draft.kind,
            title=self.announcement_title.value.strip(),
            body=self.announcement_body.value.strip(),
            game_ids=self.review_view.draft.game_ids,
        )
        if self.review_view.message is not None:
            await self.review_view.message.edit(
                content="以下係草稿預覽；未發佈。",
                embed=self.review_view.embed(),
                view=self.review_view,
            )
        await interaction.response.send_message("✅ 草稿已更新。", ephemeral=True)


class DraftReviewView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        guild_id: int,
        draft: AnnouncementDraft,
        games: list[PendingGame],
    ) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.draft = draft
        self.games = games
        self.message: discord.InteractionMessage | None = None

    def embed(self) -> discord.Embed:
        return build_announcement_embed(self.draft, games=self.games)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢份草稿只限建立者使用。", ephemeral=True)
            return False
        if not _publisher_access_allowed(interaction):
            await interaction.response.send_message("❌ 需要 Admin、Manage Server 或 Helper 權限。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="編輯", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_draft(self, interaction: discord.Interaction, _: discord.ui.Button["DraftReviewView"]) -> None:
        await interaction.response.send_modal(EditDraftModal(self))

    @discord.ui.button(label="發佈", emoji="📣", style=discord.ButtonStyle.success)
    async def publish_draft(self, interaction: discord.Interaction, _: discord.ui.Button["DraftReviewView"]) -> None:
        channel_id = getattr(config, "ANNOUNCEMENT_CHANNEL_ID", 0)
        if not isinstance(channel_id, int) or isinstance(channel_id, bool) or channel_id <= 0:
            await interaction.response.send_message("❌ 未設定 `ANNOUNCEMENT_CHANNEL_ID`，未有發佈。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ 呢個功能只可喺伺服器內使用。", ephemeral=True)
            return

        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                fetched = await interaction.client.fetch_channel(channel_id)
            except discord.DiscordException:
                log.exception("Unable to fetch announcement channel: channel=%s", channel_id)
                await interaction.response.send_message("❌ 搵唔到已設定的公告頻道，未有發佈。", ephemeral=True)
                return
            channel = fetched

        if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
            await interaction.response.send_message("❌ 公告頻道必須係此伺服器的文字／公告頻道。", ephemeral=True)
            return

        try:
            published_message = await channel.send(embed=self.embed())
        except discord.DiscordException:
            log.exception("Unable to publish update: channel=%s guild=%s", channel.id, guild.id)
            await interaction.response.send_message("❌ 發佈失敗；請檢查 Bot 喺公告頻道的發訊息及 Embed 權限。", ephemeral=True)
            return

        record_warning = ""
        if self.draft.kind == "game":
            try:
                mark_games_published(guild.id, self.draft.game_ids, message_id=published_message.id)
            except Exception:
                log.exception("Published update but could not clear pending game records: message=%s", published_message.id)
                record_warning = " 待公告紀錄未更新，請勿重複發佈，先檢查 `/data/game_announcements.json`。"
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ 已發佈到 {channel.mention}。{record_warning}",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="取消", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def cancel_draft(self, interaction: discord.Interaction, _: discord.ui.Button["DraftReviewView"]) -> None:
        self.stop()
        await interaction.response.edit_message(content="已取消草稿，未有發佈。", embed=None, view=None)


async def send_draft_preview(
    interaction: discord.Interaction,
    draft: AnnouncementDraft,
    games: list[PendingGame],
    *,
    note: str = "以下係草稿預覽；未發佈。",
) -> None:
    view = DraftReviewView(
        owner_id=interaction.user.id,
        guild_id=interaction.guild_id or 0,
        draft=draft,
        games=games,
    )
    await interaction.response.send_message(note, embed=view.embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()


class UpdatePublisher(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def open_from_admin_tool(self, interaction: discord.Interaction) -> None:
        if not _publisher_access_allowed(interaction):
            await send_or_followup(
                interaction,
                content="❌ 需要 Admin、Manage Server 或 Helper 權限。",
                ephemeral=True,
            )
            return

        pending_count = len(get_pending_games(interaction.guild_id or 0))
        embed = _publisher_intro()
        embed.add_field(
            name="待公告遊戲",
            value=f"{pending_count} 項（每次最多草擬 {MAX_GAMES_PER_DRAFT} 項；最多保留 {MAX_PENDING_GAMES} 項）",
            inline=False,
        )
        await send_or_followup(
            interaction,
            embed=embed,
            view=PublisherStartView(owner_id=interaction.user.id, guild_id=interaction.guild_id or 0),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UpdatePublisher(bot))
