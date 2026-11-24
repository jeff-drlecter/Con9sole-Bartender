"""Optional community on a squad plan. The directory remains the source of public names."""
import logging
import sqlite3
from types import SimpleNamespace

import discord

from features.community_directory import DirectoryUnavailable
from features.plan_services import AccessError, fresh_source, source
from features.squad_community import active_community, choose_community
from features.squad_plans import ACTIVE

log = logging.getLogger(__name__)


def draft_line(cog, data):
    key = data.get('community_key')
    if not key:
        return ''
    card = active_community(cog.bot, key)
    if card is None:
        return '\n本局公會已無法查閱，請重新選擇或移除。'
    name = discord.utils.escape_mentions(discord.utils.escape_markdown(card['name']))
    return f'\n🏷️ 本局公會：{name}（開局後用作語音房名稱）'


def add_draft_picker(view, data, owner_id):
    button = discord.ui.Button(label='選擇公會（選填）', row=1)

    async def open_picker(interaction):
        if not await view.interaction_check(interaction):
            return
        # Defer the update to the private draft so the selection can refresh that same message.
        await interaction.response.defer()

        async def select(click, key):
            from cogs.squad_plans import allowed
            try:
                member, channel = await fresh_source(click.guild, click.user.id, view.channel.id)
            except AccessError:
                await click.edit_original_response(content='無法核對原頻道，請重新開啟草稿。')
                return
            if (click.user.id != owner_id or view.used or view.is_finished()
                    or not allowed(SimpleNamespace(guild_id=click.guild_id, user=member), channel)):
                await click.edit_original_response(content='草稿已關閉或無法修改。')
                return
            if key and not active_community(view.cog.bot, key):
                await click.edit_original_response(content='此公會已無法選擇。')
                return
            if key:
                data['community_key'] = key
            else:
                data.pop('community_key', None)
            await interaction.edit_original_response(content=view.summary(), view=view,
                                                     allowed_mentions=discord.AllowedMentions.none())
            await click.edit_original_response(content='已更新草稿的公會選擇。')

        await choose_community(interaction, view.cog.bot, select, current_key=data.get('community_key'))

    button.callback = open_picker
    view.add_item(button)


async def edit_plan_community(cog, interaction, plan_id):
    from cogs.squad_plans import allowed
    initial = cog.book.get(plan_id)
    if (not initial or initial['owner'] != interaction.user.id or initial['status'] not in ACTIVE
            or initial['guild'] != interaction.guild_id or initial['channel'] != interaction.channel_id):
        await interaction.response.send_message('只有發起人可以修改本局公會。', ephemeral=True)
        return

    async def select(click, key):
        async with cog.lock:
            try:
                member, channel = await source(cog, click.guild, click.user.id, initial)
                if not allowed(SimpleNamespace(guild_id=click.guild_id, user=member), channel):
                    raise AccessError('denied')
                if key and not active_community(cog.bot, key):
                    raise ValueError('公會已無法選擇，請重新開啟。')
                updated = cog.book.set_community(plan_id, member.id, key, expected=initial)
                synced = await sync_community_rooms(cog, updated)
                refreshed = await cog.refresh(cog.book.get(plan_id))
            except AccessError:
                await click.edit_original_response(content='無法核對原卡或你的權限。')
                return
            except ValueError as exc:
                await click.edit_original_response(content=str(exc))
                return
        message = '已儲存本局公會設定。'
        if not synced or not refreshed:
            message += '卡片或房名仍待同步。'
        elif updated.get('voice'):
            message += '語音房名稱會按 Discord 改名限制更新。'
        await click.edit_original_response(content=message)

    await choose_community(interaction, cog.bot, select, current_key=initial.get('community_key'))


async def sync_community_rooms(cog, plan):
    """Hand off persisted room IDs to TempVC. Clear a receipt only after durable acceptance."""
    complete = True
    for room_id in plan.get('community_rooms_pending', []):
        room = cog.bot.get_channel(room_id)
        try:
            if room is None:
                room = await cog.bot.fetch_channel(room_id)
            plan = cog.book.get(plan['id'])
            if room_id not in plan.get('community_rooms_pending', []):
                continue
            if not isinstance(room, discord.VoiceChannel) or room.guild.id != plan['guild']:
                # IDs cannot change channel type or move to another guild.
                cog.book.community_room_synced(plan['id'], room_id, plan)
                continue
            tempvc = cog.bot.get_cog('TempVC')
            if tempvc is None:
                return False
            name = None
            if plan.get('voice') == room_id and plan['status'] in {'gathering', 'live'}:
                community = active_community(cog.bot, plan.get('community_key'), strict=True)
                name = community['name'] if community else None
            if not await tempvc.set_community_name(room, name, owner_id=plan['owner'], source=f"plan:{plan['id']}"):
                complete = False
                continue
        except discord.NotFound:
            pass  # Discord has already removed the target room.
        except (discord.HTTPException, DirectoryUnavailable, OSError, sqlite3.Error):
            log.warning('Community room name pending for plan %s', plan['id'], exc_info=True)
            complete = False
            continue
        cog.book.community_room_synced(plan['id'], room_id, plan)
    return complete
