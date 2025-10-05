# cogs/twitch_relay.py
# 雙向 Twitch <-> Discord 聊天橋接（多成員；只用 Fly.io Secrets）
# 依賴：discord.py v2、twitchio==2.8.2
# 環境變數（Fly secrets）：
#   TWITCH_RELAY_CONFIG='[
#     {"twitch_channel":"xxx","twitch_oauth":"oauth:...","discord_channel_id":"123"},
#     ...
#   ]'

import os
import json
import asyncio
from typing import Dict, Tuple, Optional, Union

import discord
from discord.ext import commands
from discord.abc import Messageable
from discord import TextChannel, VoiceChannel, StageChannel

from twitchio.ext import commands as twitch_commands


# ===== 讀取 Fly.io Secret =====
RAW_CONFIG = os.getenv("TWITCH_RELAY_CONFIG", "[]")
try:
    RELAY_CONFIG = json.loads(RAW_CONFIG)
    if not isinstance(RELAY_CONFIG, list):
        raise ValueError("TWITCH_RELAY_CONFIG 必須為 JSON array")
except Exception as e:
    print(f"[TwitchRelay] ❌ 讀取 TWITCH_RELAY_CONFIG 失敗：{e}")
    RELAY_CONFIG = []

# 顯示來源標籤（想隱藏可改為 ""）
TAG_TWITCH  = "[Twitch]"
TAG_DISCORD = "[Discord]"

# 允許發送訊息的頻道型別（含 Text / Voice / Stage 的文字聊天）
MessageableChannel = Union[TextChannel, VoiceChannel, StageChannel, Messageable]


class TwitchRelay(commands.Cog):
    """雙向 Twitch <-> Discord 聊天橋接（使用 Fly secrets 配置多成員）"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # discord_channel_id -> (twitch_channel, twitch_bot)
        self.discord_map: Dict[int, Tuple[str, twitch_commands.Bot]] = {}
        # twitch_channel(lower) -> discord_channel_id
        self.twitch_map: Dict[str, int] = {}
        self._connect_all_from_secrets()

    def _connect_all_from_secrets(self) -> None:
        """根據 secrets 啟動每個 Twitch 連線"""
        loop = asyncio.get_event_loop()

        for entry in RELAY_CONFIG:
            try:
                twitch_channel = str(entry["twitch_channel"])
                twitch_oauth   = str(entry["twitch_oauth"])
                discord_ch_id  = int(entry["discord_channel_id"])
            except KeyError as ke:
                print(f"[TwitchRelay] ⚠️ 設定缺少欄位：{ke}，已略過：{entry}")
                continue
            except Exception as e:
                print(f"[TwitchRelay] ⚠️ 設定格式錯誤：{e}，已略過：{entry}")
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
                    print(f"[Twitch] ✅ Connected as {self.nick} -> #{self.twitch_channel_name}")

                async def event_message(self, message):
                    # 避免回圈（自己送出的訊息）
                    if message.echo:
                        return

                    dch = await _safe_get_messageable_channel(
                        cog_self.bot, self.discord_channel_id
                    )
                    if not dch:
                        return

                    author = message.author.display_name or message.author.name
                    text = message.content
                    content = f"{TAG_TWITCH} {author}: {text}"
                    try:
                        await dch.send(content)
                    except Exception as e:
                        print(f"[Relay T→D] send error: {e}")

            tbot = _TwitchBot()

            self.discord_map[discord_ch_id] = (twitch_channel, tbot)
            self.twitch_map[twitch_channel.lower()] = discord_ch_id

            loop.create_task(tbot.connect())

    # ---- Discord → Twitch ----
    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        # 忽略 bot、私訊、空內容
        if message.author.bot or not message.guild or not message.content:
            return

        pair = self.discord_map.get(message.channel.id)
        if not pair:
            return  # 非橋接頻道

        # 避免把從 Twitch 轉過來的訊息再回送 Twitch（靠標籤）
        if message.content.startswith(TAG_TWITCH):
            return

        twitch_channel, tbot = pair
        text = message.content.strip()
        if not text:
            return

        # 等待 Twitch 連線穩定（不同 twitchio 版本可能無此方法，失敗則略過）
        try:
            await tbot.wait_for_ready()
        except Exception:
            pass

        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"
            if getattr(tbot, "connected_channels", None):
                await tbot.connected_channels[0].send(payload)
            else:
                # 後備（依版本 API 而定）
                await tbot.connected_channels[0].send(payload)
        except Exception as e:
            print(f"[Relay D→T] send error: {e}")


async def _safe_get_messageable_channel(
    bot: commands.Bot, channel_id: int
) -> Optional[MessageableChannel]:
    """從 cache / API 取回可發訊息的頻道（Text / Voice / Stage 的文字聊天）。"""
    ch = bot.get_channel(channel_id)
    if isinstance(ch, (TextChannel, VoiceChannel, StageChannel, Messageable)):
        return ch  # 這些型別在 discord.py 2.x 皆可 .send()

    try:
        ch = await bot.fetch_channel(channel_id)
        if isinstance(ch, (TextChannel, VoiceChannel, StageChannel, Messageable)):
            return ch
    except Exception:
        pass
    return None


async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchRelay(bot))
