"""Build the same two cards for private review and explicit bot-authored delivery."""
import asyncio
from dataclasses import replace
import re
import time

import discord

import config
from core.fc27_publication import BOT_ID, DATE_START, ReviewError, mentioned_versions
from core.gta_translation import FC_CHANNEL_ID


def cards(draft):
    title = f"FC27 v{draft.version}｜"
    parent = discord.Embed(title=title + "Con9sole 繁中整理", description=draft.recap, color=0x3478C9)
    parent.set_footer(text="Con9sole 整理 · 英文來源見本帖討論串")
    links = [f"[EA 官方原文{'（引文出處）' if i == 0 else ''}]({url})" for i, url in enumerate(draft.urls)]
    source = discord.Embed(title=title + "官方英文來源", color=0x805AD5,
                           description=f"**EA SPORTS FC Team**\n> {draft.quote}\n\n繁中對照：{draft.gloss}\n\n"
                                       + "\n".join(links))
    return parent, source


async def translated_draft(store, draft, provider):
    await asyncio.to_thread(store.check_sources, draft)
    async def one(text, limit):
        cached, ticket = await asyncio.to_thread(store.translation, draft.urls[0], text, time.time(),
                                                 provider_available=provider is not None)
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
    async for message in channel.history(limit=1001, after=DATE_START):
        count += 1
        if count > 1000:
            raise ReviewError("頻道記錄超過檢查上限，請先核對歷史。")
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            continue
        text = message_text(message)
        for snapshot in getattr(message, "message_snapshots", []):
            text += "\n" + message_text(snapshot)
        matches = (draft.version in mentioned_versions(text) or version_pattern.search(text)
                   or any(url in text for url in draft.urls))
        if matches or (in_thread and message.author.id == BOT_ID):
            if found or not same_card(message, embed):
                raise ReviewError(f"已有可能相關的訊息，請先核對 {message.jump_url}")
            found = message
        elif in_thread:
            other = message
    if not in_thread and not count:
        raise ReviewError("未能讀到 FC 官方更新頻道的歷史，請核對助手權限。")
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
        if phase != stage or not await asyncio.to_thread(store.move, draft.version, stage, pending):
            raise ReviewError("送出結果尚未確認。請先核對頻道，稍後只輸入版本號再檢查。")
        expected = pending
        try:
            found = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                       silent=True, nonce=f"fc27-{draft.version}-{stage}")
        except discord.HTTPException as exc:
            if exc.status in (400, 403, 404, 429):
                await asyncio.to_thread(store.move, draft.version, pending, stage)
            raise
    next_phase = "source" if stage == "parent" else "done"
    # Existing reviewed bot cards (including the one-off pilot) may predate receipts.
    if expected not in (stage, pending):
        raise ReviewError("送出階段與收據不符，請重新載入。")
    await asyncio.to_thread(store.move, draft.version, expected, next_phase, **{stage: found.id})
    return found


async def publish(bot, guild, store, draft):
    if guild.id != config.GUILD_ID or bot.user.id != BOT_ID or guild.me is None or guild.me.id != BOT_ID:
        raise ReviewError("助手或伺服器身份不符。")
    channel = guild.get_channel(FC_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id or channel.id != FC_CHANNEL_ID:
        raise ReviewError("找不到已核准的 FC 官方更新頻道。")
    perms = channel.permissions_for(guild.me)
    if not (perms.view_channel and perms.read_message_history and perms.send_messages and perms.embed_links
            and perms.create_public_threads and perms.send_messages_in_threads):
        raise ReviewError("助手缺少讀取、嵌入訊息或討論串權限。")
    draft.check_translation()
    parent_card, source_card = cards(draft)
    receipt = await asyncio.to_thread(store.receipt, draft.version)
    found = None
    if not receipt or not receipt[2]:
        found = await existing(channel, draft, parent_card, in_thread=False)
    await asyncio.to_thread(store.begin, draft)
    _, phase, pid, _ = await asyncio.to_thread(store.receipt, draft.version)
    parent = await send_stage(channel, store, draft, parent_card, "parent", phase, pid, found)
    _, phase, pid, sid = await asyncio.to_thread(store.receipt, draft.version)
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
    receipt = await asyncio.to_thread(store.receipt, draft.version)
    if receipt[1:] != ("done", pid, source.id):
        raise ReviewError("英文來源收據尚未確認。")
    return parent.jump_url, source.jump_url
