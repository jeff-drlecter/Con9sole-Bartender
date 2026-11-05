from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

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
    build_announcement_text,
    game_name_from_forum,
    game_draft_from_pending,
    get_pending_games,
    mark_games_published,
    record_created_game,
    parse_announcement_version,
    record_published_version,
    version_guidance,
    latest_announcement_version,
)


log = logging.getLogger("con9sole-bartender.update-publisher")
MAX_GAMES_PER_DRAFT = 5


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


def _today_hong_kong() -> str:
    return datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%d.%m.%Y")


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
        await send_version_picker(interaction, kind="feature", games=[])

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
            f"揀今次要放入草稿的遊戲（最多 {MAX_GAMES_PER_DRAFT} 項）。",
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
            f"揀返已建立但未被記錄的遊戲 Forum（最多 {MAX_GAMES_PER_DRAFT - 1} 個）。",
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
        await send_version_picker(interaction, kind="game", games=selected_games)


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
            max_values=MAX_GAMES_PER_DRAFT - 1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ 呢個功能只可喺伺服器內使用。", ephemeral=True)
            return

        forums: list[discord.ForumChannel] = []
        for selected in self.values:
            forum = guild.get_channel(selected.id)
            if isinstance(forum, discord.ForumChannel):
                forums.append(forum)

        if not forums:
            await interaction.response.send_message("❌ 未能補錄所選 Forum。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="請為每個 Forum 揀返對應的專用 Role，再撳「下一步」。",
            view=ForumRoleMappingView(owner_id=interaction.user.id, guild_id=guild.id, forums=forums),
        )


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


class ForumRoleSelect(discord.ui.RoleSelect):
    def __init__(self, forum: discord.ForumChannel, *, row: int) -> None:
        super().__init__(
            placeholder=f"{game_name_from_forum(forum.name)[:80]} 專用 Role",
            min_values=1,
            max_values=1,
            row=row,
        )
        self.forum = forum

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, ForumRoleMappingView):
            await interaction.response.send_message("❌ Role 對應狀態失效，請重新補錄。", ephemeral=True)
            return
        role = self.values[0]
        self.view.role_ids[self.forum.id] = role.id
        await interaction.response.edit_message(
            content=f"已配對 {len(self.view.role_ids)}/{len(self.view.forums)} 個 Forum；完成後撳「下一步」。",
            view=self.view,
        )


class ContinueForumMappingButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="下一步", emoji="➡️", style=discord.ButtonStyle.success, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, ForumRoleMappingView):
            await interaction.response.send_message("❌ Role 對應狀態失效，請重新補錄。", ephemeral=True)
            return
        if len(self.view.role_ids) != len(self.view.forums):
            await interaction.response.send_message("請先為每個 Forum 揀一個專用 Role。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ 呢個功能只可喺伺服器內使用。", ephemeral=True)
            return

        games: list[PendingGame] = []
        for forum in self.view.forums:
            role = guild.get_role(self.view.role_ids[forum.id])
            if role is None:
                await interaction.response.send_message(f"❌ 搵唔到 `{forum.name}` 對應的 Role。", ephemeral=True)
                return
            games.append(
                record_created_game(
                    guild_id=guild.id,
                    name=game_name_from_forum(forum.name),
                    detail=f"{forum.mention} 已開放；專用身份：{role.mention}",
                    source_key=f"forum:{forum.id}",
                    role_id=role.id,
                )
            )
        await send_version_picker(interaction, kind="game", games=games)


class ForumRoleMappingView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild_id: int, forums: list[discord.ForumChannel]) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.forums = forums
        self.role_ids: dict[int, int] = {}
        for row, forum in enumerate(forums):
            self.add_item(ForumRoleSelect(forum, row=row))
        self.add_item(ContinueForumMappingButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id and _publisher_access_allowed(interaction):
            return True
        await interaction.response.send_message("❌ 呢個選單只限建立者使用。", ephemeral=True)
        return False


class VersionChoiceButton(discord.ui.Button):
    def __init__(self, label: str, version: str) -> None:
        super().__init__(label=f"{label} · {version}", style=discord.ButtonStyle.primary)
        self.version = version

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, VersionSelectionView):
            return
        if view.review_view is not None:
            review = view.review_view
            if review.cancelled or review.publishing or review.editing or review.published_message is not None or review.revision != view.revision:
                await interaction.response.send_message("草稿狀態已改，請重新開啟。", ephemeral=True)
                return
            await interaction.response.send_modal(EditDraftModal(review, version=self.version))
        else:
            await interaction.response.send_modal(AnnouncementDetailsModal(
                kind=view.kind, games=view.games, guild_id=view.guild_id, version=self.version))


