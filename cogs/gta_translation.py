"""Translate new followed announcements in the GTA official-updates channel."""
from __future__ import annotations

import asyncio
from html import unescape
import io
import logging
import os
import sqlite3
import time

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from core.gta_translation import GTA_CHANNEL_ID, HONG_KONG, Job, TranslationQueue, source_text
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)
ENDPOINT = "https://translation.googleapis.com/language/translate/v2"


async def translate(session: aiohttp.ClientSession, text: str) -> str:
    async with session.post(ENDPOINT, json={"q": text, "target": "zh-TW", "format": "text"},
                            allow_redirects=False) as response:
        if response.status != 200:
            response.raise_for_status()
            raise ValueError(f"Google Translation HTTP {response.status}")
        result = await response.json()
        translated = result["data"]["translations"][0]["translatedText"]
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("Google Translation returned empty text")
        return unescape(translated)


async def thread_for(message):
    if message.thread is not None:
        return message.thread
    try:
        return await message.fetch_thread()
    except discord.NotFound:
        pass
    date = discord.utils.snowflake_time(message.id).astimezone(HONG_KONG).strftime("%d/%m")
    try:
        return await message.create_thread(name=f"GTA 官方更新｜{date} 繁中翻譯")
    except discord.HTTPException as exc:
        if exc.code != 160004:  # A member or an overlapping worker created the thread first.
            raise
        return await message.fetch_thread()


async def send_translation(thread, job: Job) -> None:
    heading = "**繁體中文｜自動翻譯** · [Google Translate](https://translate.google.com/)"
    content = f"{heading}\n{job.text}"
    options = dict(allowed_mentions=discord.AllowedMentions.none(), silent=True,
                   suppress_embeds=True, nonce=job.message_id)
    if len(content.encode("utf-16-le")) <= 4000:
        await thread.send(content, **options)
    else:
        with io.BytesIO(job.text.encode("utf-8")) as data:
            await thread.send(heading, file=discord.File(data, filename="GTA-繁中翻譯.txt"), **options)


class GTATranslation(commands.Cog):
    def __init__(self, bot, store, session):
        self.bot = bot
        self.store = store
        self.session = session

    async def cog_load(self):
        self.process.start()

    async def cog_unload(self):
        self.process.cancel()
        await self.session.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (message.guild is None or message.guild.id != config.GUILD_ID
                or message.channel.id != GTA_CHANNEL_ID or not message.webhook_id
                or not message.flags.is_crossposted or message.type != discord.MessageType.default):
            return
        body = source_text(message)
        if body:
            origin = message.reference.message_id if message.reference else None
            await asyncio.to_thread(self.store.add, message.id, origin or message.id, body)

    async def process_job(self, job):
        if job.stage == "translate":
            translated = await translate(self.session, job.text)
            await asyncio.to_thread(self.store.advance, job, "deliver", translated)
            return
        channel = self.bot.get_channel(GTA_CHANNEL_ID)
        if channel is None or channel.guild.id != config.GUILD_ID:
            raise RuntimeError("Configured GTA channel unavailable")
        thread = await thread_for(channel.get_partial_message(job.message_id))
        if thread.id != job.message_id or thread.parent_id != GTA_CHANNEL_ID:
            raise RuntimeError("Unexpected GTA translation thread")
        # Discord may have accepted a timed-out send. Claim it durably before posting;
        # do not auto-send an ambiguous result, even after a restart.
        if not await asyncio.to_thread(self.store.start_posting, job):
            return
        try:
            await send_translation(thread, job)
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
                log.warning("GTA translation issue message=%s stage=%s attempt=%s error=%s status=%s",
                            job.message_id if job else None, job.stage if job else "claim",
                            job.attempt if job else None, type(exc).__name__, getattr(exc, "status", None))
                return

    @process.before_loop
    async def before_process(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    key = os.getenv("GTA_TRANSLATION_API_KEY")
    if key:
        store = await asyncio.to_thread(TranslationQueue, DATA_DIR / "gta_translation.sqlite3")
        session = aiohttp.ClientSession(headers={"X-Goog-Api-Key": key},
                                        timeout=aiohttp.ClientTimeout(total=20))
        try:
            await bot.add_cog(GTATranslation(bot, store, session))
        except BaseException:
            await session.close()
            raise
