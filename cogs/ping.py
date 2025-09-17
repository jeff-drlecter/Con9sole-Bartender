import discord
from discord import app_commands
from discord.ext import commands
import config

class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Bot 反應時間")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def ping_cmd(self, inter: discord.Interaction):
        await inter.response.send_message(
            f"Pong! 🏓 {round(self.bot.latency * 1000)}ms", ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
