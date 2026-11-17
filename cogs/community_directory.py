"""Private, guild-scoped directory cards; PIC is a contact, never an authority."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper, is_server_admin, is_verified_member
from core.storage_paths import DATA_DIR
from features.community_directory import Directory, DirectoryError, DirectoryUnavailable, STATUSES, public_text

PAGE_SIZE = 10
STATUS_CHOICES = [app_commands.Choice(name=label, value=value) for value, label in STATUSES.items()]


def safe_text(value: str) -> str:
    return discord.utils.escape_markdown(value.replace('@', '@\u200b'))


class CommunityDirectory(commands.Cog):
    community = app_commands.Group(name='community', description='公會目錄及聯絡卡', guild_ids=[config.GUILD_ID])

    def __init__(self, bot):
        self.bot = bot
        self.directory = Directory(DATA_DIR / 'community_directory.json', config.GUILD_ID)

    async def reply(self, interaction, content=None, *, embed=None):
        kwargs = dict(ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if embed is not None:
            kwargs['embed'] = embed
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(content, **kwargs)

    async def authorize(self, interaction, *, admin=False, editor=False):
        if interaction.guild_id != config.GUILD_ID or interaction.guild is None:
            await self.reply(interaction, '請在本社群伺服器使用公會目錄。')
            return False
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            guild = await self.bot.fetch_guild(config.GUILD_ID)
            member = await guild.fetch_member(interaction.user.id)
        except discord.HTTPException:
            await self.reply(interaction, '暫時無法確認你的會員權限，請稍後再試。')
            return False
        allowed = (is_server_admin(member) if admin else is_admin_or_helper(member)
                   or (not editor and is_verified_member(member)))
        if member.bot or not allowed:
            message = ('此操作只限本社群管理員。' if admin else
                       '只限本社群管理員或 Helper 建立及修改有效公會。' if editor else
                       '公會目錄只供本社群已驗證會員、Helper 及管理員查閱。')
            await self.reply(interaction, message)
            return False
        return member

    async def pic(self, interaction, user):
        try:
            member = await interaction.guild.fetch_member(user.id)
        except discord.NotFound:
            raise DirectoryError('聯絡 PIC 必須是本伺服器目前的非 Bot 成員。') from None
        except discord.HTTPException:
            raise DirectoryError('暫時無法確認聯絡 PIC，請稍後再試；資料未有更改。') from None
        if member.bot:
            raise DirectoryError('聯絡 PIC 不可是 Bot。')
        return member.id

    async def cog_app_command_error(self, interaction, error):
        cause = getattr(error, 'original', error)
        if isinstance(cause, DirectoryError):
            await self.reply(interaction, str(cause))
        elif isinstance(cause, DirectoryUnavailable):
            await self.reply(interaction, '公會目錄暫時無法讀寫；原有資料已保留，請通知管理員檢查儲存檔案。')
        else:
            await self.reply(interaction, '公會目錄暫時無法完成操作，請稍後再試。')
            raise error

    @community.command(name='list', description='私人查看公會目錄及代碼，每頁 10 個')
    @app_commands.describe(page='頁數，預設第 1 頁', archived='查看已封存公會（只限管理員）')
    async def list_cards(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 50] = 1, archived: bool = False):
        if not await self.authorize(interaction, admin=archived):
            return
        cards = self.directory.cards(archived=archived)
        pages = max(1, (len(cards) + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > pages:
            raise DirectoryError(f'目前只有 {pages} 頁，請重新選擇頁數。')
        embed = discord.Embed(title='已封存公會' if archived else '公會目錄',
                              description='用 /community show key:公會代碼 開啟公會卡。\nPIC 是聯絡人；此標示不授予管理權限。')
        for card in cards[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
            embed.add_field(name=safe_text(card['name']), value=f"代碼：`{card['key']}`\n{safe_text(card['game'])} · {STATUSES[card['status']]}\nPIC：<@{card['pic_id']}>", inline=False)
        if not cards:
            embed.description += '\n目前沒有公會。'
        embed.set_footer(text=f'第 {page}／{pages} 頁 · 共 {len(cards)} 個 · 使用 page 選擇下一頁')
        await self.reply(interaction, embed=embed)

    @community.command(name='show', description='私人開啟一張公會卡，查看聯絡 PIC')
    @app_commands.describe(key='公會固定代碼，可從 /community list 查看')
    async def show(self, interaction: discord.Interaction, key: str):
        if not await self.authorize(interaction):
            return
        card = self.directory.get(key)
        if card['archived'] and not await self.authorize(interaction, admin=True):
            return
        pic = f"<@{card['pic_id']}>"
        try:
            member = await interaction.guild.fetch_member(card['pic_id'])
            if member.bot:
                pic += '\n此聯絡人為 Bot，請管理員或 Helper 協助交接。'
        except discord.NotFound:
            pic += '\n此聯絡人已離開伺服器，請管理員或 Helper 協助交接。'
        except discord.HTTPException:
            pic += '\n暫時無法確認在服狀態，請稍後再試。'
        # PIC lookup is an external await: recheck the viewer before exposing data.
        if not await self.authorize(interaction, admin=card['archived']):
            return
        if self.directory.get(key) != card:
            raise DirectoryError('公會資料剛有更新，請重新開啟公會卡。')
        embed = discord.Embed(title=safe_text(card['name']), description=safe_text(card['notes']) or '尚未填寫公開簡介。')
        embed.add_field(name='公會代碼', value=card['key'])
        embed.add_field(name='遊戲', value=safe_text(card['game']))
        embed.add_field(name='招募狀態', value=STATUSES[card['status']])
        embed.add_field(name='聯絡 PIC', value=pic, inline=False)
        embed.set_footer(text=('已封存 · ' if card['archived'] else '') + '公開公會資料 · PIC 標示不授予管理權限 · 本回覆只有你看得到')
        await self.reply(interaction, embed=embed)

    @community.command(name='create', description='管理員／Helper：私人建立公會卡；公開資料供會員查閱')
    @app_commands.describe(key='固定代碼：小寫字母／數字／底線／連字號，最多 32 字', name='公會名稱（不可重複），最多 80 字', game='遊戲，最多 80 字', pic='目前在本伺服器的非 Bot 聯絡人', notes='公開簡介／備註，最多 700 字；勿填私人資料', status='招募狀態')
    @app_commands.choices(status=STATUS_CHOICES)
    async def create(self, interaction: discord.Interaction, key: str, name: str, game: str, pic: discord.User, notes: str = '', status: str = 'open'):
        if not await self.authorize(interaction, editor=True):
            return
        pic_id = await self.pic(interaction, pic)
        if not await self.authorize(interaction, editor=True):
            return
        card = self.directory.save(key, create=True, name=public_text(name, '公會名稱', 80), game=public_text(game, '遊戲', 80), pic_id=pic_id, notes=public_text(notes, '公開簡介', 700, empty=True), status=status)
        await self.reply(interaction, f"已建立公會 `{card['key']}`；已驗證會員可用 /community show 查閱。")

    @community.command(name='edit', description='管理員／Helper：修改有效公會或交接 PIC；封存公會只限管理員')
    @app_commands.describe(key='公會固定代碼（不可更改）', name='新公會名稱，最多 80 字', game='新遊戲，最多 80 字', pic='新聯絡 PIC；不會授予管理權限', notes='新公開簡介／備註，最多 700 字', clear_notes='清空公開簡介；不可同時填 notes', status='新招募狀態')
    @app_commands.choices(status=STATUS_CHOICES)
    async def edit(self, interaction: discord.Interaction, key: str, name: str | None = None, game: str | None = None, pic: discord.User | None = None, notes: str | None = None, clear_notes: bool = False, status: str | None = None):
        member = await self.authorize(interaction, editor=True)
        if not member:
            return
        if self.directory.get(key)['archived'] and not is_server_admin(member):
            raise DirectoryError('此操作只限本社群管理員。')
        changes = {}
        if clear_notes and notes is not None:
            raise DirectoryError('清空簡介與新簡介不可同時指定。')
        for field, value, label, limit in [('name', name, '公會名稱', 80), ('game', game, '遊戲', 80), ('notes', notes, '公開簡介', 700)]:
            if value is not None:
                changes[field] = public_text(value, label, limit, empty=field == 'notes')
        if clear_notes:
            changes['notes'] = ''
        if status is not None:
            changes['status'] = status
        if pic is not None:
            changes['pic_id'] = await self.pic(interaction, pic)
            member = await self.authorize(interaction, editor=True)
            if not member:
                return
        if not changes:
            raise DirectoryError('請至少指定一項要修改的資料。')
        # Re-read after the PIC/authorization awaits; gate and write without yielding.
        if self.directory.get(key)['archived'] and not is_server_admin(member):
            raise DirectoryError('此操作只限本社群管理員。')
        self.directory.save(key, **changes)
        await self.reply(interaction, f'已更新公會 `{key}`。')

    @community.command(name='archive', description='管理員：封存公會，從會員目錄移除並保留資料')
    @app_commands.describe(key='要封存的公會代碼')
    async def archive(self, interaction: discord.Interaction, key: str):
        if not await self.authorize(interaction, admin=True):
            return
        self.directory.save(key, archived=True)
        await self.reply(interaction, f'已封存公會 `{key}`；管理員可用 /community restore 還原。')

    @community.command(name='restore', description='管理員：用原有代碼還原已封存公會')
    @app_commands.describe(key='要還原的公會代碼')
    async def restore(self, interaction: discord.Interaction, key: str):
        if not await self.authorize(interaction, admin=True):
            return
        card = self.directory.get(key)
        await self.pic(interaction, discord.Object(id=card['pic_id']))
        if not await self.authorize(interaction, admin=True):
            return
        if self.directory.get(key) != card:
            raise DirectoryError('公會資料剛有更新，請重新執行還原。')
        self.directory.save(key, archived=False)
        await self.reply(interaction, f'已還原公會 `{key}`，會員可再次查閱。')


async def setup(bot):
    await bot.add_cog(CommunityDirectory(bot))
