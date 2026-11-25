"""Translate followed announcements in the club's game-specific update channels."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import sqlite3
import time

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from core.gta_translation import (
    GTA_CHANNEL_ID, OFFICIAL_UPDATE_CHANNELS, Job, TranslationQueue, source_text, translation_input,
)
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)
SCRIPT_URL = re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec")
RESULT_URL = re.compile(r"https://script\.googleusercontent\.com/macros/echo\?[^#\s]+")


class TranslationLimit(Exception):
    pass


async def translate(session: aiohttp.ClientSession, url: str, token: str, text: str,
                    *, channel_id: int = GTA_CHANNEL_ID) -> str:
    source, replacements = translation_input(text, channel_id)
    async with session.post(url, json={"text": source, "token": token},
                            allow_redirects=False) as response:
        if response.status in (302, 303):
            location = response.headers.get("Location", "")
            if not RESULT_URL.fullmatch(location):
                raise ValueError("Unexpected Apps Script result location")
            # ContentService redirects to a one-use result URL. No POST body or credentials on GET.
            async with session.get(location, allow_redirects=False) as output:
                if output.status != 200:
                    raise ValueError("Apps Script result unavailable")
                result = await output.json()
        elif response.status == 200:
            result = await response.json()
        else:
            response.raise_for_status()
            raise ValueError("Unexpected Apps Script response")
    if not isinstance(result, dict):
        raise ValueError("Unexpected Apps Script result")
    if result.get("error") in ("daily_limit", "month_full"):
        raise TranslationLimit(result["error"])
    translated = result.get("translation")
    if not isinstance(translated, str) or not translated.strip():
        raise ValueError("Apps Script returned no translation")
    if replacements:
        if any(translated.count(marker) != source.count(marker) for marker in replacements):
            raise ValueError("Apps Script changed a protected translation marker")
        # One pass: literal text in one original URL cannot expand into another URL.
        translated = re.sub("|".join(replacements), lambda m: replacements[m[0]], translated)
    return translated


async def reply_with_translation(channel, job: Job) -> None:
    heading = "**繁體中文｜自動翻譯** · [Google Translate](https://translate.google.com/)"
    content = f"{heading}\n{job.text}"
    reference = discord.MessageReference(message_id=job.message_id, channel_id=job.channel_id,
                                         guild_id=channel.guild.id, fail_if_not_exists=True)
    options = dict(reference=reference, mention_author=False, allowed_mentions=discord.AllowedMentions.none(), silent=True,
                   suppress_embeds=True, nonce=job.message_id)
    if len(content.encode("utf-16-le")) <= 4000:
        await channel.send(content, **options)
    else:
        with io.BytesIO(job.text.encode("utf-8")) as data:
            game = OFFICIAL_UPDATE_CHANNELS[job.channel_id]
            await channel.send(heading, file=discord.File(data, filename=f"{game}-繁中翻譯.txt"), **options)


class GTATranslation(commands.Cog):
    def __init__(self, bot, store, session, url, token):
        self.bot = bot
        self.store = store
        self.session = session
        self.url = url
        self.token = token

    async def cog_load(self):
        self.process.start()

    async def cog_unload(self):
        self.process.cancel()
        await self.session.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (message.guild is None or message.guild.id != config.GUILD_ID
                or message.channel.id not in OFFICIAL_UPDATE_CHANNELS or not message.webhook_id
                or not message.flags.is_crossposted or message.type != discord.MessageType.default):
            return
        body = source_text(message)
        if body:
            origin = message.reference.message_id if message.reference else None
            await asyncio.to_thread(self.store.add, message.id, origin or message.id, body,
                                    channel_id=message.channel.id)

    async def process_job(self, job):
        if job.channel_id not in OFFICIAL_UPDATE_CHANNELS:
            raise ValueError("Unknown official update channel")
        if job.stage == "translate":
            try:
                translated = await translate(self.session, self.url, self.token, job.text, channel_id=job.channel_id)
            except TranslationLimit as exc:
                await asyncio.to_thread(self.store.defer_quota, job, str(exc), time.time())
                return
            await asyncio.to_thread(self.store.advance, job, "deliver", translated)
            return
        channel = self.bot.get_channel(job.channel_id)
        if channel is None or channel.id != job.channel_id or channel.guild.id != config.GUILD_ID:
            raise RuntimeError("Configured official update channel unavailable")
        # Discord may have accepted a timed-out send. Claim it durably before posting;
        # do not auto-send an ambiguous result, even after a restart.
        if not await asyncio.to_thread(self.store.start_posting, job):
            return
        try:
            await reply_with_translation(channel, job)
        except discord.HTTPException as exc:
            if 400 <= exc.status < 500:
                await asyncio.to_thread(self.store.rejected, job)
            raise
        await asyncio.to_thread(self.store.sent, job.message_id)

    @tasks.loop(seconds=10)
    async def process(self):
        for _ in range(8):
            job = None
            try:
                job = await asyncio.to_thread(self.store.claim, time.time())
                if job is None:
                    return
                await self.process_job(job)
            except (aiohttp.ClientError, TimeoutError, discord.DiscordException, ValueError,
                    KeyError, IndexError, TypeError, RuntimeError, sqlite3.Error) as exc:
                # Never log Google headers, a response body or source content.
                log.warning("Game translation issue channel=%s message=%s stage=%s attempt=%s error=%s status=%s",
                            job.channel_id if job else None, job.message_id if job else None, job.stage if job else "claim",
                            job.attempt if job else None, type(exc).__name__, getattr(exc, "status", None))
                return

    @process.before_loop
    async def before_process(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    url = os.getenv("GTA_TRANSLATION_SCRIPT_URL")
    token = os.getenv("GTA_TRANSLATION_TOKEN")
    if url or token:
        if not SCRIPT_URL.fullmatch(url or "") or not re.fullmatch(r"[a-f0-9]{64}", token or ""):
            raise ValueError("Incomplete or invalid GTA Apps Script configuration")
        store = await asyncio.to_thread(TranslationQueue, DATA_DIR / "gta_translation.sqlite3")
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
        try:
            await bot.add_cog(GTATranslation(bot, store, session, url, token))
        except BaseException:
            await session.close()
            raise
