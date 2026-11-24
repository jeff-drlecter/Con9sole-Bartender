"""Optional community links and private, freshly authorized squad selection."""
from __future__ import annotations

from functools import partial

import discord

from cogs.community_directory import safe_text
from features.community_directory import DirectoryError, DirectoryUnavailable
from features.community_directory_ui import DirectoryView

PAGE_SIZE = 25


async def _reply(interaction, content):
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(content, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def active_community(bot, key, *, strict=False):
    """A missing, archived or unreadable link never prevents an ordinary squad card."""
    if not key:
        return None
    cog = bot.get_cog('CommunityDirectory')
    if cog is None:
        if strict:
            raise DirectoryUnavailable
        return None
    try:
        card = cog.directory.get(key)
    except DirectoryError:
        return None
    except DirectoryUnavailable:
        if strict:
            raise
        return None
    return None if card['archived'] else card


def add_community_field(embed, card):
    if card is not None and not card['archived']:
        embed.add_field(name='公會', value=safe_text(card['name']), inline=False)


def add_community_details(view, bot, key, *, custom_id, row=None):
    if not key:
        return
    button = discord.ui.Button(label='查看公會', custom_id=custom_id, row=row)

    async def details(interaction):
        cog = bot.get_cog('CommunityDirectory')
        if cog is None:
            await _reply(interaction, '公會目錄暫時無法開啟，請稍後再試。')
            return
        try:
            # render_card validates the guild and fetches fresh roles before reading.
            # active_only also closes the archive race during its authorization await.
            await cog.render_card(interaction, key=key, active_only=True)
        except (DirectoryError, DirectoryUnavailable) as error:
            await cog.cog_app_command_error(interaction, error)

    button.callback = details
    view.add_item(button)


class CommunityPicker(DirectoryView):
    def __init__(self, cog, owner_id, on_select, current_key):
        super().__init__(cog, owner_id)
        self.on_select = on_select
        self.current_key = current_key

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await _reply(interaction, '請從自己的召集卡開啟公會選擇。')
        return False

    async def render(self, interaction, *, page=1, replace=False):
        if not await self.interaction_check(interaction):
            return
        if not await self.cog.authorize(interaction, replace=replace):
            return
        cards = self.cog.directory.cards()
        pages = max(1, (len(cards) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, page), pages)
        visible = cards[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        current = next((card for card in cards if card['key'] == self.current_key), None)
        description = '所有遊戲的有效公會均可選擇；請自行確認名稱及遊戲。'
        description += ('\n目前選擇：' + safe_text(current['name']) if current else '\n目前沒有有效公會連結。')
        if not cards:
            description += '\n目前沒有有效公會；可繼續使用沒有公會的召集卡。'
        embed = discord.Embed(title='選擇召集卡公會', description=description)
        embed.set_footer(text=f'第 {page}／{pages} 頁 · 共 {len(cards)} 個 · 只有你看得到')
        view = CommunityPicker(self.cog, self.owner_id, self.on_select, self.current_key)
        if visible:
            select = discord.ui.Select(placeholder='選擇公會（名稱／遊戲）', row=0, options=[
                discord.SelectOption(label=card['name'].replace('@', '@\u200b')[:100], value=card['key'],
                                     description=card['game'].replace('@', '@\u200b')[:100],
                                     default=card['key'] == self.current_key)
                for card in visible
            ])

            async def selected(component):
                if len(select.values) != 1 or select.values[0] not in {card['key'] for card in visible}:
                    await _reply(component, '請重新開啟公會選擇。')
                    return
                await view.select(component, select.values[0])

            select.callback = selected
            view.add_item(select)
        if pages > 1:
            for label, target in [('上一頁', page - 1), ('下一頁', page + 1)]:
                view.button(label, partial(view.navigate, render=view.render, page=target),
                            disabled=not 1 <= target <= pages)
        view.button('不選公會／移除公會', partial(view.select, key=None))
        await self.cog.send_panel(interaction, embed=embed, view=view, replace=replace)

    async def select(self, interaction, key):
        if not await self.interaction_check(interaction):
            return
        # Always thinking=True: the business callback must never edit a public source
        # merely because this interaction came from a component.
        if not await self.cog.authorize(interaction):
            return
        if key is not None:
            card = self.cog.directory.get(key)
            if card['archived']:
                raise DirectoryError('此公會已停用，請重新選擇。')
        await self.on_select(interaction, key)


async def choose_community(interaction, bot, on_select, *, current_key=None):
    """Open a separate private picker; on_select receives an acknowledged interaction."""
    cog = bot.get_cog('CommunityDirectory')
    if cog is None:
        await _reply(interaction, '公會目錄暫時無法開啟；你仍可使用沒有公會的召集卡。')
        return
    view = CommunityPicker(cog, interaction.user.id, on_select, current_key)
    try:
        # Never replace the calling draft/public card, even if it was already ACKed.
        await view.render(interaction)
    except (DirectoryError, DirectoryUnavailable) as error:
        await cog.cog_app_command_error(interaction, error)
