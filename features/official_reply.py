"""Reply in place to an authenticated announcement, using the Follow translator's receipts."""
import asyncio
from dataclasses import dataclass
import re

import discord

import config
from core import apex_updates, reviewed_games
from core.fc27_publication import BOT_ID, ReviewError, VERSION, clean, normalized, source_version
from core.gta_translation import APEX_CHANNEL_ID, FC_CHANNEL_ID, OFFICIAL_UPDATE_CHANNELS, TranslationQueue
from core.sqlite_storage import connect_sqlite
from core.storage_paths import DATA_DIR
from features.fc27_publisher import message_text
from features.fc27_review_ui import ERRORS, allowed, failure


PERMALINK = re.compile(r"https://discord\.com/channels/(\d{17,20})/(\d{17,20})/(\d{17,20})")
HAN = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class Draft:
    channel: int
    message: int
    identifier: str
    recap: str
    sources: tuple[str, ...]

    @classmethod
    def parse(cls, link, identifier, recap, sources):
        match = PERMALINK.fullmatch(link.strip())
        if not match or int(match[1]) != config.GUILD_ID or int(match[2]) not in OFFICIAL_UPDATE_CHANNELS:
            raise ReviewError("請貼上本伺服器官方更新頻道的原帖連結。")
        urls = tuple(line.strip() for line in sources.strip().splitlines())
        if not 1 <= len(urls) <= 2 or any(len(url) > 240 for url in urls):
            raise ReviewError("請填一至兩條官方來源，每行一條。")
        recap = clean(recap, 1150)
        if not HAN.search(recap):
            raise ReviewError("請填寫繁中整理。")
        return cls(int(match[2]), int(match[3]), clean(identifier, 80), recap, urls)

    @property
    def body(self):
        links = "\n".join(f"<{url}>" for url in self.sources)
        return f"**{OFFICIAL_UPDATE_CHANNELS[self.channel]} {self.identifier}｜Con9sole 繁中整理**\n{self.recap}\n\n**官方來源**\n{links}"


def version_marker(draft):
    ident = draft.identifier
    numeric = re.fullmatch(r"v?([0-9]+(?:\.[0-9]+)+)", ident, re.I)
    if not numeric:
        return re.compile(re.escape(ident), re.I)
    value = numeric[1]
    if draft.channel in (FC_CHANNEL_ID, APEX_CHANNEL_ID):
        canonical = normalized(value, "fc27" if draft.channel == FC_CHANNEL_ID else "apex")
        if canonical.endswith(".0"):
            pattern = re.escape(canonical[:-2]) + r"(?:\.0)?"
        else:
            pattern = re.escape(canonical)
    else:
        pattern = re.escape(value)
    return re.compile(r"(?<![\w.])v?" + pattern + r"(?!\w|\.\d)", re.I)


def release_keys(draft, original):
    """Bind the preview's sources to the original and share known publication identities."""
    marker = version_marker(draft)
    if not marker.search(original):
        raise ReviewError("原帖識別文字不符，請核對版本或標題。")
    channel_name = OFFICIAL_UPDATE_CHANNELS[draft.channel]
    keys = set()
    for url in draft.sources:
        if PERMALINK.fullmatch(url):
            if url not in re.findall(r"https://discord\.com/channels/\d+/\d+/\d+(?!\d)", original):
                raise ReviewError("Discord 來源必須來自指定原帖。")
            keys.add("discord-source:" + url)
            continue
        if draft.channel == FC_CHANNEL_ID:
            version = source_version(url)
            if version and marker.fullmatch(version):
                keys.add(version)
                continue
        elif draft.channel == APEX_CHANNEL_ID:
            day = apex_updates.dated_hotfix(url)
            if apex_updates.article_key(url) and (not day or marker.fullmatch(day)):
                keys.update(apex_updates.article_keys(url))
                continue
        else:
            for game, route in reviewed_games.ROUTES.items():
                item = reviewed_games.source(game, url) if route.channel == channel_name else None
                if (item and (not item.edition or marker.fullmatch(item.edition))
                        and (not item.month_day or draft.identifier.endswith(item.month_day[:2] + "-" + item.month_day[2:]))):
                    keys.update(reviewed_games.article_keys(game, [item]))
                    keys.add(game + ":" + draft.identifier.lstrip("vV").casefold())
                    break
            else:
                raise ReviewError("官方來源或版本與原帖不符。")
            continue
        raise ReviewError("官方來源或版本與原帖不符。")
    if draft.channel in (FC_CHANNEL_ID, APEX_CHANNEL_ID):
        game = "fc27" if draft.channel == FC_CHANNEL_ID else "apex"
        if re.fullmatch("v?" + VERSION, draft.identifier, re.I):
            value = normalized(draft.identifier.lstrip("vV"), game)
            keys.add(value if game == "fc27" else "apex:" + value)
        elif game == "apex":
            keys.update(apex_updates.relay_keys(original, VERSION))
    else:
        for game, route in reviewed_games.ROUTES.items():
            if route.channel == channel_name:
                keys.update(reviewed_games.relay_keys(game, original, original.splitlines()))
        games = [game for game, route in reviewed_games.ROUTES.items() if route.channel == channel_name]
        if len(games) == 1:
            keys.add(games[0] + ":" + draft.identifier.lstrip("vV").casefold())
    return keys


