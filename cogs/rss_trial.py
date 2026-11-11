from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.rss_trial import MAX_BYTES, SOURCES, TRIAL_SECONDS, TrialStore, parse_feed
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)


def memory_bytes():
    """Linux process current/peak RSS, not Fly billing or whole VM memory."""
    try:
        fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        return tuple(int(fields[name].split()[0]) * 1024 for name in ("VmRSS", "VmHWM"))
    except (OSError, ValueError, KeyError):
        return 0, 0


class RSSTrial(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = TrialStore(DATA_DIR / "rss_trial.sqlite3")
        self.validators = {}

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
                                            headers={"User-Agent": "Con9sole-Bartender RSS shadow trial/1.0"},
                                            cookie_jar=aiohttp.DummyCookieJar(), trust_env=False)
        self.poll.start()

    async def cog_unload(self):
        self.poll.cancel()
        await self.session.close()

    @tasks.loop(minutes=20)
    async def poll(self):
        if not self.store.active() or os.getenv("RSS_TRIAL_STOP") == "1":
            log.info("RSS shadow trial stopped/expired; no articles delivered")
            self.poll.stop()
            return
        for source, url, _channel_id in SOURCES:
            started = time.monotonic()
            size = 0
            resolved = url
            articles = []
            status = "ok"
            try:
                async with self.session.get(url, headers=self.validators.get(source, {}), max_redirects=5) as response:
                    resolved = str(response.url)
                    if response.status == 304:
                        status = "not_modified"
                    else:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.content.iter_chunked(16384):
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError("feed exceeds 2 MiB decompressed limit")
                            body.extend(chunk)
                        articles = await asyncio.to_thread(parse_feed, bytes(body))
                        headers = {}
                        for name, target in (("ETag", "If-None-Match"), ("Last-Modified", "If-Modified-Since")):
                            if response.headers.get(name):
                                headers[target] = response.headers[name]
                        self.validators[source] = headers
            except Exception as exc:
                status = type(exc).__name__ + ": " + str(exc)[:180]
                log.warning("RSS trial %s failed: %s", source, status)
            rss, peak = memory_bytes()
            count = self.store.record(source, articles, status=status, size=size,
                                      seconds=time.monotonic() - started, rss_bytes=rss,
                                      peak_bytes=peak, resolved_url=resolved)
            log.info("RSS trial source=%s status=%s new=%s bytes=%s process_rss=%s peak=%s", source, status, count, size, rss, peak)

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="rss_trial_status", description="查看 RSS 只讀試行結果（不會公開發送新聞）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        report = self.store.report()
        end = int(report["start"] + TRIAL_SECONDS)
        lines = [f"RSS 只讀試行｜{'運行中' if self.poll.is_running() and self.store.active() else '已停止'}", f"到期：<t:{end}:F>",
                 "Steam 停用；公開派送 0；翻譯 API 0。", "首次成功讀取只建立基準，不補發舊聞。"]
        for source, count, size, rss, peak, errors in report["polls"]:
            lines.append(f"{source}: {count} 次檢查／錯誤 {errors}／讀取 {size/1024:.0f} KiB／程序 RAM {rss/1048576:.1f} MiB／峰值 {peak/1048576:.1f} MiB")
        for source, error in report["last_errors"]:
            lines.append(f"{source} 最近一次錯誤（歷史）：{error[:180]}")
        for source, verdict, count in report["decisions"]:
            lines.append(f"{source} · {verdict}: {count}")
        lines.append("RAM 為整個 Bot 程序，並非 RSS 增量或整部 Fly VM；無法由此計算帳單。")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(RSSTrial(bot))
