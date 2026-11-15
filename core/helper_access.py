"""Fresh, least-privilege checks shared by every Helper interaction."""
import discord
import config

DEMO_ROOM_ID = 1570093470666854411  # Existing former sandbox; 06 must verify before reuse.


async def member_for(cog, interaction, *, demo=False):
    target = DEMO_ROOM_ID if demo else getattr(cog.channel, 'id', None)
    if (not cog.enabled or not target or interaction.guild_id != config.GUILD_ID
            or not interaction.guild or interaction.channel_id != target):
        return None
    try:
        member = await interaction.guild.fetch_member(interaction.user.id)
        channel = await interaction.guild.fetch_channel(target)
        p = channel.permissions_for(member)
        roles = set(config.HELPER_ROLE_IDS)
        if demo and cog.tester_id:
            roles.add(cog.tester_id)
        if (channel.guild.id == config.GUILD_ID and p.view_channel and p.read_message_history
                and (member.guild_permissions.administrator or any(r.id in roles for r in member.roles))):
            return member
    except discord.HTTPException:
        pass
    return None


async def source_for(cog, guild, member, channel_id):
    """Fetch the source (and thread parent) rather than trust an old card/cache."""
    try:
        channel = await guild.fetch_channel(channel_id)
        if channel.guild.id != config.GUILD_ID or not cog.can_read_source(channel, member):
            return None
        parent = channel
        if isinstance(channel, discord.Thread):
            if channel.type == discord.ChannelType.private_thread:
                return None
            parent = await guild.fetch_channel(channel.parent_id)
            p = parent.permissions_for(member)
            if not p.view_channel or not p.read_message_history:
                return None
        if getattr(parent, 'nsfw', False):
            return None  # Do not carry age-gated content into a non-age-gated panel.
        return channel
    except discord.HTTPException:
        return None
