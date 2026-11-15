"""Fresh source authorization for owner-bound private UI; no privilege shortcuts."""
import asyncio
from copy import copy
from dataclasses import dataclass
import discord


class SourceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Source:
    owner: int
    guild: int
    channel: int
    message: int | None = None

    async def resolve(self, i):
        if (i.user.id != self.owner or i.user.bot or i.guild_id != self.guild
                or i.guild is None or i.guild.id != self.guild or i.channel_id != self.channel):
            raise SourceUnavailable()
        try:
            member, channel = await fresh_access(i.guild, self.owner, self.channel)
            message = await channel.fetch_message(self.message) if self.message else None
            if message and message.author.id != i.client.user.id:
                raise SourceUnavailable()
            return member, channel, message
        except (discord.HTTPException, OSError) as exc:
            raise SourceUnavailable() from exc


async def fresh_access(guild, owner, channel_id):
    """Use REST roles/member/overwrites in a local snapshot, never mutate gateway cache."""
    try:
        member = copy(await guild.fetch_member(owner))
        channel = copy(await guild.fetch_channel(channel_id))
        if channel.guild.id != guild.id or member.bot:
            raise SourceUnavailable()
        snapshot = copy(guild)
        snapshot._roles = {role.id: role for role in await guild.fetch_roles()}
        member.guild = snapshot
        channel.guild = snapshot
        if isinstance(channel, discord.Thread):
            parent = copy(await guild.fetch_channel(channel.parent_id))
            if parent.guild.id != guild.id:
                raise SourceUnavailable()
            parent.guild = snapshot
            snapshot._channels = dict(getattr(guild, '_channels', {}))
            snapshot._channels[parent.id] = parent
            p = parent.permissions_for(member)
            if not p.view_channel or not p.read_message_history:
                raise SourceUnavailable()
            if channel.is_private():
                await channel.fetch_member(owner)
        p = channel.permissions_for(member)
        if not p.view_channel or not p.read_message_history:
            raise SourceUnavailable()
        return member, channel
    except (discord.HTTPException, OSError) as exc:
        raise SourceUnavailable() from exc


async def visible_people(guild, channel, ids):
    """Retain existing roster rule: current human members with source View."""
    semaphore = asyncio.Semaphore(5)
    async def one(uid):
        async with semaphore:
            try:
                member = await guild.fetch_member(int(uid))
            except discord.NotFound:
                return None
            except (discord.HTTPException, OSError) as exc:
                raise SourceUnavailable() from exc
            if member.bot or not channel.permissions_for(member).view_channel:
                return None
            if isinstance(channel, discord.Thread) and channel.is_private():
                try:
                    await channel.fetch_member(int(uid))
                except discord.NotFound:
                    return None
                except (discord.HTTPException, OSError) as exc:
                    raise SourceUnavailable() from exc
            return int(uid), discord.utils.escape_mentions(discord.utils.escape_markdown(member.display_name))
    return [row for row in await asyncio.gather(*(one(uid) for uid in ids)) if row]
