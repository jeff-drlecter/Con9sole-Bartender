from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock

import discord


def member(user_id=10, *, bot=False, guild=None):
    result = MagicMock(spec=discord.Member)
    result.id, result.bot = user_id, bot
    result.mention = f"<@{user_id}>"
    result.guild = guild
    result.roles = []
    result.voice = None
    result.guild_permissions = discord.Permissions.none()
    return result


def interaction(user=None, *, guild=None, channel=None, can_send=True):
    guild = guild or MagicMock(spec=discord.Guild)
    guild.id = 1
    user = user or member(guild=guild)
    channel = channel or MagicMock(spec=discord.TextChannel)
    channel.id = 100
    channel.guild = guild
    response = MagicMock()
    response.is_done.return_value = False

    async def acknowledge(*args, **kwargs):
        response.is_done.return_value = True

    response.defer = AsyncMock(side_effect=acknowledge)
    response.send_message = AsyncMock(side_effect=acknowledge)
    response.edit_message = AsyncMock(side_effect=acknowledge)
    response.send_modal = AsyncMock(side_effect=acknowledge)
    permissions = discord.Permissions.none()
    permissions.view_channel = True
    permissions.send_messages = can_send
    permissions.send_messages_in_threads = can_send
    message = MagicMock(spec=discord.InteractionMessage)
    message.id = 500
    message.edit = AsyncMock()
    result = N(
        id=900,
        user=user,
        guild=guild,
        guild_id=guild.id,
        channel=channel,
        channel_id=channel.id,
        permissions=permissions,
        response=response,
        followup=N(send=AsyncMock()),
        edit_original_response=AsyncMock(return_value=message),
        original_response=AsyncMock(return_value=message),
        message=message,
        client=MagicMock(),
    )
    return result
