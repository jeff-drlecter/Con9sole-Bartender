# cogs/twitch_relay.py  (DEBUG build, loopback-safe)
# 雙向 Twitch <-> Discord；只讀 Fly Secrets；詳盡日誌；帶去重與 loopback 防護
# 依賴：discord.py v2、twitchio==2.8.2

import os
import json
import asyncio
import logging
import time
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

# ---- 簡單去重 cache：{ (discord_ch_id, text) : expire_ts } ----
_recent_send: Dict[Tuple[int, str], float] = {}
DEDUP_TTL_SEC = 6.0

def _norm_text(s: str) -> str:
    """標準化文字：strip、移除零寬字元/全形空白、合併多空白"""
    if not s:
        return ""
    # 常見零寬 & 方向控制
    ZERO_WIDTH = [
        "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
        "\u2061", "\u2062", "\u2063", "\u2064",
    ]
    for z in ZERO_WIDTH:
        s = s.replace(z, "")
    s = s.replace("\u3000", " ")  # 全形空白
    s = s.strip()
    # 收斂連續空白
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def _seen_recent(discord_ch_id: int, text: str) -> bool:
    """6 秒內重覆內容則視作已見過"""
    now = time.time()
    # 清過期
    dead = [k for k, exp in _recent_send.items() if exp <= now]
    for k in dead:
        _recent_send.pop(k, None)
    key = (discord_ch_id, text)
    if key in _recent_send and _recent_send[key] > now:
        return True
    _recent_send[key] = now + DEDUP_TTL_SEC
    return False


class TwitchRelay(commands.Cog):
    """雙向 Twitch <-> Discord（Debug 版，帶 loopback 防護）"""

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
                    # ① 官方旗標：自己送出的訊息
                    if getattr(message, "echo", False):
                        return

                    # ② 作者名就係本 bot 自己
                    try:
                        if (message.author and message.author.name
                                and self.nick
                                and message.author.name.lower() == self.nick.lower()):
                            return
                    except Exception:
                        pass

                    # ③ Discord→Twitch 的訊息（我們會加 TAG_DISCORD）——防回射
                    text_raw = message.content or ""
                    text_norm = _norm_text(text_raw)
                    if text_norm.startswith(TAG_DISCORD):
                        return

                    dch = await _safe_get_messageable_channel(cog_self.bot, self.discord_channel_id)
                    if not dch:
                        log.error("❌ [T→D] 解析不到 Discord 頻道 id=%s", self.discord_channel_id)
                        return

                    author = message.author.display_name or message.author.name
                    content = f"{TAG_TWITCH} {author}: {text_norm}"

                    # ④ 去重：避免短時間重覆
                    if _seen_recent(self.discord_channel_id, content):
                        log.info("⏩ [T→D] duplicate skipped")
                        return

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
        text = _norm_text(message.content)
        if not text:
            return

        log.info("📥 [D→T recv] ch=%s(id=%s,type=%s) | %s",
                 getattr(message.channel, 'name', 'unknown'),
                 message.channel.id,
                 type(message.channel).__name__,
                 text)

        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"

            # 1) 等 Twitch bot 準備好
            try:
                await tbot.wait_for_ready()
            except Exception:
                pass

            # 2) 嘗試從已連結頻道中找目標
            chan = None
            if getattr(tbot, "connected_channels", None):
                for c in tbot.connected_channels:
                    if getattr(c, "name", "").lower() == twitch_channel.lower():
                        chan = c
                        break

            # 3) 若未找到，嘗試加入
            if chan is None:
                try:
                    await tbot.join_channels([twitch_channel])
                    log.info("🔁 [D→T] join_channels -> #%s", twitch_channel)
                except Exception as e:
                    log.warning("⚠️ [D→T] join_channels 失敗：%s", e)
                if getattr(tbot, "connected_channels", None):
                    for c in tbot.connected_channels:
                        if getattr(c, "name", "").lower() == twitch_channel.lower():
                            chan = c
                            break

            if chan is None:
                log.error("❌ [D→T] 找不到/未加入 Twitch #%s（檢查 token 是否含 chat:edit）", twitch_channel)
                return

            await chan.send(payload)
            log.info("✅ [D→T send] #%s | %s", twitch_channel, payload)

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
    log.info("🧩 TwitchRelay Cog 已載入（Debug 版，loopback-safe）")
