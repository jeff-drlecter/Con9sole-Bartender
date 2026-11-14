"""Member-owned controls for actual news role opt-ins; never sends notifications."""
import asyncio
import json
from pathlib import Path
import discord
from features.news_channel_categories import CHANNELS,LABELS,ROLE_NAMES
from features.language_preferences import language
from core.storage_paths import DATA_DIR
from core.news_channel_inventory import fetch_news_channels

STATE=DATA_DIR/'news_channel_categories'/'applied.json'
LOCKS={}


def settings():
    data=json.loads(STATE.read_text())
    if data.get('version')!=1 or set(data.get('role_ids',{}))!=set(CHANNELS) or data.get('channel_ids')!=CHANNELS:
        raise ValueError('新聞分類設定未準備好，請稍後再試。')
    return data['role_ids']


async def safe_roles(guild):
    ids=settings()
    current=await guild.fetch_roles()
    roles={key:next((r for r in current if r.id==int(rid)),None) for key,rid in ids.items()}
    if any(r is None or r.managed or r.permissions.value or r.name!=ROLE_NAMES[k] for k,r in roles.items()):
        raise ValueError('新聞分類身份組設定已變更，請管理員檢查。')
    selected_ids={r.id for r in roles.values()}
    for channel in await fetch_news_channels(guild):
        if channel.id not in CHANNELS.values() and any(t.id in selected_ids and
                (isinstance(t,discord.Role) or getattr(t,'type',None) is discord.Role)
                for t in channel.overwrites):
            raise ValueError('新聞分類身份組涉及其他區域，請管理員先檢查。')
    me=await guild.fetch_member(guild._state.user.id)
    if any(r>=me.top_role for r in roles.values()): raise ValueError('Bot 無法調整新聞分類，請管理員檢查。')
    return roles


class NewsChannelSelect(discord.ui.Select):
    def __init__(self,selected):
        super().__init__(placeholder='選擇新聞分類（可複選；清空即全部關閉）',min_values=0,max_values=3,
            options=[discord.SelectOption(label=label,value=key,default=key in selected) for key,label in LABELS.items()])

    async def callback(self,interaction):
        await interaction.response.defer(ephemeral=True)
        async with LOCKS.setdefault(interaction.user.id,asyncio.Lock()):
            try:
                roles=await safe_roles(interaction.guild)
                member=await interaction.guild.fetch_member(interaction.user.id)
                chosen=set(self.values)
                if chosen-set(CHANNELS): raise ValueError('請重新開啟新聞分類選單。')
                for key,role in roles.items():
                    if key in chosen and role not in member.roles:
                        await member.add_roles(role,reason='Member news channel choice')
                    elif key not in chosen and role in member.roles:
                        await member.remove_roles(role,reason='Member news channel choice')
                fresh=await interaction.guild.fetch_member(member.id)
                selected={k for k,r in roles.items() if r in fresh.roles}
                if selected!=chosen: raise ValueError('尚未確認設定，請重新開啟選單檢查。')
                content=('✅ 已儲存新聞頻道選擇。可隨時更改；手機通知由 Discord 頻道通知設定控制。'
                    if language(fresh)!='hk' else '✅ 已儲存新聞頻道選擇。可隨時再改；手機通知跟返 Discord 頻道通知設定。')
                await interaction.followup.send(content,view=NewsChannelView(fresh.id,selected),ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException,FileNotFoundError) as exc:
                await interaction.followup.send(str(exc) if isinstance(exc,ValueError) else '設定未完成，請稍後重新開啟選單檢查。',ephemeral=True)


class NewsChannelView(discord.ui.View):
    def __init__(self,owner,selected):
        super().__init__(timeout=600)
        self.owner=owner
        self.add_item(NewsChannelSelect(selected))

    async def interaction_check(self,interaction):
        import config
        if interaction.guild_id==config.GUILD_ID and interaction.user.id==self.owner: return True
        await interaction.response.send_message('請開啟自己的「新聞頻道接收」。',ephemeral=True)
        return False


async def open_news_channels(interaction):
    import config
    if interaction.guild_id!=config.GUILD_ID or interaction.guild is None:
        await interaction.response.send_message('請在本社群內使用。',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    try:
        roles=await safe_roles(interaction.guild)
        member=await interaction.guild.fetch_member(interaction.user.id)
        selected={k for k,r in roles.items() if r in member.roles}
        await interaction.followup.send('📰 新聞頻道接收\n選擇要開啟的分類；未選擇的分類會隱藏。\n這裡調整頻道接收；「我的情報」篩選另行設定。',
            view=NewsChannelView(member.id,selected),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    except (ValueError,discord.HTTPException,FileNotFoundError) as exc:
        await interaction.followup.send(str(exc) if isinstance(exc,ValueError) else '新聞分類暫未準備好，請稍後再試。',ephemeral=True)

