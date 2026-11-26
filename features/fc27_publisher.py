"""Build the same two cards for private review and explicit bot-authored delivery."""
import asyncio
import hashlib
from dataclasses import replace
import re
import time

import discord

import config
from core import apex_updates, reviewed_games
from core.fc27_publication import BOT_ID, DATE_START, VERSION, ReviewError, mentioned_versions


def cards(draft):
    label = draft.version if "-" in draft.version else f"v{draft.version}"
    title = f"{draft.game_name} {label}｜"
    attribution = "EA · Apex Legends" if draft.game == "apex" else "EA SPORTS FC Team"
    route = reviewed_games.ROUTES.get(draft.game)
    if route:
        attribution = route.publisher
    native = draft.game == "wwmhmt"
    language = "繁中" if native else "英文"
    parent = discord.Embed(title=title + "Con9sole 繁中整理", description=draft.recap, color=0x3478C9)
    parent.set_footer(text=f"Con9sole 整理 · {language}來源見本帖討論串")
    prefix = "" if route else "EA "
    links = [f"[{prefix}官方原文{'（引文出處）' if i == 0 else ''}]({url})" for i, url in enumerate(draft.urls)]
    heading = f" · {discord.utils.escape_markdown(draft.headline)}" if draft.headline else ""
    excerpt = f"**{attribution}**{heading}\n> {draft.quote}"
    if not native:
        excerpt += f"\n\n繁中對照：{draft.gloss}"
    source = discord.Embed(title=title + f"官方{language}來源", color=0x805AD5,
                           description=excerpt + "\n\n" + "\n".join(links))
    return parent, source


async def translated_draft(store, draft, provider):
    await asyncio.to_thread(store.check_sources, draft)
    if draft.game == "wwmhmt":
        return draft

    async def one(text, limit):
        cached, ticket = await asyncio.to_thread(store.translation, draft.urls[0], text, time.time(),
                                                 provider_available=provider is not None, channel_id=draft.channel_id)
        if ticket is None:
            return cached
        value = (await provider(text)).strip()
        if not value or len(value.encode("utf-16-le")) // 2 > limit:
            raise ReviewError("譯文過長或不完整，請縮短英文底稿。")
        await asyncio.to_thread(store.cache_result, ticket, value)
        return value
    return replace(draft, recap=await one(draft.english, 2200), gloss=await one(draft.quote, 450))


def same_card(message, embed):
    return (message.author.id == BOT_ID and not message.webhook_id and any(
        e.title == embed.title and e.description == embed.description for e in message.embeds))


def message_text(message):
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.extend([embed.title or "", embed.description or "", embed.url or ""])
        for field in embed.fields:
            parts.extend([field.name, field.value])
    return "\n".join(parts)


async def existing(channel, draft, embed, *, in_thread):
    found = None
    other = None
    number = re.escape(draft.version)
    if draft.version.endswith(".0"):
        number = re.escape(draft.version[:-2]) + r"(?:\.0)?"
    version_pattern = re.compile(r"(?<![\d.])" + number + r"(?!\d|\.\d)")
    # Stop instead of inferring absence from a capped history or an unreadable source thread.
    count = 0
    async for message in channel.history(limit=1001, after=DATE_START if draft.game == "fc27" else None):
        count += 1
        if count > 1000:
            raise ReviewError("頻道記錄超過檢查上限，請先核對歷史。")
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            continue
        text = message_text(message)
        for snapshot in getattr(message, "message_snapshots", []):
            text += "\n" + message_text(snapshot)
        if draft.game in reviewed_games.ROUTES:
            matches = (same_card(message, embed) or embed.title in text
                       or draft.owner_keys.intersection(reviewed_games.relay_keys(draft.game, text, text.splitlines())))
        elif draft.game == "apex":
            matches = draft.owner_keys.intersection(apex_updates.relay_keys(text, VERSION))
        else:
            matches = (draft.version in mentioned_versions(text) or version_pattern.search(text)
                       or any(url in text for url in draft.urls))
        if matches or (in_thread and message.author.id == BOT_ID):
            if found or not same_card(message, embed):
                raise ReviewError(f"已有可能相關的訊息，請先核對 {message.jump_url}")
            found = message
        elif in_thread:
            other = message
    if not in_thread and not count:
        raise ReviewError("未能讀到官方更新頻道的歷史，請核對助手權限。")
    if other is not None and found is None:
        raise ReviewError(f"來源串已有內容，請先核對 {other.jump_url}")
    return found


