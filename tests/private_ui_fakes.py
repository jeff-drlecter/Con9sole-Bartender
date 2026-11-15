"""Fresh API fixture; mutations are reflected by every subsequent request."""
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
import discord


def attach(i, people=None):
    people = people if people is not None else {i.user.id:i.user}
    i.channel.guild=i.guild
    i.message.channel=i.channel
    if not getattr(i.channel, 'fetch_message', None):
        i.channel.fetch_message=AsyncMock(return_value=i.message)
    async def member(uid):
        value=people.get(uid)
        if value is None:
            raise discord.NotFound(N(status=404,reason='gone'), {'message':'gone','code':10007})
        return value
    i.guild.fetch_member=AsyncMock(side_effect=member)
    i.guild.fetch_roles=AsyncMock(return_value=[])
    i.guild.fetch_channel=AsyncMock(return_value=i.channel)
    return i
