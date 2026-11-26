"""Private Update Publisher flow for reviewed game releases."""
import asyncio
from dataclasses import replace
from functools import partial
import logging
import sqlite3

import aiohttp
import discord

import config
from core.reviewed_games import ROUTES
from core.fc27_publication import Receipts, Release, ReviewError, normalized, receipt_key
from core.gta_translation import TranslationLimit
from core.permissions import is_server_admin
from core.storage_paths import DATA_DIR
from features.fc27_publisher import cards, publish, translated_draft
from features.wording import text as private_text

log = logging.getLogger(__name__)
DENIED = "只有開啟面板嘅管理員可以操作。"


async def allowed(interaction, owner):
    if (interaction.guild is not None and interaction.guild.id == config.GUILD_ID
            and interaction.user.id == owner and is_server_admin(interaction.user)):
        return True
    await interaction.response.send_message(private_text(interaction.user, DENIED), ephemeral=True)
    return False


async def failure(interaction, exc):
    if isinstance(exc, ReviewError):
        note = str(exc)
    elif isinstance(exc, TranslationLimit):
        note = "翻譯服務已達額度上限，請稍後再試。"
    else:
        log.warning("Game update review operation failed: %s status=%s", type(exc).__name__, getattr(exc, "status", None))
        note = "未能確認結果。請核對遊戲官方更新頻道，再用更新識別碼開啟確認稿。"
    await interaction.followup.send(note, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


ERRORS = (ValueError, RuntimeError, TimeoutError, aiohttp.ClientError, discord.DiscordException, sqlite3.Error,
          TranslationLimit)


async def preview(interaction, store, draft):
    view = Review(interaction.user.id, store, draft)
    await interaction.followup.send(
        f"私人預覽。請對照官方原文核對數字、單位、平台及例外，確認後由助手發布至 {draft.game_name} 官方更新頻道。",
        embeds=review_cards(draft), view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )


def review_cards(draft):
    if draft.game == "wwmhmt":
        return list(cards(draft))
    return [*cards(draft), discord.Embed(title="校對用英文摘要（僅自己可見）", description=draft.english)]


class Intake(discord.ui.Modal, title="FC27 官方更新"):
    version = discord.ui.TextInput(label="更新識別碼（只填此欄可載入已確認稿）", max_length=14, placeholder="例如 1.3.0")
    links = discord.ui.TextInput(label="官方原文（引文出處在首行，最多兩條）", style=discord.TextStyle.paragraph,
                                required=False, max_length=481)
    notes = discord.ui.TextInput(label="自撰英文摘要（保留數值、條件及平台差異）", style=discord.TextStyle.paragraph,
                                required=False, max_length=1600)
    quote = discord.ui.TextInput(label="第一篇來源的英文短引（最多 25 詞）", required=False, max_length=200)

    def __init__(self, owner, *, game="fc27"):
        super().__init__()
        self.owner = owner
        self.game = game
        if game in ROUTES:
            route = ROUTES[game]
            self.title = route.name + " 官方更新"
            self.version.max_length = 46
            self.version.placeholder = "例如 " + route.example
            self.headline = discord.ui.TextInput(label="第一篇官方原文的完整標題", required=False, max_length=150)
            self.add_item(self.headline)
        elif game == "apex":
            self.title = "Apex 官方更新"
            self.version.placeholder = "例如 1.2.3 或 2026-11-25"

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.owner):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            version = normalized(self.version.value, self.game)
            store = await asyncio.to_thread(Receipts, DATA_DIR / "gta_translation.sqlite3")
            receipt = await asyncio.to_thread(store.receipt, receipt_key(self.game, version))
            if receipt:
                if any(field.value.strip() for field in self.children if field is not self.version):
                    raise ReviewError("此版本已有確認稿。請只填版本號載入。")
                draft = Release.unpack(receipt[0])
                if draft.game != self.game or draft.version != version:
                    raise ReviewError("收據與選取的遊戲或更新不符，請核對已確認稿。")
            else:
                draft = Release.from_input(version, self.links.value, self.notes.value, self.quote.value,
                                           game=self.game, headline=self.headline.value if self.game in ROUTES else "")
                cog = interaction.client.get_cog("GTATranslation")
                provider = partial(cog.translate_reviewed, channel_id=draft.channel_id) if cog else None
                draft = await translated_draft(store, draft, provider)
            await preview(interaction, store, draft)
        except ERRORS as exc:
            await failure(interaction, exc)


class NativeIntake(Intake):
    notes = discord.ui.TextInput(label="人工撰寫的繁中摘要，保留地區、日期及條件", style=discord.TextStyle.paragraph,
                                required=False, max_length=1600)
    quote = discord.ui.TextInput(label="第一篇來源的繁中短引（最多 60 字）", required=False, max_length=60)


class Edit(discord.ui.Modal, title="校訂繁中整理"):
    recap = discord.ui.TextInput(label="主帖繁中摘要", style=discord.TextStyle.paragraph, max_length=2200)
    gloss = discord.ui.TextInput(label="英文短引的繁中對照", style=discord.TextStyle.paragraph, max_length=450)

    def __init__(self, review):
        super().__init__()
        self.review = review
        self.recap.default = review.draft.recap
        if review.draft.game == "wwmhmt":
            self.remove_item(self.gloss)
        else:
            self.gloss.default = review.draft.gloss

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.review.owner):
            return
        draft = replace(self.review.draft, recap=self.recap.value.strip(), gloss=self.review.draft.quote if self.review.draft.game == "wwmhmt" else self.gloss.value.strip())
        try:
            draft.check_translation()
        except ReviewError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        # Replace the original review and retire its old buttons.
        await interaction.response.edit_message(embeds=review_cards(draft), view=Review(self.review.owner, self.review.store, draft))
        self.review.stop()


class Review(discord.ui.View):
    def __init__(self, owner, store, draft):
        super().__init__(timeout=900)
        self.owner, self.store, self.draft = owner, store, draft

    @discord.ui.button(label="校訂繁中")
    async def edit(self, interaction, button):
        if await allowed(interaction, self.owner):
            if await asyncio.to_thread(self.store.receipt, self.draft.key):
                await interaction.response.send_message("已確認的版本不能修改，請載入原稿。", ephemeral=True)
                return
            await interaction.response.send_modal(Edit(self))

    @discord.ui.button(label="確認並由助手發布", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction, button):
        if not await allowed(interaction, self.owner):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            parent, source = await publish(interaction.client, interaction.guild, self.store, self.draft)
            language = "繁中" if self.draft.game == "wwmhmt" else "英文"
            await interaction.followup.send(f"[繁中主帖]({parent}) · [{language}來源串]({source})", ephemeral=True)
        except ERRORS as exc:
            await failure(interaction, exc)