async def send_stage(channel, store, draft, embed, stage, phase, known_id, found):
    if known_id:
        message = await channel.fetch_message(known_id)
        if not same_card(message, embed):
            raise ReviewError("已記錄的訊息與確認稿不符，請核對原帖。")
        return message
    pending = stage + "_pending"
    expected = phase
    if found is None:
        if phase != stage or not await asyncio.to_thread(store.move, draft.key, stage, pending):
            raise ReviewError("送出結果尚未確認。請先核對頻道，稍後只輸入版本號再檢查。")
        expected = pending
        try:
            nonce = f"{draft.game}-{draft.version}-{stage}"
            if draft.game in reviewed_games.ROUTES:
                nonce = hashlib.sha256(nonce.encode()).hexdigest()[:24]
            found = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                       silent=True, nonce=nonce)
        except discord.HTTPException as exc:
            if exc.status in (400, 403, 404, 429):
                await asyncio.to_thread(store.move, draft.key, pending, stage)
            raise
    next_phase = "source" if stage == "parent" else "done"
    # Existing reviewed bot cards (including the one-off pilot) may predate receipts.
    if expected not in (stage, pending):
        raise ReviewError("送出階段與收據不符，請重新載入。")
    await asyncio.to_thread(store.move, draft.key, expected, next_phase, **{stage: found.id})
    return found


async def publish(bot, guild, store, draft):
    if guild.id != config.GUILD_ID or bot.user.id != BOT_ID or guild.me is None or guild.me.id != BOT_ID:
        raise ReviewError("助手或伺服器身份不符。")
    channel = guild.get_channel(draft.channel_id)
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id or channel.id != draft.channel_id:
        raise ReviewError("找不到已核准的遊戲官方更新頻道。")
    perms = channel.permissions_for(guild.me)
    if not (perms.view_channel and perms.read_message_history and perms.send_messages and perms.embed_links
            and perms.create_public_threads and perms.send_messages_in_threads):
        raise ReviewError("助手缺少讀取、嵌入訊息或討論串權限。")
    draft.check_translation()
    parent_card, source_card = cards(draft)
    receipt = await asyncio.to_thread(store.receipt, draft.key)
    found = None
    if not receipt or not receipt[2]:
        found = await existing(channel, draft, parent_card, in_thread=False)
    await asyncio.to_thread(store.begin, draft)
    _, phase, pid, _ = await asyncio.to_thread(store.receipt, draft.key)
    parent = await send_stage(channel, store, draft, parent_card, "parent", phase, pid, found)
    _, phase, pid, sid = await asyncio.to_thread(store.receipt, draft.key)
    if pid != parent.id:
        raise ReviewError("主帖收據尚未確認。")
    try:
        thread = await bot.fetch_channel(parent.id)
    except discord.NotFound as exc:
        if exc.code != 10003 or sid:
            raise
        # Discord allows only one attached thread, sharing its parent's message ID.
        thread = await parent.create_thread(name=source_card.title, auto_archive_duration=1440)
    if (not isinstance(thread, discord.Thread) or thread.parent_id != channel.id or thread.id != pid
            or thread.guild.id != guild.id or thread.name != source_card.title
            or thread.type not in (discord.ChannelType.public_thread, discord.ChannelType.news_thread)):
        raise ReviewError("原帖的討論串與確認稿不符。")
    thread_perms = thread.permissions_for(guild.me)
    if not (thread_perms.view_channel and thread_perms.read_message_history and thread_perms.send_messages_in_threads):
        raise ReviewError("助手無法讀寫來源串，請核對權限後再以版本號載入。")
    found = None if sid else await existing(thread, draft, source_card, in_thread=True)
    source = await send_stage(thread, store, draft, source_card, "source", phase, sid, found)
    receipt = await asyncio.to_thread(store.receipt, draft.key)
    if receipt[1:] != ("done", pid, source.id):
        raise ReviewError("英文來源收據尚未確認。")
    return parent.jump_url, source.jump_url
