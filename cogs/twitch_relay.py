# cogs/twitch_relay.py — diagnostics build
import os, json, asyncio
from typing import Dict, Tuple, Optional, Union

import discord
from discord.ext import commands
from discord.abc import Messageable
from discord import TextChannel, VoiceChannel, StageChannel

from twitchio.ext import commands as twitch_commands

RAW_CONFIG = os.getenv("TWITCH_RELAY_CONFIG", "[]")
try:
    RELAY_CONFIG = json.loads(RAW_CONFIG)
    if not isinstance(RELAY_CONFIG, list):
        raise ValueError("must be JSON array")
except Exception as e:
    print(f"[RelayBoot] ❌ invalid TWITCH_RELAY_CONFIG: {e}")
    RELAY_CONFIG = []

TAG_TWITCH  = "[Twitch]"
TAG_DISCORD = "[Discord]"

MessageableChannel = Union[TextChannel, VoiceChannel, StageChannel, Messageable]


class TwitchRelay(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.discord_map: Dict[int, Tuple[str, twitch_commands.Bot]] = {}
        self.twitch_map: Dict[str, int] = {}
        print(f"[RelayBoot] Loaded {len(RELAY_CONFIG)} relay entries")
        for i, e in enumerate(RELAY_CONFIG):
            print(f"[RelayBoot] #{i+1} {e}")
        self._connect_all_from_secrets()

    def _connect_all_from_secrets(self) -> None:
        loop = asyncio.get_event_loop()

        for entry in RELAY_CONFIG:
            try:
                twitch_channel = str(entry["twitch_channel"])
                twitch_oauth   = str(entry["twitch_oauth"])
                discord_ch_id  = int(entry["discord_channel_id"])
            except Exception as e:
                print(f"[RelayBoot] ⚠️ bad entry {entry}: {e}")
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
                    print(f"[T] ✅ Connected as {self.nick} -> #{self.twitch_channel_name}")

                async def event_message(self, message):
                    if message.echo:
                        return
                    ch = await _safe_get_messageable_channel(cog_self.bot, self.discord_channel_id)
                    if not ch:
                        print(f"[T→D] ❌ cannot resolve discord channel id={self.discord_channel_id}")
                        return
                    author = message.author.display_name or message.author.name
                    text = message.content
                    content = f"{TAG_TWITCH} {author}: {text}"
                    try:
                        await ch.send(content)
                        print(f"[T→D] ok -> {type(ch).__name__}({ch.id}) | {content}")
                    except Exception as e:
                        print(f"[T→D] ❌ send error: {e}")

            tbot = _TwitchBot()
            self.discord_map[discord_ch_id] = (twitch_channel, tbot)
            self.twitch_map[twitch_channel.lower()] = discord_ch_id
            loop.create_task(tbot.connect())

    @commands.Cog.listener("on_message")
    async def _discord_to_twitch(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        pair = self.discord_map.get(message.channel.id)
        if not pair:
            return
        if message.content.startswith(TAG_TWITCH):
            # 係由 T→D 帶過來嘅，唔回射
            return

        twitch_channel, tbot = pair
        text = message.content.strip()
        if not text:
            return

        print(f"[D→T recv] in ch={message.channel.id} type={type(message.channel).__name__} | {text}")

        try:
            await getattr(tbot, "wait_for_ready", asyncio.sleep)(0)
        except Exception:
            pass

        try:
            payload = f"{TAG_DISCORD} {message.author.display_name}: {text}"
            if getattr(tbot, "connected_channels", None):
                await tbot.connected_channels[0].send(payload)
            else:
                # 保底仍試一次
                await tbot.connected_channels[0].send(payload)
            print(f"[D→T send] #{twitch_channel} | {payload}")
        except Exception as e:
            print(f"[D→T] ❌ send error: {e}")


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
