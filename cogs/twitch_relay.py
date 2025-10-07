# cogs/twitch_relay.py  (DEBUG build, strong de-dup & channel guard)
import os, json, asyncio, logging, time
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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.discord_map: Dict[int, Tuple[str, twitch_commands.Bot]] = {}
        self.twitch_map: Dict[str, int] = {}

        log.info("🔧 RelayBoot: 已載入 %d 條配置", len(RELAY_CONFIG))
        for i, e in enumerate(RELAY_CONFIG, start=1):
            safe = {"twitch_channel": e.get("twitch_channel"),
                    "discord_channel_id": e.get("discord_channel_id"),
                    "twitch_oauth": "oauth:***hidden***" if e.get("twitch_oauth") else None}
            log.info("🔧 RelayBoot: #%d %s", i, safe)

        self._connect_all_from_secrets()

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
                    super().__init__(token=twitch_oauth, prefix="!", initial_channels=[twitch_channel])
                    self.discord_channel_id = discord_ch_id
                    self.twitch_channel_name = twitch_channel

                async def event_ready(self):
                    log.info("🟣 [T] Connected as %s -> #%s", self.nick, self.twitch_channel_name)

                async def event_message(self, message):
                    # ---- 基本過濾 ----
                    if getattr(message, "echo", False):
                        return
                    try:
                        if (message.author and message.author.name and self.nick and
                                message.author.name.lower() == self.nick.lower()):
                            return
                    except Exception:
                        pass

                    text_raw = message.content or ""
                    text = _norm_text(text_raw)
                    if text.startswith(TAG_DISCORD):
                        return

                    # ---- 只處理綁定的頻道 ----
                    try:
                        ch_name = (getattr(message.channel, "name", "") or "").lower()
                        if ch_name != (self.twitch_channel_name or "").lower():
                            return
                    except Exception:
                        pass

                    # ---- 以 Twitch message-id 去重 ----
                    msg_id = None
                    try:
                        # twitchio 2.x: message.tags 係 dict; 有些 client 在 tags['id']
                        tags = getattr(message, "tags", {}) or {}
                        msg_id = str(tags.get("id")) if "id" in tags else None
                    except Exception:
                        msg_id = None
                    if _seen_recent_tw(msg_id or f"{ch_name}:{message.author.name}:{text}"):
                        log.info("⏩ [T→D] duplicate skipped (tw)")
                        return

                    dch = await _safe_get_messageable_channel(cog_self.bot, self.discord_channel_id)
                    if not dch:
                        log.error("❌ [T→D] 解析不到 Discord 頻道 id=%s", self.discord_channel_id)
                        return

                    author = message.author.display_name or message.author.name
                    content = f"{TAG_TWITCH} {author}: {text}"

                    # 二次去重（同頻道同內容）
                    if _seen_recent_td(self.discord_channel_id, content):
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

            tbot = _TwitchBot()
            self.discord_map[discord_ch_id] = (twitch_channel, tbot)
            self.twitch_map[twitch_channel.lower()] = discord_ch_id
            loop.create_task(tbot.connect())
            log.info("🔌 啟動 Twitch 連線：#%s -> Discord(%s)", twitch_channel, discord_ch_id)

    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return

        pair = self.discord_map.get(message.channel.id)
        if not pair:
            return

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
            try:
                await tbot.wait_for_ready()
            except Exception:
                pass

            chan = None
            if getattr(tbot, "connected_channels", None):
                for c in tbot.connected_channels:
                    if getattr(c, "name", "").lower() == twitch_channel.lower():
                        chan = c
                        break

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
    log.info("🧩 TwitchRelay Cog 已載入（Debug+de-dup）")
