# cogs/twitch_relay.py — Unified Twitch Bot (DEBUG + de-dup + loopback-safe)
# 依賴：discord.py v2、twitchio==2.8.2
# Secrets（Fly GUI 設定）：
#   TWITCH_BOT_USERNAME : 例如 "con9sole_bot"
#   TWITCH_BOT_OAUTH    : 例如 "oauth:xxxxxxxx"  (必含 chat:read + chat:edit)
#   TWITCH_RELAY_CONFIG : JSON array（無 oauth）：
#     [
#       {"twitch_channel":"jeff_con9sole","discord_channel_id":"1424..."},
#       {"twitch_channel":"siuq4me","discord_channel_id":"1424..."}
#     ]

import os, json, asyncio, logging, time
from typing import Dict, Tuple, Optional, Union

import discord
from discord.ext import commands
from discord.abc import Messageable
from discord import TextChannel, VoiceChannel, StageChannel

from twitchio.ext import commands as twitch_commands

log = logging.getLogger("twitch-relay")

# ---------- Load secrets ----------
BOT_USERNAME = os.getenv("TWITCH_BOT_USERNAME", "").strip()
BOT_OAUTH    = os.getenv("TWITCH_BOT_OAUTH", "").strip()
RAW_CONFIG   = os.getenv("TWITCH_RELAY_CONFIG", "[]")

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

# ---- 去重 cache ----
_recent_td: Dict[Tuple[int, str], float] = {}           # (discord_ch_id, content) -> expire
_recent_tw_ids: Dict[str, float] = {}                   # twitch message id -> expire
DEDUP_TD_TTL = 8.0
DEDUP_TW_TTL = 8.0

