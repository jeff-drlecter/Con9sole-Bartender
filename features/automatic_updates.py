"""Bot-authored release recaps. Only fixed public publisher endpoints and configured game channels."""
import asyncio
from dataclasses import replace
from datetime import datetime
import re
import time

import aiohttp
import discord

import config
from core.automatic_updates import (
    APPS, HMT, HMT_URL, STEAM_NEWS, UPDATE, Notice, current_article, dated_keys, excerpt, hmt_notices, identities, steam_notices,
)
from core.fc27_publication import BOT_ID, ReviewError
from core.gta_translation import HONG_KONG, OFFICIAL_UPDATE_CHANNELS
from features.fc27_publisher import message_text


async def fetch(session, name, store):
    url = HMT_URL if name == HMT else STEAM_NEWS
    params = None if name == HMT else {"appid": str(APPS[name]), "count": "50",
                                       "feeds": "steam_community_announcements", "maxlength": "0"}
    async with session.get(url, params=params, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=20)) as response:
        if response.status != 200:
            raise ValueError(f"publisher HTTP {response.status}")
        body = bytearray()
        async for block in response.content.iter_chunked(32768):
            body.extend(block)
            if len(body) > 2_000_000:
                raise ValueError("Oversized publisher index")
    if name == HMT:
        return hmt_notices(body)
    items = steam_notices(name, body)
    fresh = []
    for item in items:
        identity = next(k for k in item.keys if k.startswith("steam:feed:"))
        if await asyncio.to_thread(store.seen, item.channel, identity):
            continue
        if item.published <= store.started:
            fresh.append(item)
            continue
        # News gids differ from announcement IDs. Only accept Steam's own redirect to this game.
        async with session.head(item.url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=10)) as redirect:
            target = redirect.headers.get("Location", "")
            match = re.fullmatch(rf"https://steamcommunity\.com/(?:ogg|app|games)/{APPS[name]}/announcements/detail/(\d+)/?", target)
            if redirect.status in (301, 302, 303, 307, 308) and match:
                url = f"https://store.steampowered.com/news/app/{APPS[name]}/view/{match[1]}"
                keys = set(item.keys) | set(identities(name, item.title, url))
                fresh.append(replace(item, url=url, keys=tuple(sorted(k for k in keys if k in item.keys or not k.startswith("auto:")))))
            else:
                raise ValueError("Unverified Steam announcement redirect")
    return fresh


def native(msg):
    return bool(msg.webhook_id and msg.flags.is_crossposted and msg.type == discord.MessageType.default)


def describe(msg, name):
    text = message_text(msg)
    titles = [e.title for e in msg.embeds if e.title]
    first_line = next((line.strip(" #*") for line in (msg.content or "").splitlines() if line.strip(" #*")), "")
    title = next((t for t in titles if t and "://" not in t), first_line)
    links = [e.url for e in msg.embeds if e.url]
    if not links:
        # A standalone link line is a source; inline historical citations are not.
        links = [line.strip(" <>") for line in (msg.content or "").splitlines()
                 if re.fullmatch(r"<?https://[^\s<>]+>?", line.strip())]
    link = links[0] if len(set(links)) == 1 else ""
    source = current_article(name, title, link)
    keys = dated_keys(identities(name, title, source), msg.created_at.timestamp())
    return text, [title] if title else [], set(keys), source


def from_follow(msg, now):
    if not native(msg):
        return None
    name = OFFICIAL_UPDATE_CHANNELS[msg.channel.id]
    text, titles, keys, source = describe(msg, name)
    strong = any(not k.startswith("auto:") for k in keys)
    # Unidentified Follow messages can still match a publisher headline in history.
    if not strong or (all(k.startswith(("auto:", "steam:", "wilds:article:")) for k in keys)
                      and not any(UPDATE.search(t) for t in titles[:2])):
        return None
    if not titles or not keys:
        return None
    original = getattr(msg.reference, "message_id", None) or msg.id
    published = discord.utils.snowflake_time(original).timestamp()
    if published > now + 60:
        return None
    title = next((t for t in titles if "://" not in t and len(t) <= 180), None)
    if not title:
        return None
    return Notice(msg.channel.id, tuple(sorted(keys)), title, excerpt(text), source or msg.jump_url, published)


