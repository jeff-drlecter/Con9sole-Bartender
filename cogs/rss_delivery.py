"""Opt-in RSS publisher; RSS_DELIVERY_SOURCES is empty by default."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.rss_delivery import DeliveryStore, enabled_sources
from core.rss_trial import MAX_BYTES, SOURCES, parse_feed
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)


class RSSDelivery(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sources = enabled_sources(os.getenv("RSS_DELIVERY_SOURCES", ""))
        self.store = None
        self.session = None
        self.errors = {}

    async def cog_load(self):
        if not self.sources:
            return
        self.store = DeliveryStore(DATA_DIR / "rss_delivery.sqlite3")
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
                                            headers={"User-Agent": "Con9sole-Bartender RSS/1.0"},
                                            cookie_jar=aiohttp.DummyCookieJar(), trust_env=False)
        self.poll.start()
        self.deliver.start()

    async def cog_unload(self):
        self.poll.cancel()
        self.deliver.cancel()
        if self.session:
            await self.session.close()

    @tasks.loop(minutes=20)
    async def poll(self):
        for source, url, _ in SOURCES:
            if source not in self.sources:
                continue
            try:
                async with self.session.get(url, max_redirects=5) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError("feed exceeds 2 MiB decompressed limit")
                articles = await asyncio.to_thread(parse_feed, bytes(body))
                await asyncio.to_thread(self.store.ingest, source, articles, time.time())
                self.errors.pop(source, None)
            except Exception as exc:
                self.errors[source] = type(exc).__name__ + ": " + str(exc)[:180]
                log.warning("RSS delivery poll %s: %s", source, self.errors[source])

    @tasks.loop(seconds=30)
    async def deliver(self):
        # At most one article per source per cycle; no translations or mentions.
        for source, _, channel_id in SOURCES:
            if source not in self.sources:
                continue
            channel = self.bot.get_channel(channel_id)
            if channel is None or not isinstance(channel, discord.TextChannel) or channel.guild.id != config.GUILD_ID or channel.guild.me is None:
                self.errors[source] = "target channel unavailable"
                continue
            permissions = channel.permissions_for(channel.guild.me)
            if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
                self.errors[source] = "missing View Channel / Send Messages / Embed Links"
                continue
            try:
                article = await asyncio.to_thread(self.store.claim, source, time.time())
            except Exception:
                log.exception("RSS queue claim failed for %s", source)
                continue
            if article is None:
                continue
            embed = discord.Embed(title=article['title'][:256] or "遊戲消息",
                                  url=article['link'], description=article['summary'][:1500])
            embed.set_footer(text={"ps":"PlayStation Blog", "xbox":"Xbox Wire", "4gamers":"4Gamers"}[source])
            outcome, detail = "sent", ""
            try:
                message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                detail = str(message.id)
            except discord.HTTPException as exc:
                # Retry only a definitive rate-limit refusal. A 5xx may have accepted
                # the message; uncertain sends require inspection, not duplication.
                outcome = "retry" if exc.status == 429 else "uncertain" if exc.status >= 500 else "failed"
                detail = f"HTTP {exc.status}"
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                outcome, detail = "uncertain", type(exc).__name__
            except Exception as exc:
                outcome, detail = "uncertain", type(exc).__name__
                log.exception("RSS send failed for %s", source)
            try:
                await asyncio.to_thread(self.store.finish, source, article['key'], outcome, time.time(), detail)
            except Exception:
                # Reserved 'sending' state remains and will not be retried on restart.
                log.exception("RSS queue finalization failed for %s", source)

    @poll.before_loop
    @deliver.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="rss_delivery_status", description="查看 RSS 正式派送狀態（管理員）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = ["RSS 正式派送：" + (", ".join(sorted(self.sources)) or "未啟用"),
                 "每來源最多 50 次派送嘗試／24 小時；首次讀取只建立基準。"]
        if self.store:
            for source, state, count in await asyncio.to_thread(self.store.report):
                lines.append(f"{source} · {state}: {count}")
        for source, error in self.errors.items():
            lines.append(f"{source}: {error}")
        lines.append("sending／uncertain 要先核對 Discord 訊息；不會自動補發。")
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(RSSDelivery(bot))