class VersionSelectionView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild_id: int, kind: str,
                 games: list[PendingGame], review_view: "DraftReviewView | None" = None) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.kind = kind
        self.games = games
        self.review_view = review_view
        self.revision = review_view.revision if review_view is not None else 0
        latest = latest_announcement_version(guild_id)
        if review_view is not None:
            self.add_item(VersionChoiceButton("保留版本", review_view.draft.version))
        if latest is None:
            self.add_item(VersionChoiceButton("首次公告", "v1.0.0"))
        else:
            major, minor, patch = latest
            for label, version in (
                ("修訂", f"v{major}.{minor}.{patch + 1}"),
                ("小更新", f"v{major}.{minor + 1}.0"),
                ("大更新", f"v{major + 1}.0.0"),
            ):
                if parse_announcement_version(version) is not None:
                    self.add_item(VersionChoiceButton(label, version))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id and _publisher_access_allowed(interaction):
            return True
        await interaction.response.send_message("❌ 呢個選單只限建立者使用。", ephemeral=True)
        return False


async def send_version_picker(interaction: discord.Interaction, *, kind: str,
                              games: list[PendingGame], review_view: "DraftReviewView | None" = None) -> None:
    await interaction.response.send_message(
        "揀今次公告版本；揀完再填日期及內容，之後會先顯示草稿預覽。",
        view=VersionSelectionView(owner_id=interaction.user.id, guild_id=interaction.guild_id or 0,
                                  kind=kind, games=games, review_view=review_view),
        ephemeral=True,
    )


def draft_preview_text(draft: AnnouncementDraft, games: list[PendingGame]) -> str:
    text = build_announcement_text(draft, games=games)
    if draft.thread_body.strip():
        text = f"**內容 A｜公告**\n{text}\n\n**內容 B｜A 下方的 Thread**\n{draft.thread_body.strip()}"
    return text


async def publish_optional_thread(message: discord.Message, draft: AnnouncementDraft) -> str:
    """A is already published: thread failures must never trigger another A."""
    if not draft.thread_body.strip():
        return ""
    thread = None
    try:
        thread = await message.create_thread(
            name=f"Con9sole 更新 {draft.version}｜補充內容"[:100],
            reason="Update Publisher optional content B")
        await thread.send(draft.thread_body.strip(), allowed_mentions=discord.AllowedMentions.none())
        return f" Thread 已建立：{thread.mention}"
    except discord.DiscordException:
        log.exception("Announcement published but thread failed: message=%s", message.id)
        location = thread.mention if thread is not None else message.jump_url
        return f" ⚠️ 內容 A 已發佈；內容 B 未能確認發送，請先查看 {location} 再手動補上，勿重複發佈 A。"