def receipt(queue, msg, keys, claim=False):
    source = msg.reference.message_id if msg.reference and msg.reference.message_id else msg.id
    with connect_sqlite(queue.path) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM posts WHERE message_id=? OR source_id=?", (msg.id, source)).fetchone():
            raise ReviewError("此原帖已有翻譯或送達紀錄，請先核對，避免重複回覆。")
        if any(db.execute("SELECT 1 FROM fc27_delivery_owner WHERE version=?", (key,)).fetchone()
               for key in keys):
            raise ReviewError("同一更新已有發布或轉發處理紀錄，請先核對。")
        if claim:
            db.executemany("INSERT INTO fc27_delivery_owner VALUES (?,?)",
                           [(key, f"reply:{msg.id}") for key in keys])
            db.execute("INSERT INTO posts(message_id,source_id,channel_id,stage,body) VALUES (?,?,?,'posting','')",
                       (msg.id, source, msg.channel.id))


def release_rejection(queue, message_id):
    # Only the confirmer that won the insert may release a definitive rejection.
    with connect_sqlite(queue.path) as db:
        db.execute("DELETE FROM fc27_delivery_owner WHERE owner=?", (f"reply:{message_id}",))
        db.execute("DELETE FROM posts WHERE message_id=? AND stage='posting' AND attempt=0", (message_id,))


async def inspect_original(interaction, draft, queue):
    guild = interaction.guild
    channel = guild.get_channel(draft.channel)
    if (interaction.client.user.id != BOT_ID or guild.id != config.GUILD_ID
            or not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id):
        raise ReviewError("找不到指定的助手或官方更新頻道。")
    for member in (guild.me, interaction.user):
        perms = channel.permissions_for(member)
        if not (perms.view_channel and perms.read_message_history):
            raise ReviewError("無法讀取原帖及回覆紀錄。")
    if not channel.permissions_for(guild.me).send_messages:
        raise ReviewError("助手缺少回覆原帖的權限。")
    msg = await channel.fetch_message(draft.message)
    if not (msg.webhook_id and msg.flags.is_crossposted and msg.type == discord.MessageType.default):
        raise ReviewError("只接受官方更新頻道收到的原生 Follow 轉發。")
    keys = release_keys(draft, message_text(msg))
    await asyncio.to_thread(receipt, queue, msg, keys)
    marker = version_marker(draft)
    if msg.flags.has_thread:
        thread = await interaction.client.fetch_channel(msg.id)
        if not isinstance(thread, discord.Thread) or thread.parent_id != channel.id:
            raise ReviewError("無法核對原帖的討論串。")
        if not thread.permissions_for(guild.me).read_message_history:
            raise ReviewError("無法核對討論串歷史。")
        async for item in thread.history(limit=2):
            if item.type != discord.MessageType.thread_starter_message:
                raise ReviewError(f"原帖已有討論串內容，請先核對 {item.jump_url}")
    count = 0
    async for item in channel.history(limit=1001):
        count += 1
        if count > 1000:
            raise ReviewError("頻道歷史超出可核對範圍，已停止。")
        if item.id == msg.id:
            continue
        referenced = item.reference and item.reference.message_id == msg.id
        text = message_text(item)
        if referenced or (marker.search(text) and HAN.search(text)):
            raise ReviewError(f"已有相關回覆或可能的繁中整理，請核對 {item.jump_url}")
    if not count:
        raise ReviewError("未能核對頻道歷史。")
    return msg, keys


class ReplyIntake(discord.ui.Modal, title="回覆現有官方帖"):
    original = discord.ui.TextInput(label="本伺服器的官方原帖連結", max_length=150)
    identifier = discord.ui.TextInput(label="原帖內的版本號或更新標題", max_length=80)
    recap = discord.ui.TextInput(label="繁中整理（附平台、日期及適用條件）", style=discord.TextStyle.paragraph, max_length=1150)
    sources = discord.ui.TextInput(label="官方原文或原帖所附英文來源串（每行一條）", style=discord.TextStyle.paragraph, max_length=481)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.owner):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            draft = Draft.parse(self.original.value, self.identifier.value, self.recap.value, self.sources.value)
            queue = await asyncio.to_thread(TranslationQueue, DATA_DIR / "gta_translation.sqlite3")
            msg, _ = await inspect_original(interaction, draft, queue)
            await interaction.followup.send(f"私人預覽 · 回覆 <{msg.jump_url}>\n\n{draft.body}",
                                           view=ConfirmReply(self.owner, queue, draft), ephemeral=True,
                                           allowed_mentions=discord.AllowedMentions.none())
        except ERRORS as exc:
            await failure(interaction, exc)


class ConfirmReply(discord.ui.View):
    def __init__(self, owner, queue, draft):
        super().__init__(timeout=900)
        self.owner, self.queue, self.draft = owner, queue, draft

    @discord.ui.button(label="確認並靜音回覆原帖", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction, _):
        if not await allowed(interaction, self.owner):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            msg, keys = await inspect_original(interaction, self.draft, self.queue)
            await asyncio.to_thread(receipt, self.queue, msg, keys, True)
            try:
                posted = await msg.channel.send(self.draft.body, reference=msg.to_reference(fail_if_not_exists=True),
                                                silent=True, mention_author=False, suppress_embeds=True,
                                                allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.NotFound):
                await asyncio.to_thread(release_rejection, self.queue, msg.id)
                raise
            await asyncio.to_thread(self.queue.sent, msg.id)
            await interaction.followup.send(f"已靜音回覆：{posted.jump_url}", ephemeral=True)
        except ERRORS as exc:
            if isinstance(exc, ReviewError):
                await failure(interaction, exc)
            else:
                await interaction.followup.send("未能確認回覆結果。請先核對原帖及送達紀錄。", ephemeral=True)
