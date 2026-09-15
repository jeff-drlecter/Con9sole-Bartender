from __future__ import annotations

from discord.ext import commands


class RoleChannelFactory(commands.Cog):
    """Deprecated compatibility cog.

    The old /role_channel_new command has been retired. Game creation is handled by
    /add_new_game and /add_game_version in cogs.duplicate.

    Keeping this empty extension allows a live `/reload role_channel_factory` to
    unload the legacy command cleanly before the next full bot restart/sync.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleChannelFactory(bot))
