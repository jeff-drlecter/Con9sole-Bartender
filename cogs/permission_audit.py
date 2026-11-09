"""Admin-only read-only permission audit export."""
import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands
import config
from core.permissions import is_server_admin
from features.permission_audit import collect, archive


class PermissionAudit(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.lock=asyncio.Lock()
        self.last_run=0

    async def authorized(self,inter):
        if inter.guild_id!=config.GUILD_ID or inter.guild is None:return False
        # Refresh actor authority rather than trusting a panel's cached member.
        try:actor=await inter.guild.fetch_member(inter.user.id)
        except discord.HTTPException:return False
        return is_server_admin(actor)

    async def menu_entry(self,inter):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked() or time.monotonic()-self.last_run<60:
            await inter.followup.send('報告生成中或剛完成，請稍候一分鐘再試。',ephemeral=True);return
        async with self.lock:
            snapshot=await collect(inter.guild,config.VERIFIED_ROLE_ID)
            output=await asyncio.to_thread(archive,snapshot)
            if not await self.authorized(inter):
                await inter.followup.send('權限已改變，報告未送出。',ephemeral=True);return
            if output.getbuffer().nbytes>inter.guild.filesize_limit:
                await inter.followup.send('報告超出附件限制，未有送出；請聯絡維護者。',ephemeral=True);return
            self.last_run=time.monotonic()
            counts={level:sum(r['severity']==level for r in snapshot['findings']) for level in ('warning','policy','review')}
            await inter.followup.send(
                f"**Anti-scam Update｜權限審核**\n角色 {len(snapshot['roles'])}｜分類／頻道 {len(snapshot['channels'])}\n"
                f"需優先核對 {counts['warning']}｜設計差異 {counts['policy']}｜一般覆核 {counts['review']}\n"
                f"Onboarding：{snapshot['onboarding']['status']}｜AutoMod：{snapshot['automod']['status']}\n"
                '附件包含摘要及完整 JSON；未修改任何設定。未涵蓋 threads 或逐人有效權限，詳見 coverage。',
                file=discord.File(output,filename='anti-scam-permission-audit.zip'),
                ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='permission_audit',description='Anti-scam Update：唯讀匯出角色、分類、頻道及權限報告')
    async def audit(self,inter:discord.Interaction):
        try:await self.menu_entry(inter)
        except discord.HTTPException:
            await inter.followup.send('Discord 讀取或附件傳送失敗；未修改任何設定，請稍後再試。',ephemeral=True)


async def setup(bot):await bot.add_cog(PermissionAudit(bot))
