"""Persistent public entry; every functional reply is private and member-localized."""
import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_server_admin
from core.ui import SafeView

ENTRY_COPY = (
    '🎮 **找隊友，約一局**\n'
    '先選擇遊戲，再開啟功能或發起預約。沒有合適遊戲也可向 Helper 查詢。\n'
    '下方操作只向自己顯示；提交約局後才會在所選頻道公開。'
)
GUIDE_NAMES = {'bartender使用指南', '組隊與語音指南', '如何加入不同遊戲分區✅'}


class MemberEntryView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)
        for action, label in [('games', '🎮 選擇遊戲'), ('menu', '🍸 開啟功能'),
                              ('plan', '📅 約一局'), ('language', '🌐 語言設定')]:
            button = discord.ui.Button(label=label, custom_id=f'entry:{action}:v1', row=0 if action in {'games', 'menu'} else 1)
            async def callback(interaction, action=action):
                await self.open(interaction, action)
            button.callback = callback
            self.add_item(button)

    async def open(self, interaction, action):
        if (interaction.guild_id != config.GUILD_ID or interaction.channel is None
                or not interaction.channel.permissions_for(interaction.user).view_channel):
            await interaction.response.send_message('請在可查看的社群頻道使用。', ephemeral=True)
            return
        if action == 'games':
            await interaction.response.send_message(
                '🎮 前往 <id:customize> 選擇遊戲。未選擇時，部分遊戲討論區及語音不會開放。\n'
                '找不到想玩的遊戲，可選「暫不選擇／找不到想玩的遊戲」並向 Helper 查詢。', ephemeral=True)
            return
        name = {'menu': 'Menu', 'plan': 'SquadPlans', 'language': 'LanguagePreferences'}[action]
        cog = interaction.client.get_cog(name)
        if cog is None:
            await interaction.response.send_message('功能暫時無法使用，請稍後再試或通知 Helper。', ephemeral=True)
            return
        if action == 'menu':
            await cog.open_main_menu(interaction)
        else:
            await cog.menu_entry(interaction)


class MemberEntry(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(MemberEntryView())

    @app_commands.command(name='社群入口', description='管理員：在教學頻道建立或更新固定功能按鈕')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def install(self, interaction: discord.Interaction):
        guild, channel = interaction.guild, interaction.channel
        if (interaction.guild_id != config.GUILD_ID or not guild
                or not is_server_admin(await guild.fetch_member(interaction.user.id))):
            await interaction.response.send_message('只限本社群管理員。', ephemeral=True)
            return
        if not isinstance(channel, discord.TextChannel) or channel.name not in GUIDE_NAMES:
            await interaction.response.send_message('請在遊戲加入指南、組隊與語音指南或 bartender使用指南設定入口。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # Update only our functional entry; never alter another author's guide.
        async for message in channel.history(limit=50):
            ids = {getattr(item, 'custom_id', None) for row in message.components for item in row.children}
            if message.author.id == self.bot.user.id and 'entry:menu:v1' in ids:
                await message.edit(content=ENTRY_COPY, view=MemberEntryView(), allowed_mentions=discord.AllowedMentions.none())
                break
        else:
            message = await channel.send(ENTRY_COPY, view=MemberEntryView(), allowed_mentions=discord.AllowedMentions.none())
        await interaction.followup.send(f'固定功能入口已就緒：{message.jump_url}', ephemeral=True)


async def setup(bot):
    await bot.add_cog(MemberEntry(bot))
