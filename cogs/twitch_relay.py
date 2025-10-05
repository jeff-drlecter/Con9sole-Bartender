# cogs/twitch_relay.py
# 雙向 Twitch <-> Discord 聊天橋接（多成員）
# 需要：discord.py v2 / twitchio==2.8.2
# 設定檔：repo 根目錄放 twitch_relay_config.json
# [
#   {"twitch_channel": "jeff_con9sole",
#    "twitch_oauth": "oauth:XXXXXXXX",
#    "discord_channel_id": "123456789012345678"},
#   ...
# ]

import asyncio
import json
from typing import Dict, Tuple, Optional

import discord
from discord.ext import commands
from twitchio.ext import commands as twitch_commands

CONFIG_PATH = "twitch_relay_config.json"

# 標籤（如不想顯示可改為 ""）
TAG_TWITCH  = "[Twitch]"
TAG_DISCORD = "[Discord]"


class TwitchRelay(commands.Cog):
    """雙向 Twitch <-> Discord 聊天橋接"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # discord_channel_id -> (twitch_channel, twitch_bot)
        self.discord_map: Dict[int, Tuple[str, twitch_commands.Bot]] = {}
        # twitch_channel(lower) -> discord_channel_id
        self.twitch_map: Dict[str, int] = {}

        self._load_config_and_connect()

    # 讀取設定並為每個 entry 建立一條 TwitchIO 連線
    def _load_config_and_connect(self) -> None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        loop = asyncio.get_event_loop()

        for entry in cfg:
            twitch_channel = entry["twitch_channel"]
            twitch_oauth   = entry["twitch_oauth"]
            discord_ch_id  = int(entry["discord_channel_id"])

            # 內嵌一個 TwitchIO Bot 類別以帶到本 Cog 的上下文
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
                    # Twitch 對自身送出的訊息會標記為 echo；避免回圈
                    if message.echo:
                        return

                    # 送去對應 Discord 頻道
                    dch = await _safe_get_text_channel(cog_self.bot, self.discord_channel_id)
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

            # 記錄映射
            self.discord_map[discord_ch_id] = (twitch_channel, tbot)
            self.twitch_map[twitch_channel.lower()] = discord_ch_id

            # 非阻塞啟動
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

        # 避免把由 Twitch 轉過來的訊息再回送 Twitch
        if message.content.startswith(TAG_TWITCH):
            return

        twitch_channel, tbot = pair
        text = message.content.strip()
        if not text:
            return

        # 等候 Twitch 連線穩定（不同版本可能無此方法，失敗則略過）
        try:
            await tbot.wait_for_ready()  # twitchio>=2.8
        except Exception:
            pass

        # 發送到 Twitch chat
        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"
            # 優先用已連接頻道
            if getattr(tbot, "connected_channels", None):
                await tbot.connected_channels[0].send(payload)
            else:
                # 後備（某些版本 API）
                chan = twitch_channel
                await tbot.get_channel(chan).send(payload)  # 可能因版本不同而無效
            # 完成
        except Exception as e:
            print(f"[Relay D→T] send error: {e}")


async def _safe_get_text_channel(bot: commands.Bot, channel_id: int) -> Optional[discord.TextChannel]:
    """優先用 cache，取不到再 fetch；失敗回 None。"""
    ch = bot.get_channel(channel_id)
    if isinstance(ch, discord.TextChannel):
        return ch
    try:
        ch = await bot.fetch_channel(channel_id)
        if isinstance(ch, discord.TextChannel):
            return ch
    except Exception:
        pass
    return None


async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchRelay(bot))