class AnnouncementDetailsModal(discord.ui.Modal, title="更新公告資料"):
    announcement_date = discord.ui.TextInput(
        label="日期",
        placeholder="例如 17.09.2026",
        max_length=32,
    )
    new_features = discord.ui.TextInput(
        label="內容 A（公告；每行一項）",
        placeholder="例如：新增 FC27 及 NBA 2K27 遊戲專區",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )

    thread_content = discord.ui.TextInput(
        label="內容 B（選填；自動開 Thread）",
        placeholder="留空就唔開 Thread",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    def __init__(self, *, kind: str, games: list[PendingGame], guild_id: int = 0, version: str = "v1.0.0") -> None:
        super().__init__()
        self.kind = kind
        self.games = games
        self.version = version
        self.announcement_date.default = _today_hong_kong()
        if kind == "game" and games:
            game_names = "、".join(game.name for game in games)
            self.new_features.default = f"新增 {game_names} 遊戲專區"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not _publisher_access_allowed(interaction):
            await interaction.response.send_message("❌ 需要 Admin、Manage Server 或 Helper 權限。", ephemeral=True)
            return
        if parse_announcement_version(self.version) is None:
            await interaction.response.send_message("版本請填 v大.小.修訂，例如 v3.9.0（亦接受 v3.9）。", ephemeral=True)
            return
        draft = AnnouncementDraft(
            kind="game" if self.kind == "game" else "feature",
            title="Con9sole 更新公告",
            body=self.new_features.value.strip(),
            thread_body=self.thread_content.value.strip(),
            game_ids=tuple(game.id for game in self.games),
            version=self.version.strip(),
            announcement_date=self.announcement_date.value.strip(),
        )
        await send_draft_preview(interaction, draft, self.games)


class EditDraftModal(discord.ui.Modal, title="編輯公告草稿"):
    announcement_date = discord.ui.TextInput(label="日期", max_length=32)
    new_features = discord.ui.TextInput(
        label="內容 A（公告；每行一項）",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )

    thread_content = discord.ui.TextInput(
        label="內容 B（選填；自動開 Thread）",
        placeholder="留空就唔開 Thread",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    def __init__(self, view: "DraftReviewView", *, version: str | None = None) -> None:
        super().__init__()
        self.review_view = view
        self.revision = view.revision
        self.version = version or view.draft.version
        self.announcement_date.default = view.draft.announcement_date
        self.new_features.default = view.draft.body
        self.thread_content.default = view.draft.thread_body

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.review_view
        if interaction.user.id != view.owner_id or not _publisher_access_allowed(interaction):
            await interaction.response.send_message("你已冇權限修改呢份草稿。", ephemeral=True)
            return
        if view.cancelled or view.publishing or view.published_message is not None or view.editing or view.revision != self.revision:
            await interaction.response.send_message("草稿狀態已改，請重新開啟。", ephemeral=True)
            return
        candidate = AnnouncementDraft(
            kind=view.draft.kind, title="Con9sole 更新公告", body=self.new_features.value.strip(),
            game_ids=view.draft.game_ids, version=self.version.strip(),
            announcement_date=self.announcement_date.value.strip(),
            thread_body=self.thread_content.value.strip())
        if parse_announcement_version(candidate.version) is None:
            await interaction.response.send_message("版本請填 v大.小.修訂，例如 v3.9.0（亦接受 v3.9）。", ephemeral=True)
            return
        preview = "以下係草稿預覽；未發佈。\n\n" + draft_preview_text(candidate, view.games)
        if len(preview) > 2000:
            await interaction.response.send_message("草稿超過 2,000 字，請縮短內容。", ephemeral=True)
            return
        view.editing = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if view.message is not None:
                await view.message.edit(content=preview, embed=None, view=view,
                                        allowed_mentions=discord.AllowedMentions.none())
            view.draft = candidate
            view.revision += 1
            await interaction.followup.send("✅ 草稿已更新。", ephemeral=True)
        finally:
            view.editing = False



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
        self.publishing = False
        self.cancelled = False
        self.editing = False
        self.revision = 0
        self.published_message = None

    def embed(self) -> discord.Embed:
        return build_announcement_embed(self.draft, games=self.games)

    def announcement_text(self) -> str:
        return build_announcement_text(self.draft, games=self.games)

    def preview_content(self) -> str:
        return f"以下係草稿預覽；未發佈。\n\n{draft_preview_text(self.draft, self.games)}"

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
        if self.cancelled or self.publishing or self.editing or self.published_message is not None:
            await interaction.response.send_message("草稿正在處理或已結束。", ephemeral=True)
            return
        await send_version_picker(interaction, kind=self.draft.kind, games=self.games, review_view=self)

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

        # Acknowledge before any Discord request can exceed the interaction deadline.
        await interaction.response.defer()
        if getattr(self, "cancelled", False) or getattr(self, "editing", False):
            await interaction.followup.send("草稿已取消或正在編輯，未有發佈。", ephemeral=True)
            return
        if self.published_message is not None:
            await interaction.followup.send(
                f"✅ 呢份草稿已發佈，唔會重複發送：{self.published_message.jump_url}", ephemeral=True)
            return
        if self.publishing:
            await interaction.followup.send("⏳ 正在發佈，請稍候，唔使再撳。", ephemeral=True)
            return
        self.publishing = True
        try:
            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
                except discord.DiscordException:
                    log.exception("Unable to fetch announcement channel: channel=%s", channel_id)
                    await interaction.followup.send("❌ 搵唔到已設定的公告頻道，未有發佈。", ephemeral=True)
                    return

            if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
                await interaction.followup.send("❌ 公告頻道必須係此伺服器的文字／公告頻道。", ephemeral=True)
                return

            if self.draft.thread_body.strip():
                me = guild.me
                perms = channel.permissions_for(me) if me is not None else None
                if perms is None or not (perms.create_public_threads and perms.send_messages_in_threads):
                    await interaction.followup.send(
                        "❌ Bot 缺少開 Thread／在 Thread 發訊息權限，內容 A、B 都未有發佈。",
                        ephemeral=True)
                    return

            try:
                published_message = await channel.send(content=self.announcement_text(), allowed_mentions=discord.AllowedMentions.none())
            except discord.DiscordException:
                log.exception("Unable to publish update: channel=%s guild=%s", channel.id, guild.id)
                await interaction.followup.send("❌ 發佈未能確認；請先查看公告頻道，確認冇出文先重試。", ephemeral=True)
                return

            # Remember success before bookkeeping or confirmation can fail.
            self.published_message = published_message
            record_warning = ""
            try:
                record_published_version(guild.id, self.draft.version, message_id=published_message.id)
            except Exception:
                log.exception("Published update but could not record version: message=%s", published_message.id)
                record_warning = " 版本紀錄儲存失敗，請保留本次版本號；唔好重複發佈。"
            if self.draft.kind == "game":
                try:
                    mark_games_published(guild.id, self.draft.game_ids, message_id=published_message.id)
                except Exception:
                    log.exception("Published update but could not clear pending game records: message=%s", published_message.id)
                    record_warning = " 待公告紀錄未更新，請勿重複發佈，先檢查待公告清單。"
            thread_result = await publish_optional_thread(published_message, self.draft)
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(
                content=f"✅ 已發佈到 {channel.mention}。{record_warning}{thread_result}",
                embed=None,
                view=None,
            )
            self.stop()
        finally:
            self.publishing = False

    @discord.ui.button(label="取消", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def cancel_draft(self, interaction: discord.Interaction, _: discord.ui.Button["DraftReviewView"]) -> None:
        if self.publishing or self.editing or self.published_message is not None:
            await interaction.response.send_message("正在處理或已發佈，不能取消；請先查看公告頻道。", ephemeral=True)
            return
        self.cancelled = True
        self.revision += 1
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
    preview_content = f"{note}\n\n{draft_preview_text(draft, games)}"
    if len(preview_content) > 2000:
        await interaction.response.send_message(
            "❌ 草稿超過 Discord 2,000 字限制；請縮短新功能內容或減少今次項目。",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(preview_content, view=view, ephemeral=True)
    view.message = await interaction.original_response()


class UpdatePublisher(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _import_version_history(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or latest_announcement_version(guild.id) is not None:
            return
        channel_id = getattr(config, "ANNOUNCEMENT_CHANNEL_ID", 0)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            async for message in channel.history(limit=100):
                first_line = message.content.splitlines()[0] if message.content else ""
                match = re.search(r"Con9sole 更新公告\s*[—–-]\s*(v\.?\d+\.\d+(?:\.\d+)?)", first_line, re.IGNORECASE)
                if match:
                    record_published_version(guild.id, match.group(1), message_id=message.id)
        except (discord.DiscordException, OSError):
            log.exception("Could not import existing announcement versions: guild=%s", guild.id)

    async def open_from_admin_tool(self, interaction: discord.Interaction) -> None:
        if not _publisher_access_allowed(interaction):
            await send_or_followup(
                interaction,
                content="❌ 需要 Admin、Manage Server 或 Helper 權限。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._import_version_history(interaction)
        pending_count = len(get_pending_games(interaction.guild_id or 0))
        embed = _publisher_intro()
        embed.add_field(name="版本提示", value=version_guidance(interaction.guild_id or 0), inline=False)
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