def comparable_editions(left, right):
    def families(keys):
        return {k.rsplit(":", 1)[0] if ":" in k else "fc27" for k in keys
                if re.fullmatch(r"(?:[a-z0-9]+:)?(?:[0-9]+(?:\.[0-9]+)+|[0-9]{4}-[0-9]{2}-[0-9]{2})", k)}
    if any(k.startswith("hd2:platform:") for k in left) and any(k.startswith("hd2:platform:") for k in right):
        return True
    return bool(families(left) & families(right))


async def destination(channel, item, aliases, parent, since):
    """Read visible current history, including other writers' recaps, before choosing the send shape."""
    originals = set()
    references = set()
    uncertain = False
    name = OFFICIAL_UPDATE_CHANNELS[item.channel]
    count = 0
    async for msg in channel.history(limit=1001, after=since):
        count += 1
        if count > 1000:
            raise ReviewError("Incomplete history")
        text, titles, keys, _ = describe(msg, name)
        if msg.reference and msg.type == discord.MessageType.reply and re.search(r"[\u3400-\u9fff]", text):
            references.add(msg.reference.message_id)
        if msg.id != parent and not aliases.intersection(keys) and item.url not in text:
            # A relay may use a short link or a different title. Do not infer that an
            # unmatched nearby announcement lacking a comparable edition is a different release.
            if native(msg) and abs(msg.created_at.timestamp() - item.published) < 2 * 86400:
                if not any(not k.startswith("auto:") for k in keys):
                    uncertain = True
                elif any(UPDATE.search(t) for t in titles[:2]) and not comparable_editions(aliases, keys):
                    uncertain = True
            continue
        if native(msg):
            if msg.flags.has_thread or re.search(r"[\u3400-\u9fff]{5}", text):
                raise ReviewError("existing local content")
            originals.add(msg.id)
        elif re.search(r"[\u3400-\u9fff]", text):
            raise ReviewError("existing recap")
    if (uncertain and not originals) or len(originals) > 1 or originals & references or (parent and parent not in originals):
        raise ReviewError("ambiguous or missing original")
    return next(iter(originals), None)


async def deliver(cog, job):
    key, item, parent, aliases = job
    store = cog.automatic
    channel = cog.bot.get_channel(item.channel)
    if (not channel or channel.guild.id != config.GUILD_ID or cog.bot.user.id != BOT_ID
            or item.channel not in OFFICIAL_UPDATE_CHANNELS):
        raise RuntimeError("Unverified update destination")
    perms = channel.permissions_for(channel.guild.me)
    if not (perms.view_channel and perms.read_message_history and perms.send_messages):
        raise RuntimeError("Update destination unavailable")
    # Include older origins and the whole delivery window, bounded independently of server lifetime.
    since = datetime.fromtimestamp(item.published - 7 * 86400, HONG_KONG)
    async def locate():
        return await destination(channel, item, aliases, parent, since)
    try:
        await locate()
    except ReviewError:
        await asyncio.to_thread(store.finish, key, "held", from_stage="pending")
        return
    text = re.sub(r"@\S+|https?://\S+", "", item.title + "\n" + item.excerpt).strip()
    if OFFICIAL_UPDATE_CHANNELS[item.channel] != HMT:
        translated, ticket = await asyncio.to_thread(store.translation, item.url, text, time.time(),
                                                     provider_available=True, channel_id=item.channel)
        if ticket:
            translated = await cog.translate_reviewed(text, channel_id=item.channel)
            if not re.search(r"[\u3400-\u9fff]", translated):
                raise ValueError("Translation has no Chinese text")
            await asyncio.to_thread(store.cache_result, ticket, translated)
        text = translated
    day = datetime.fromtimestamp(item.published, HONG_KONG).strftime("%d/%m/%Y")
    content = f"**{OFFICIAL_UPDATE_CHANNELS[item.channel]}｜Con9sole 繁中整理**\n{day} · 來源發布日期\n{text}\n\n官方來源：<{item.url}>"
    if len(content.encode("utf-16-le")) > 4000:
        raise ValueError("Recap exceeds Discord limit")
    # Recheck after translation/network waits. A gateway callback can also attach a parent until the claim.
    try:
        found = await locate()
    except ReviewError:
        await asyncio.to_thread(store.finish, key, "held", from_stage="pending")
        return
    if not await asyncio.to_thread(store.claim_send, key, parent):
        return
    reference = discord.MessageReference(message_id=found, guild_id=channel.guild.id,
                                         channel_id=channel.id, fail_if_not_exists=True) if found else None
    sent = await channel.send(content, reference=reference, mention_author=False, silent=True,
                              allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
    await asyncio.to_thread(store.finish, key, "sent", from_stage="posting", message=sent.id)
