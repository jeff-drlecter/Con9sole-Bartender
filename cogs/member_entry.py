"""Persistent public entry; every functional reply is private and member-localized."""
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_server_admin
from core.ui import SafeView
from core.json_storage import atomic_write_json
from core.storage_paths import DATA_DIR

ENTRY_COPY = (
    '🎮 **找隊友，約一局**\n'
    '先選擇遊戲，再開啟功能或發起預約。沒有合適遊戲也可向 Helper 查詢。\n'
    '下方操作只向自己顯示；提交約局後才會在所選頻道公開。'
)
GUIDE_NAMES = {'bartender使用指南', '組隊與語音指南', '如何加入不同遊戲分區✅'}


def game_entry_moves(guild):
    targets = []
    for category in guild.categories:
        if category.id == config.TEMPLATE_CATEGORY_ID or category.name in {'封存', 'sample-template'}:
            continue
        chats = [c for c in category.text_channels if c.name.endswith('-吹水組隊')]
        if len(chats) != 1:
            continue
        chat = chats[0]
        bucket = sorted((c for c in category.channels if c._sorting_bucket == chat._sorting_bucket), key=lambda c: (c.position, c.id))
        if bucket and bucket[0].id != chat.id:
            targets.append(chat)
    return targets


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

    @app_commands.command(name='遊戲入口排序', description='管理員：將各遊戲組隊文字頻道移到分類最前；不改權限')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(action=[app_commands.Choice(name='預覽', value='preview'), app_commands.Choice(name='套用', value='apply')])
    async def order(self, interaction: discord.Interaction, action: str = 'preview'):
        if interaction.guild_id != config.GUILD_ID or not is_server_admin(await interaction.guild.fetch_member(interaction.user.id)):
            await interaction.response.send_message('只限本社群管理員。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        moves = game_entry_moves(interaction.guild)
        if action == 'preview':
            await interaction.followup.send('待調整：' + ('、'.join(c.name for c in moves) or '無') + '\n只調整分類內的文字／論壇排序；語音、身份組及權限不變。', ephemeral=True)
            return
        if action != 'apply':
            await interaction.followup.send('未知操作。', ephemeral=True)
            return
        snapshot = [dict(category=c.id, channels=[dict(id=x.id, position=x.position, type=str(x.type)) for x in c.channels]) for c in interaction.guild.categories]
        path = DATA_DIR / ('channel-order-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
        atomic_write_json(path, snapshot)
        updated = 0
        for channel in moves:
            try:
                if not is_server_admin(await interaction.guild.fetch_member(interaction.user.id)):
                    break
                fresh = await interaction.guild.fetch_channel(channel.id)
                if fresh.category_id != channel.category_id or fresh.name != channel.name:
                    break
                await channel.move(beginning=True, reason='Place game squad entry before reference channels')
                updated += 1
            except discord.HTTPException:
                break
        await interaction.followup.send(f'已調整 {updated}／{len(moves)} 個遊戲入口；原排序已備份。未修改身份組或權限。', ephemeral=True)

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
