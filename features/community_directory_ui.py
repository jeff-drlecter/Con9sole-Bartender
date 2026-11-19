"""Private, short-lived controls for the guild directory."""
from __future__ import annotations

from functools import partial

import discord

from core.permissions import is_admin_or_helper, is_server_admin
from features.community_directory import DirectoryError, STATUSES


class DirectoryView(discord.ui.View):
    def __init__(self, cog, owner_id):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await self.cog.reply(interaction, '請從 /公會 列表 開啟自己的私人目錄。')
        return False

    async def on_error(self, interaction, error, item):
        await self.cog.cog_app_command_error(interaction, error)

    async def navigate(self, interaction, render, **params):
        # Only this owner-bound View may request edits to its ephemeral component source.
        message = getattr(interaction, 'message', None)
        metadata = getattr(message, 'interaction_metadata', None)
        source_user = getattr(metadata, 'user', None)
        replace = (interaction.user.id == self.owner_id
                   and getattr(interaction, 'type', None) == discord.InteractionType.component
                   and getattr(getattr(message, 'flags', None), 'ephemeral', None) is True
                   and (source_user is None or getattr(source_user, 'id', None) == self.owner_id)
                   and not interaction.response.is_done())
        await render(interaction, replace=replace, **params)

    async def back_to_menu(self, interaction):
        menu = self.cog.bot.get_cog('Menu')
        if menu is None:
            await self.cog.reply(interaction, '主選單暫時無法開啟，請稍後再試。')
            return
        await menu.open_main_menu(interaction)

    def button(self, label, callback, *, disabled=False, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(label=label, disabled=disabled, style=style)
        button.callback = callback
        self.add_item(button)

    def list_controls(self, cards, page, pages, archived, member):
        if cards:
            select = discord.ui.Select(placeholder='選擇公會查看聯絡卡', row=0, options=[
                discord.SelectOption(label=card['name'], value=card['key'],
                                     description=f"{card['key']} · {STATUSES[card['status']]}")
                for card in cards
            ])

            async def open_card(interaction):
                await self.navigate(interaction, self.cog.render_card, key=select.values[0])

            select.callback = open_card
            self.add_item(select)
        if pages > 1:
            for label, target in [('上一頁', page - 1), ('下一頁', page + 1)]:
                callback = partial(self.navigate, render=self.cog.render_directory, page=target, archived=archived)
                self.button(label, callback, disabled=not 1 <= target <= pages)
        if is_admin_or_helper(member):
            self.button('建立公會卡', self.cog.open_form, style=discord.ButtonStyle.primary)
        if is_server_admin(member):
            self.button('有效公會' if archived else '已封存公會',
                        partial(self.navigate, render=self.cog.render_directory, archived=not archived))
        self.button('返回主選單', self.back_to_menu)

    def card_controls(self, card, member):
        key = card['key']
        self.button('返回目錄', partial(self.navigate, render=self.cog.render_directory, archived=card['archived']))
        if is_admin_or_helper(member):
            self.button('編輯公會／交接 PIC', partial(self.cog.open_form, card=card),
                        style=discord.ButtonStyle.primary)
        if is_server_admin(member):
            if card['archived']:
                self.button('還原公會', partial(self.cog.restore_card, key=key))
            else:
                self.button('封存公會', partial(self.cog.archive_card, key=key))


class DirectoryForm(discord.ui.Modal):
    def __init__(self, cog, owner_id, card=None):
        super().__init__(title='編輯公會卡' if card else '建立公會卡', timeout=600)
        self.cog, self.owner_id, self.card = cog, owner_id, card
        if card is None:
            self.key = self.text_field('固定代碼', 32, placeholder='例如 team-a，建立後不能更改')
        self.name = self.text_field('公會名稱', 80, default=card and card['name'])
        self.game = self.text_field('遊戲', 80, default=card and card['game'])
        self.notes = self.text_field('公開簡介', 700, default=card and card['notes'], required=False,
                                     style=discord.TextStyle.paragraph, placeholder='供會員查閱，請勿填寫私人資料')
        self.pic = discord.ui.UserSelect(required=card is None, min_values=0 if card else 1, max_values=1,
                                         placeholder='搜尋本伺服器的聯絡人')
        self.add_item(discord.ui.Label(text='新聯絡 PIC（留空保留原有 PIC）' if card else '聯絡 PIC', component=self.pic))
        if card:
            self.status = discord.ui.Select(options=[
                discord.SelectOption(label=label, value=value, default=value == card['status'])
                for value, label in STATUSES.items()
            ])
            self.add_item(discord.ui.Label(text='招募狀態', component=self.status))

    def text_field(self, label, limit, **kwargs):
        field = discord.ui.TextInput(max_length=limit, **kwargs)
        self.add_item(discord.ui.Label(text=label, component=field))
        return field

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await self.cog.reply(interaction, '請重新開啟自己的私人表單。')
        return False

    async def on_submit(self, interaction):
        pic = self.pic.values[0] if self.pic.values else None
        if pic is not None and not hasattr(pic, 'id'):
            raise DirectoryError('暫時無法確認所選聯絡人，請重新開啟表單。')
        if self.card is None:
            if pic is None:
                raise DirectoryError('請選擇公會聯絡 PIC。')
            await self.cog.create_card(interaction, key=self.key.value, name=self.name.value,
                                       game=self.game.value, notes=self.notes.value, pic=pic)
        else:
            await self.cog.update_card(interaction, key=self.card['key'], name=self.name.value,
                                       game=self.game.value, notes=self.notes.value, pic=pic,
                                       status=self.status.values[0], expected=self.card)

    async def on_error(self, interaction, error):
        await self.cog.cog_app_command_error(interaction, error)
