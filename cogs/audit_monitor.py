"""Watch the logger independently, updating one private maintenance card per incident."""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks

import config
from core.audit_monitor import ALERT_CHANNEL, IncidentCard, findings
from core.storage_paths import DATA_DIR

log=logging.getLogger(__name__)


class AuditMonitor(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.card=IncidentCard(DATA_DIR/'audit_monitor.json')
        self.last_error=None
        self.latest=[]
        self.lock=asyncio.Lock()

    async def cog_load(self): self.watch.start()

    async def cog_unload(self):
        self.watch.cancel()
        task=self.watch.get_task()
        if task: await asyncio.gather(task,return_exceptions=True)

    def destination(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        channel=guild.get_channel(ALERT_CHANNEL) if guild else None
        if not isinstance(channel,discord.TextChannel) or channel.guild.id!=config.GUILD_ID:
            raise RuntimeError('未找到 bot-維護頻道')
        permissions=channel.permissions_for(guild.me)
        if channel.permissions_for(guild.default_role).view_channel or not (permissions.view_channel and permissions.send_messages):
            raise RuntimeError('bot-維護路由不是私有或 Bot 無法派送')
        return channel

    @tasks.loop(seconds=30)
    async def watch(self):
        async with self.lock:
            try:
                audit=self.bot.get_cog('CommunityAudit')
                if not audit:
                    issues=['社群日誌模組未載入']
                else:
                    try:
                        health=await asyncio.to_thread(audit.store.health)
                        issues=findings(health,sender_running=audit.deliver.is_running(),heartbeat=audit.heartbeat,
                                        write_failed=audit.write_failed)
                    except Exception:
                        issues=['日誌資料庫無法讀取']
                    for category in ('server','message','member','voice'):
                        try: audit.destination(category)
                        except Exception: issues.append(f'{category} 日誌路由無法派送')
                if not self.bot.is_ready(): issues.append('Discord Gateway 未連線')
                self.latest=issues
                if issues or self.card.state.get('since'):
                    await self.card.publish(self.destination(),issues)
                self.last_error=None
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.last_error=type(exc).__name__
                log.exception('Audit watchdog could not update its maintenance card')

    @watch.before_loop
    async def before_watch(self): await self.bot.wait_until_ready()

    async def demo(self,inter):
        # Separate state and card, never inject fake failures into the real monitor or outbox.
        async with self.lock:
            card=IncidentCard(DATA_DIR/'audit_monitor_demo.json')
            channel=self.destination()
            await card.publish(channel,['模擬：派送循環停止／佇列積壓；正式日誌仍正常運行'],demo=True)
            mid=card.state.get('message_id')
            if not mid:
                await inter.followup.send('模擬卡送出結果未明，已停止；請先核對 bot-維護。',ephemeral=True)
                return
            await card.publish(channel,[],demo=True)
            await inter.followup.send(f'模擬異常及恢復已更新同一張卡：\nhttps://discord.com/channels/{config.GUILD_ID}/{channel.id}/{mid}',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


async def setup(bot): await bot.add_cog(AuditMonitor(bot))