def _norm_text(s: str) -> str:
    if not s:
        return ""
    for z in ["\u200b","\u200c","\u200d","\u2060","\ufeff","\u2061","\u2062","\u2063","\u2064"]:
        s = s.replace(z, "")
    s = s.replace("\u3000", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def _seen_recent_td(ch_id: int, content: str) -> bool:
    now = time.time()
    for k, exp in list(_recent_td.items()):
        if exp <= now:
            _recent_td.pop(k, None)
    key = (ch_id, content)
    if key in _recent_td and _recent_td[key] > now:
        return True
    _recent_td[key] = now + DEDUP_TD_TTL
    return False

def _seen_recent_tw(msg_id: Optional[str]) -> bool:
    if not msg_id:
        return False
    now = time.time()
    for k, exp in list(_recent_tw_ids.items()):
        if exp <= now:
            _recent_tw_ids.pop(k, None)
    if msg_id in _recent_tw_ids and _recent_tw_ids[msg_id] > now:
        return True
    _recent_tw_ids[msg_id] = now + DEDUP_TW_TTL
    return False


class TwitchRelay(commands.Cog):
    """單一 Twitch Bot，支援多個 Twitch channel ↔ 指定 Discord channel"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Discord -> Twitch 映射：discord_channel_id -> twitch_channel
        self.d2t_map: Dict[int, str] = {}
        # Twitch -> Discord 映射：twitch_channel(lower) -> discord_channel_id
        self.t2d_map: Dict[str, int] = {}

        # 讀配置
        for i, e in enumerate(RELAY_CONFIG, start=1):
            try:
                tchan = str(e["twitch_channel"]).strip()
                dcid  = int(e["discord_channel_id"])
            except Exception as ex:
                log.warning("⚠️ 配置 #%d 格式錯誤，略過：%s (%s)", i, e, ex)
                continue
            self.d2t_map[dcid] = tchan
            self.t2d_map[tchan.lower()] = dcid

        log.info("🔧 RelayBoot: 載入 %d 條映射", len(self.d2t_map))
        for t, d in self.t2d_map.items():
            log.info("   - #%s  <->  Discord(%s)", t, d)

        # 準備 TwitchIO Bot（單一）
        if not BOT_OAUTH:
            log.error("❌ 缺少 TWITCH_BOT_OAUTH，無法啟動 Twitch bot")
            return

        initial = list({ch for ch in self.t2d_map.keys()})  # 去重
        class _UnifiedTwitchBot(twitch_commands.Bot):
            async def event_ready(self_inner):
                log.info("🟣 [T] Connected as %s", self_inner.nick)
                # 確保全部 channel 已加入（initial_channels 之外再保險 join）
                try:
                    await self_inner.join_channels(initial)
                    log.info("🔁 確認 join_channels：%s", ",".join(initial))
                except Exception as e:
                    log.warning("⚠️ join_channels 失敗：%s", e)

            async def event_message(self_inner, message):
                # 忽略自己 / loopback 標籤
                if getattr(message, "echo", False):
                    return
                try:
                    if (message.author and message.author.name and self_inner.nick and
                            message.author.name.lower() == self_inner.nick.lower()):
                        return
                except Exception:
                    pass

                text = _norm_text(message.content or "")
                if text.startswith(TAG_DISCORD):
                    return

                # 只轉發有配置嘅頻道
                try:
                    ch_name = (getattr(message.channel, "name", "") or "").lower()
                except Exception:
                    ch_name = ""
                if ch_name not in self.t2d_map:
                    return

                # 去重（twitch message id）
                msg_id = None
                try:
                    tags = getattr(message, "tags", {}) or {}
                    msg_id = str(tags.get("id")) if "id" in tags else None
                except Exception:
                    msg_id = None
                if _seen_recent_tw(msg_id or f"{ch_name}:{message.author.name}:{text}"):
                    log.info("⏩ [T→D] duplicate skipped (tw)")
                    return

                # 送去對應 Discord channel
                dch_id = self.t2d_map.get(ch_name)
                dch = await _safe_get_messageable_channel(self.bot, dch_id)
                if not dch:
                    log.error("❌ [T→D] 找不到 Discord 頻道 id=%s", dch_id)
                    return

                author = message.author.display_name or message.author.name
                content = f"{TAG_TWITCH} {author}: {text}"

                # 二次去重（同頻道同內容）
                if _seen_recent_td(dch_id, content):
                    log.info("⏩ [T→D] duplicate skipped (td)")
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

        self.twitch_bot = _UnifiedTwitchBot(
            token=BOT_OAUTH,
            prefix="!",
            initial_channels=initial or None
        )

        # 啟動連線
        loop = asyncio.get_event_loop()
        loop.create_task(self.twitch_bot.connect())
        log.info("🔌 啟動統一 Twitch 連線：%s", ",".join(initial))

    # ========== Discord -> Twitch ==========
    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return

        twitch_channel = self.d2t_map.get(message.channel.id)
        if not twitch_channel:
            return  # 非橋接頻道

        # 防回圈：T→D 轉過來已帶 TAG_TWITCH
        if message.content.startswith(TAG_TWITCH):
            return

        text = _norm_text(message.content)
        if not text:
            return

        log.info("📥 [D→T recv] ch=%s(id=%s,type=%s) | %s",
                 getattr(message.channel, 'name', 'unknown'),
                 message.channel.id,
                 type(message.channel).__name__,
                 text)

        if not self.twitch_bot:
            log.error("❌ Twitch bot 未啟動")
            return

        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"

            # 等 bot 準備好
            try:
                await self.twitch_bot.wait_for_ready()
            except Exception:
                pass

            # 找對應頻道；未加入就 join
            chan = None
            if getattr(self.twitch_bot, "connected_channels", None):
                for c in self.twitch_bot.connected_channels:
                    if getattr(c, "name", "").lower() == twitch_channel.lower():
                        chan = c
                        break
            if chan is None:
                try:
                    await self.twitch_bot.join_channels([twitch_channel])
                    log.info("🔁 [D→T] join_channels -> #%s", twitch_channel)
                except Exception as e:
                    log.warning("⚠️ [D→T] join_channels 失敗：%s", e)
                if getattr(self.twitch_bot, "connected_channels", None):
                    for c in self.twitch_bot.connected_channels:
                        if getattr(c, "name", "").lower() == twitch_channel.lower():
                            chan = c
                            break

            if chan is None:
                log.error("❌ [D→T] 找不到/未加入 Twitch #%s（檢查 bot 是否被 /ban 或 token 是否含 chat:edit）", twitch_channel)
                return

            await chan.send(payload)
            log.info("✅ [D→T send] #%s | %s", twitch_channel, payload)

        except Exception as e:
            log.exception("❌ [D→T] send 失敗：%s", e)


# ---------- Discord channel fetch helper ----------
async def _safe_get_messageable_channel(
    bot: commands.Bot, channel_id: int
) -> Optional[Messageable]:
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
    log.info("🧩 TwitchRelay Cog 已載入（Unified Bot）")
