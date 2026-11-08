import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config
from core.permissions import can_use_staff_tool, is_server_admin
from core.ui import SafeView
from core.storage_paths import DATA_DIR
from features.bot_health import storage_health


class HealthView(SafeView):
    def __init__(self, member):
        super().__init__(timeout=180)
        self.owner = member.id
        refresh = discord.ui.Button(label="重新整理", emoji="🔄", row=0)
        async def reload(interaction):
            await interaction.client.get_cog("BotHealth").menu_entry(interaction, refresh=True)
        refresh.callback = reload
        self.add_item(refresh)
        if is_server_admin(member):
            from features.notification_review_views import open_reviews
            review = discord.ui.Button(label='處理待查通知', emoji='📬')
            review.callback = open_reviews
            self.add_item(review)
            from features.drink_views import FeatureButton
            self.add_item(FeatureButton(label='等級管理', emoji='🎖️', cog='CommunityLevels', method='admin_entry', row=1))
            self.add_item(FeatureButton(label='稱號管理', emoji='🏅', cog='TitleRoles', method='admin_entry', row=1))
            audit = discord.ui.Button(label='通知操作紀錄', emoji='📋', row=1)
            async def show_audit(inter):
                current = inter.guild.get_member(inter.user.id) if inter.guild else None
                if not is_server_admin(current):
                    await inter.response.send_message('只限管理員。', ephemeral=True)
                    return
                await inter.response.defer(ephemeral=True, thinking=True)
                from features.bot_health import review_history
                levels = inter.client.get_cog('CommunityLevels')
                warnings = []
                rows = await asyncio.to_thread(review_history, levels.ledger.path if levels else DATA_DIR / 'community_levels.sqlite3', inter.guild_id, warnings=warnings)
                actions={'sent':'核對已送出','retry':'確認重試','cancel':'取消通知'}
                lines = [f"<t:{int(row['stamp'])}:f>｜{row['kind']}｜{actions[row['action']]}｜操作人 {row['actor']}" for row in rows]
                lines.extend(warnings)
                await inter.followup.send(embed=discord.Embed(title='📋 最近通知操作', description='\n'.join(lines) or '暫時未有操作紀錄。'), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            audit.callback = show_audit
            self.add_item(audit)
        from features.drink_views import FeatureButton
        self.add_item(FeatureButton(label='返回管理工具', emoji='🛠️', cog='Menu', method='open_admin_tool_from_button', row=0))

    async def interaction_check(self, interaction):
        current = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        if interaction.guild_id == config.GUILD_ID and interaction.user.id == self.owner and can_use_staff_tool(current, 'bot_health'):
            return True
        await interaction.response.send_message('權限已改變或面板唔屬於你，請重新開啟。', ephemeral=True)
        return False


class BotHealth(commands.Cog):
    def __init__(self,bot):self.bot=bot

    async def menu_entry(self,interaction, *, refresh=False):
        if interaction.guild_id!=config.GUILD_ID or not can_use_staff_tool(interaction.guild.get_member(interaction.user.id), "bot_health"):
            await interaction.response.send_message('只限本伺服器管理員／Mod／Helper 使用。',ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True,thinking=not refresh)
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
        titles=self.bot.get_cog('TitleRoles')
        title_status='未載入'
        if titles:
            from features.title_roles import queue_status,settings,safe_role
            count=len(await asyncio.to_thread(queue_status,interaction.guild_id))
            cfg=await asyncio.to_thread(settings,interaction.guild_id)
            unsafe=sum(not safe_role(interaction.guild,interaction.guild.get_role(rid),titles.levels()) for rid in cfg['mapping'].values())
            title_status=f"已載入｜同步循環 {'運行中' if titles.tick.is_running() else '已停止'}｜待同步 {count} 人｜待修正 Role {unsafe} 個"
        embed.add_field(name='展示稱號',value=title_status,inline=False)
        levels=self.bot.get_cog('CommunityLevels')
        health=await asyncio.to_thread(storage_health,levels.ledger.path if levels else DATA_DIR / 'community_levels.sqlite3',interaction.guild_id)
        for name,values in health.items():
            embed.add_field(name=name,value='｜'.join(f'{key}：{value}' for key,value in values.items()),inline=False)
        embed.timestamp=discord.utils.utcnow()
        embed.set_footer(text='最近檢查｜循環運行唔代表每項工作已成功；待查通知需逐項核對。')
        embed.add_field(name='異常處理', value='角色同步：進入等級／稱號管理核對。\n通知：進入待查通知逐項處理，保留操作紀錄。\n召人卡結果不明：先核對原頻道，再用 /squad_recover 配對實際卡片；唔會自動補發。\n收尾通知由背景工作重試；持續積壓請查管理日誌。', inline=False)
        view=HealthView(interaction.guild.get_member(interaction.user.id))
        if refresh:
            await interaction.edit_original_response(embed=embed,view=view)
            return
        await interaction.followup.send(embed=embed,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='bot_health',description='唯讀檢查 Bot 子系統、帳本及待發通知')
    async def health(self,interaction:discord.Interaction):await self.menu_entry(interaction)


async def setup(bot):await bot.add_cog(BotHealth(bot))
