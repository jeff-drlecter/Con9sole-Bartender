"""Supplement native AutoMod with deterministic alert-only repeated-text detection."""
import logging
import time
import discord
from discord.ext import commands
import config
from features.anti_scam_monitor import private_alert
from features.anti_scam_rules import ALERT_CHANNEL
from features.repeated_message_monitor import RepeatedMessages

log = logging.getLogger(__name__)


class RepeatedMessageMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.detector = RepeatedMessages()

    @commands.Cog.listener()
    async def on_message(self, message):
        if (message.guild is None or message.guild.id != config.GUILD_ID
                or message.author.bot or message.webhook_id
                or message.channel.id == ALERT_CHANNEL):
            return
        count = self.detector.observe(message.author.id, message.id, message.content, time.monotonic())
        if count is None:
            return
        try:
            roles = await message.guild.fetch_roles()
            channel = await message.guild.fetch_channel(ALERT_CHANNEL)
            private_alert(message.guild.id, roles, channel)
            await channel.send(
                '**疑似重複訊息｜只提示**\n'
                f'會員 ID：{message.author.id}｜15 秒內相同文字 {count} 條\n'
                f'檢視訊息：{message.jump_url}\n'
                '請人工覆核；未刪訊息、未停權、未撤銷 Verified。',
                allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        except (discord.HTTPException, ValueError):
            log.exception('Repeated-message alert withheld or unconfirmed; no retry')


async def setup(bot):
    await bot.add_cog(RepeatedMessageMonitor(bot))
