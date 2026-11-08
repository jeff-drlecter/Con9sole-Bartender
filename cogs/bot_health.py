import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config
from core.permissions import is_admin_or_helper
from features.bot_health import storage_health


class BotHealth(commands.Cog):
    def __init__(self,bot):self.bot=bot

    async def menu_entry(self,interaction):
        if interaction.guild_id!=config.GUILD_ID or not is_admin_or_helper(interaction.user):
            await interaction.response.send_message('只限本伺服器管理員／Helper 使用。',ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True,thinking=True)
        embed=discord.Embed(title='🩺 Bot 系統狀態',description='唯讀檢查；唔會修改 XP、角色或重發通知。')
        for name,label in (
            ('Menu','主選單'),('Drink','酒吧／收藏'),('Cheers','打氣'),('DailyBar','每日任務'),
            ('CommunityLevels','會員等級'),('SquadCards','招募／足跡卡'),('TempVC','小隊語音房'),
            ('RoleManager','角色工具'),('ActivityReminder','活動提醒'),('UpdatePublisher','更新公告'),
            ('Confession','匿名投稿'),('TwitchRelay','直播轉發')):
            cog=self.bot.get_cog(name)
            text='已載入' if cog else '未載入'
            if name=='CommunityLevels' and cog:
                text+=f"｜計分 {cog.cfg.get('mode','未知')}｜語音循環 {'運行中' if cog.voice_tick.is_running() else '已停止'}"
            if name=='SquadCards' and cog and getattr(cog,'last_error',None):text+='｜有待查錯誤'
            if name=='SquadCards' and cog:text+=f"｜更新循環 {'運行中' if cog.tick.is_running() else '已停止'}"
            embed.add_field(name=label,value=text,inline=False)
        levels=self.bot.get_cog('CommunityLevels')
        if levels:
            health=await asyncio.to_thread(storage_health,levels.ledger.path,interaction.guild_id)
            for name,values in health.items():
                embed.add_field(name=name,value='｜'.join(f'{key}：{value}' for key,value in values.items()),inline=False)
        await interaction.followup.send(embed=embed,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='bot_health',description='唯讀檢查 Bot 子系統、帳本及待發通知')
    async def health(self,interaction:discord.Interaction):await self.menu_entry(interaction)


async def setup(bot):await bot.add_cog(BotHealth(bot))
