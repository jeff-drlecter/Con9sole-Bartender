# cogs/twitch_relay.py  (DEBUG build)
# 雙向 Twitch <-> Discord 聊天橋接；只讀 Fly.io Secrets；詳盡日誌。
# 依賴：discord.py v2、twitchio==2.8.2
#
# TWITCH_RELAY_CONFIG 例子（Fly Secrets）：
# [
#   {"twitch_channel":"jeff_con9sole","twitch_oauth":"oauth:AAA111","discord_channel_id":"123456789012345678"},
#   {"twitch_channel":"teammateA","twitch_oauth":"oauth:BBB222","discord_channel_id":"234567890123456789"}
# ]

import os
import json
import asyncio
import logging
from typing import Dict, Tuple, Optional, Union

import discord
from discord.ext import commands
from discord.abc import Messageable
from discord import TextChannel, VoiceChannel, StageChannel

from twitchio.ext import commands as twitch_commands

log = logging.getLogger("twitch-relay")

RAW_CONFIG = os.getenv("TWITCH_RELAY_CONFIG", "[]")
try:
    RELAY_CONFIG = json.loads(RAW_CONFIG)
    if not isinstance(RELAY_CONFIG, list):
        raise ValueError("TWITCH_RELAY_CONFIG 必須為 JSON array")
except Exception as e:
    log.error("❌ 讀取 TWITCH_RELAY_CONFIG 失敗：%s", e)
    RELAY_CONFIG = []

TAG_TWITCH  = "[Twitch]"
TAG_DISCORD = "[Discord]"

MessageableChannel = Union[TextChannel, VoiceChannel, StageChannel, Messageable]


class TwitchRelay(commands.Cog):
    """雙向 Twitch <-> Discord（Debug 版，會輸出詳細日誌）"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # discord_channel_id -> (twitch_channel, twitch_bot)
        self.discord_map: Dict[int, Tuple[str, twitch_commands.Bot]] = {}
        # twitch_channel(lower) -> discord_channel_id
        self.twitch_map: Dict[str, int] = {}

        log.info("🔧 RelayBoot: 已載入 %d 條配置", len(RELAY_CONFIG))
        for i, e in enumerate(RELAY_CONFIG, start=1):
            safe = {
                "twitch_channel": e.get("twitch_channel"),
                "discord_channel_id": e.get("discord_channel_id"),
                "twitch_oauth": "oauth:***hidden***" if e.get("twitch_oauth") else None,
            }
            log.info("🔧 RelayBoot: #%d %s", i, safe)

        self._connect_all_from_secrets()

    # === 建立 Twitch 連線 ===
    def _connect_all_from_secrets(self) -> None:
        loop = asyncio.get_event_loop()

        for entry in RELAY_CONFIG:
            try:
                twitch_channel = str(entry["twitch_channel"])
                twitch_oauth   = str(entry["twitch_oauth"])
                discord_ch_id  = int(entry["discord_channel_id"])
            except Exception as e:
                log.warning("⚠️ 配置格式錯誤，已略過：%s | err=%s", entry, e)
                continue

            cog_self = self

            class _TwitchBot(twitch_commands.Bot):
                def __init__(self):
                    super().__init__(
                        token=twitch_oauth,
                        prefix="!",
                        initial_channels=[twitch_channel],
                    )
                    self.discord_channel_id = discord_ch_id
                    self.twitch_channel_name = twitch_channel

                async def event_ready(self):
                    log.info("🟣 [T] Connected as %s -> #%s", self.nick, self.twitch_channel_name)

                async def event_message(self, message):
                    # Twitch 會將自己發出的訊息標記為 echo
                    if message.echo:
                        return

                    dch = await _safe_get_messageable_channel(cog_self.bot, self.discord_channel_id)
                    if not dch:
                        log.error("❌ [T→D] 解析不到 Discord 頻道 id=%s", self.discord_channel_id)
                        return

                    author = message.author.display_name or message.author.name
                    text = message.content
                    content = f"{TAG_TWITCH} {author}: {text}"
                    try:
                        await dch.send(content)
                        log.info("✅ [T→D] -> %s(id=%s,type=%s): %s",
                                 getattr(dch, 'name', 'unknown'),
                                 getattr(dch, 'id', 'n/a'),
                                 type(dch).__name__,
                                 content)
                    except Exception as e:
                        log.exception("❌ [T→D] send 失敗：%s", e)

            tbot = _TwitchBot()

            self.discord_map[discord_ch_id] = (twitch_channel, tbot)
            self.twitch_map[twitch_channel.lower()] = discord_ch_id

            loop.create_task(tbot.connect())
            log.info("🔌 啟動 Twitch 連線：#%s -> Discord(%s)", twitch_channel, discord_ch_id)

    # === Discord -> Twitch ===
    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        # 忽略 bot、DM、無內容
        if message.author.bot or not message.guild or not message.content:
            return

        pair = self.discord_map.get(message.channel.id)
        if not pair:
            return  # 非橋接頻道

        # 防回圈：T→D 轉過來已帶 TAG_TWITCH，不回射
        if message.content.startswith(TAG_TWITCH):
            return

        twitch_channel, tbot = pair
        text = message.content.strip()
        if not text:
            return

        log.info("📥 [D→T recv] ch=%s(id=%s,type=%s) | %s",
                 getattr(message.channel, 'name', 'unknown'),
                 message.channel.id,
                 type(message.channel).__name__,
                 text)

        # 等連線（不同 twitchio 版本未必有 wait_for_ready，失敗略過）
        try:
            await tbot.wait_for_ready()
        except Exception:
            pass

        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"
            if getattr(tbot, "connected_channels", None):
                await tbot.connected_channels[0].send(payload)
                log.info("✅ [D→T send] #%s | %s", twitch_channel, payload)
            else:
                # 後備（不同版本 API 或會不可用）
                await tbot.connected_channels[0].send(payload)
                log.info("✅ [D→T send-fallback] #%s | %s", twitch_channel, payload)
        except Exception as e:
            log.exception("❌ [D→T] send 失敗：%s", e)


# === 工具：解析可發訊息的頻道（Text / Voice / Stage 的聊天） ===
async def _safe_get_messageable_channel(
    bot: commands.Bot, channel_id: int
) -> Optional[MessageableChannel]:
    ch = bot.get_channel(channel_id)
    if isinstance(ch, (TextChannel, VoiceChannel, StageChannel, Messageable)):
        return ch
    try:
        ch = await bot.fetch_channel(channel_id)
        if isinstance(ch, (TextChannel, VoiceChannel, StageChannel, Messageable)):
            return ch
    except Exception:
        pass
    return None


async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchRelay(bot))
    log.info("🧩 TwitchRelay Cog 已載入（Debug 版）")
