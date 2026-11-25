"""Translate new followed announcements in the GTA official-updates channel."""
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
from core.gta_translation import GTA_CHANNEL_ID, HONG_KONG, Job, TranslationQueue, source_text
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)
SCRIPT_URL = re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec")
RESULT_URL = re.compile(r"https://script\.googleusercontent\.com/macros/echo\?[^#\s]+")
# A complete, generic noun phrase. Leave named models and compounds such as
# "a vehicle warehouse" to the translator.
GENERIC_VEHICLE = re.compile(r"\ba vehicle\b(?=\s*(?:$|[,.!?:;)]|\b(?:and|or)\b))", re.I)
VEHICLE_MARKER = "GTA0V"


class TranslationLimit(Exception):
    pass


async def translate(session: aiohttp.ClientSession, url: str, token: str, text: str) -> str:
    source, protected = text, 0
    if VEHICLE_MARKER.casefold() not in text.casefold():
        source, protected = GENERIC_VEHICLE.subn(VEHICLE_MARKER, text)
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
    if protected:
        if translated.count(VEHICLE_MARKER) != protected:
            raise ValueError("Apps Script changed a protected GTA term")
        translated = translated.replace(VEHICLE_MARKER, "一輛載具")
    return translated


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
                or message.channel.id != GTA_CHANNEL_ID or not message.webhook_id
                or not message.flags.is_crossposted or message.type != discord.MessageType.default):
            return
        body = source_text(message)
        if body:
            origin = message.reference.message_id if message.reference else None
            await asyncio.to_thread(self.store.add, message.id, origin or message.id, body)

    async def process_job(self, job):
        if job.stage == "translate":
            try:
                translated = await translate(self.session, self.url, self.token, job.text)
            except TranslationLimit as exc:
                await asyncio.to_thread(self.store.defer_quota, job, str(exc), time.time())
                return
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
