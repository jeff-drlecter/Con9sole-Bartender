"""Existing destinations only. No role assignment or permission changes."""
import discord
import config
from features.language_preferences import language


def words(member, neutral, hk):
    return hk if language(member) == 'hk' else neutral


async def support_destination(interaction):
    if interaction.guild_id != config.GUILD_ID or not interaction.guild:
        return None
    try:
        member = await interaction.guild.fetch_member(interaction.user.id)
        channel = await interaction.guild.fetch_channel(config.SUPPORT_CHANNEL_ID)
        if (not isinstance(channel, (discord.TextChannel, discord.ForumChannel))
                or channel.guild.id != config.GUILD_ID or channel.nsfw):
            return None
        p = channel.permissions_for(member)
        if p.view_channel and p.read_message_history and p.send_messages:
            return channel
    except discord.HTTPException:
        pass
    return None


async def show_route(i, action):
    if action == 'observe':
        text = words(i.user,
            '可以先看看。到 <id:customize> 自選聊天、新聞或直播內容；日後也在這裡選擇遊戲，再按「約一局」。',
            '可以先睇吓。去 <id:customize> 自選聊天、新聞或直播內容；之後想玩，就喺同一度揀遊戲，再按「約一局」。')
    elif action == 'help':
        await i.response.defer(ephemeral=True)
        target = await support_destination(i)
        text = (words(i.user, '找不到合適遊戲，或需要協助／建議：', '搵唔到啱玩嘅遊戲，或者需要協助／建議：') + target.mention
                if target else words(i.user,
                    '目前未能確認你可發言的求助入口，沒有開放任何新權限。可先到 <id:customize> 查看可選內容；請稍後再試。',
                    '暫時未能確認你用到嘅求助入口，冇開放任何新權限。可以先去 <id:customize> 睇可選內容；請稍後再試。'))
        await i.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return
    else:
        text = words(i.user,
            '🎮 到 <id:customize> 選擇遊戲，再按「約一局」。找不到合適遊戲可按「求助／建議」；也可以先觀望。',
            '🎮 去 <id:customize> 揀遊戲，再按「約一局」。搵唔到啱玩嘅可以按「求助／建議」，或者先觀望。')
    await i.response.send_message(text, view=NextSteps(), ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())


class NextSteps(discord.ui.View):
    @discord.ui.button(label='求助／建議')
    async def help(self, i, button):
        await show_route(i, 'help')

    @discord.ui.button(label='先觀望')
    async def observe(self, i, button):
        await show_route(i, 'observe')
