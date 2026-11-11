"""Opt-in RSS publisher; RSS_DELIVERY_SOURCES is empty by default."""
from __future__ import annotations

import asyncio
import logging
import json
from pathlib import Path
import os
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.rss_delivery import enabled_sources
from core.rss_digest import DigestConfig, DigestStore, OFFER_LABELS, HK, excerpt, display_link
from datetime import datetime
from core.rss_trial import MAX_BYTES, SOURCES, parse_feed
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)


class RSSDelivery(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sources = enabled_sources(os.getenv("RSS_DELIVERY_SOURCES", ""))
        config_path = os.getenv("RSS_DIGEST_CONFIG", "")
        data = {}
        if config_path:
            raw = Path(config_path).read_bytes()
            if len(raw) > 65536:
                raise ValueError("digest config exceeds 64 KiB")
            data = json.loads(raw)
        self.digest_config = DigestConfig.from_dict(data)
        self.store = None
        self.session = None
        self.errors = {}

    async def cog_load(self):
        if not self.sources:
            return
        self.store = DigestStore(DATA_DIR / "rss_delivery.sqlite3")
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

    @staticmethod
    def render(batch, now):
        reminder = batch['kind'] == 'reminder'
        title = ('⏰ 今日到期提醒' if reminder else '🎮 今日遊戲情報')
        title += '｜' + datetime.fromtimestamp(now, HK).strftime('%m/%d')
        embed = discord.Embed(title=title)
        for article in batch['articles']:
            source = {'ps':'🔵 PS', 'xbox':'🟢 Xbox', '4gamers':'💻 綜合遊戲'}[article['source']]
            name = source + '｜' + discord.utils.escape_markdown(excerpt(article['title'], 80))
            description = discord.utils.escape_markdown(excerpt(article['summary'], 150))
            offer = article.get('offer')
            if offer:
                description = (f"{OFFER_LABELS[offer['kind']]}｜{discord.utils.escape_markdown(offer['region'])}"
                               f"｜截止 <t:{int(offer['deadline'])}:f>\n" + description)
            # Encoding brackets prevents external URLs from changing Markdown structure.
            link = '[原文／領取詳情](<' + display_link(article['link']) + '>)'
            value = description[:max(0, 599-len(link))] + '\n' + link
            embed.add_field(name=name[:100], value=value, inline=False)
        embed.set_footer(text='來源內容節錄 · 香港時間 · 非即時逐篇推送')
        return embed

    @tasks.loop(minutes=1)
    async def deliver(self):
        if not self.digest_config.enabled:
            return
        channel = self.bot.get_channel(self.digest_config.channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel) or channel.guild.id != config.GUILD_ID or channel.guild.me is None:
            self.errors['digest'] = 'target channel unavailable'
            return
        permissions = channel.permissions_for(channel.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            self.errors['digest'] = 'missing View Channel / Send Messages / Embed Links'
            return
        try:
            batch = await asyncio.to_thread(self.store.claim_batch, self.digest_config, self.sources, time.time())
        except Exception:
            log.exception('RSS digest claim failed')
            return
        if batch is None:
            return
        outcome, detail = 'sent', ''
        try:
            message = await channel.send(embed=self.render(batch, time.time()), allowed_mentions=discord.AllowedMentions.none())
            detail = str(message.id)
        except discord.HTTPException as exc:
            outcome = 'retry' if exc.status == 429 else 'uncertain' if exc.status >= 500 else 'failed'
            detail = f'HTTP {exc.status}'
        except Exception as exc:
            outcome, detail = 'uncertain', type(exc).__name__
            log.warning('RSS digest send: %s', detail)
        try:
            await asyncio.to_thread(self.store.finish_batch, batch['slot'], outcome, time.time(), detail)
        except Exception:
            log.exception('RSS digest finalization failed; reserved batch will not be resent')

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
        lines = ["RSS 摘要：" + ("已啟用" if self.sources and self.digest_config.enabled else "公開派送關閉"),
                 "來源：" + (", ".join(sorted(self.sources)) or "未啟用收集"),
                 "19:00 每日摘要（最多 8 條）；12:30 只提醒晚間前到期嘅已核實優惠。"]
        if self.store:
            for source, state, count in await asyncio.to_thread(self.store.report):
                lines.append(f"{source} · {state}: {count}")
            for name, state, attempts in await asyncio.to_thread(self.store.batch_report):
                lines.append(f"{name} · {state} · {attempts} 次嘗試")
        for source, error in self.errors.items():
            lines.append(f"{source}: {error}")
        lines.append("sending／uncertain 要先核對 Discord 訊息；不會自動補發。")
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="rss_digest_preview", description="私人預覽下一份 RSS 摘要，不會發佈或清空佇列")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.store:
            await interaction.followup.send("未啟用 RSS 收集，暫無摘要。", ephemeral=True)
            return
        now = time.time()
        articles = await asyncio.to_thread(self.store.preview, self.digest_config, self.sources, now)
        if not articles:
            await interaction.followup.send("目前冇符合篩選嘅新內容；唔會發空摘要。", ephemeral=True)
            return
        await interaction.followup.send(embed=self.render({'kind':'digest','articles':articles}, now),
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(RSSDelivery(bot))
