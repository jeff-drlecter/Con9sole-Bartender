# cogs/twitch_relay.py — Unified Twitch Bot (Auto-Reconnect + de-dup + loopback-safe)

import os, json, asyncio, logging, time, aiohttp
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
_recent_td: Dict[Tuple[int, str], float] = {}
_recent_tw_ids: Dict[str, float] = {}
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
        self.twitch_bot: Optional[twitch_commands.Bot] = None
        self._connect_task: Optional[asyncio.Task] = None
        self.d2t_map: Dict[int, str] = {}
        self.t2d_map: Dict[str, int] = {}

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

        if not BOT_OAUTH:
            log.error("❌ 缺少 TWITCH_BOT_OAUTH，無法啟動 Twitch bot")
            return

        initial = list({ch for ch in self.t2d_map.keys()})

        class _UnifiedTwitchBot(twitch_commands.Bot):
            async def event_ready(self_inner):
                log.info("🟣 [T] Connected as %s", self_inner.nick)
                try:
                    await self_inner.join_channels(initial)
                    log.info("🔁 確認 join_channels：%s", ",".join(initial))
                except Exception as e:
                    log.warning("⚠️ join_channels 失敗：%s", e)

            async def event_message(self_inner, message):
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

                try:
                    ch_name = (getattr(message.channel, "name", "") or "").lower()
                except Exception:
                    ch_name = ""
                if ch_name not in self.t2d_map:
                    return

                msg_id = None
                try:
                    tags = getattr(message, "tags", {}) or {}
                    msg_id = str(tags.get("id")) if "id" in tags else None
                except Exception:
                    msg_id = None
                if _seen_recent_tw(msg_id or f"{ch_name}:{message.author.name}:{text}"):
                    log.info("⏩ [T→D] duplicate skipped (tw)")
                    return

                dch_id = self.t2d_map.get(ch_name)
                dch = await _safe_get_messageable_channel(self.bot, dch_id)
                if not dch:
                    log.error("❌ [T→D] 找不到 Discord 頻道 id=%s", dch_id)
                    return

                author = message.author.display_name or message.author.name
                content = f"{TAG_TWITCH} {author}: {text}"

                if _seen_recent_td(dch_id, content):
                    log.info("⏩ [T→D] duplicate skipped (td)")
                    return

                try:
                    await dch.send(content)
                    log.info("✅ [T→D] -> %s(id=%s): %s", getattr(dch, 'name', 'unknown'), dch_id, content)
                except Exception as e:
                    log.exception("❌ [T→D] send 失敗：%s", e)

        self.twitch_bot = _UnifiedTwitchBot(
            token=BOT_OAUTH,
            prefix="!",
            initial_channels=initial or None
        )

        self._connect_task = asyncio.create_task(self.twitch_bot.connect())
        log.info("🔌 啟動統一 Twitch 連線：%s", ",".join(initial))

    def cog_unload(self) -> None:
        """Stop background Twitch work when this cog is reloaded or unloaded."""
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()

        if self.twitch_bot is not None:
            asyncio.create_task(self.twitch_bot.close())

    # ========== Discord → Twitch ==========
    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return

        twitch_channel = self.d2t_map.get(message.channel.id)
        if not twitch_channel:
            return

        if message.content.startswith(TAG_TWITCH):
            return

        text = _norm_text(message.content)
        if not text:
            return

        log.info("📥 [D→T recv] ch=%s(id=%s) | %s",
                 getattr(message.channel, 'name', 'unknown'),
                 message.channel.id, text)

        if not self.twitch_bot:
            log.error("❌ Twitch bot 未啟動")
            return

        payload = f"{TAG_DISCORD} {message.author.name}: {text}"

        try:
            # 確保 WS 可用
            ws = getattr(self.twitch_bot, "_websocket", None)
            if ws is None or ws.closed or getattr(ws, "_closing", False):
                log.warning("⚠️ [D→T] Twitch WS 關閉中，嘗試重連…")
                await self.twitch_bot.connect()
                await asyncio.sleep(2)

            # 找對應 Twitch channel
            chan = next((c for c in getattr(self.twitch_bot, "connected_channels", [])
                         if getattr(c, "name", "").lower() == twitch_channel.lower()), None)
            if chan is None:
                await self.twitch_bot.join_channels([twitch_channel])
                log.info("🔁 [D→T] join_channels -> #%s", twitch_channel)
                await asyncio.sleep(1)
                chan = next((c for c in getattr(self.twitch_bot, "connected_channels", [])
                             if getattr(c, "name", "").lower() == twitch_channel.lower()), None)

            if not chan:
                log.error("❌ [D→T] 找不到 Twitch #%s（檢查 token 是否含 chat:edit）", twitch_channel)
                return

            await chan.send(payload)
            log.info("✅ [D→T send] #%s | %s", twitch_channel, payload)

        except aiohttp.client_exceptions.ClientConnectionResetError:
            log.warning("⚠️ [D→T] Twitch 重連中，略過訊息。")
        except Exception as e:
            log.exception("❌ [D→T] send 失敗：%s", e)


async def _safe_get_messageable_channel(bot: commands.Bot, channel_id: int) -> Optional[Messageable]:
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
    log.info("🧩 TwitchRelay Cog 已載入（Unified Bot + Auto-Reconnect）")
