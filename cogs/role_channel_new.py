# cogs/role_channel_factory.py
# Generic versioned channel factory
# Create a new channel + new role by cloning a sample channel
# and replacing the sample role overwrite with the new role

import discord
from discord.ext import commands
from discord import app_commands

SUPPORTED_TYPES = (
    discord.ChannelType.text,
    discord.ChannelType.forum,
    discord.ChannelType.voice,
    discord.ChannelType.stage_voice,
)

class RoleChannelFactory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="role_channel_new",
        description="Clone a channel and replace its version role with a new one",
    )
    @app_commands.describe(
        source_channel="Sample channel to clone",
        new_role_name="Name of the new version role",
        new_channel_name="Optional new channel name (default: source_temp)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def role_channel_new(
        self,
        interaction: discord.Interaction,
        source_channel: discord.abc.GuildChannel,
        new_role_name: str,
        new_channel_name: str | None = None,
    ):
        guild = interaction.guild

        # --- Validation ---
        if source_channel.type not in SUPPORTED_TYPES:
            await interaction.response.send_message(
                "❌ Unsupported channel type",
                ephemeral=True,
            )
            return

        # Identify sample role from overwrites
        sample_role = None
        for target, overwrite in source_channel.overwrites.items():
            if isinstance(target, discord.Role):
                if target.is_default():
                    continue
                if target.permissions.administrator:
                    continue
                if sample_role is not None:
                    await interaction.response.send_message(
                        "❌ Source channel has multiple non-admin roles. Clean template first.",
                        ephemeral=True,
                    )
                    return
                sample_role = target

        if sample_role is None:
            await interaction.response.send_message(
                "❌ No sample role found in source channel",
                ephemeral=True,
            )
            return

        # Check role existence
        if discord.utils.get(guild.roles, name=new_role_name):
            await interaction.response.send_message(
                f"❌ Role `{new_role_name}` already exists",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # --- Create role ---
        try:
            new_role = await guild.create_role(
                name=new_role_name,
                reason="Versioned channel role creation",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create role: {e}")
            return

        # --- Clone channel ---
        channel_name = new_channel_name or f"{source_channel.name}_temp"
        try:
            new_channel = await source_channel.clone(
                name=channel_name,
                reason="Versioned channel clone",
            )
        except Exception as e:
            await new_role.delete(reason="Rollback: clone failed")
            await interaction.followup.send(f"❌ Failed to clone channel: {e}")
            return

        # --- Replace role overwrite ---
        try:
            overwrites = new_channel.overwrites
            sample_overwrite = overwrites.get(sample_role)
            if sample_overwrite is None:
                raise RuntimeError("Sample role overwrite missing after clone")

            # Apply identical permissions to new role
            overwrites[new_role] = sample_overwrite
            overwrites.pop(sample_role, None)

            # Passive users: visible but read-only
            everyone = guild.default_role
            passive = overwrites.get(everyone, discord.PermissionOverwrite())
            passive.view_channel = True
            passive.send_messages = False
            passive.create_public_threads = False
            passive.create_private_threads = False
            passive.send_messages_in_threads = False
            overwrites[everyone] = passive

            await new_channel.edit(overwrites=overwrites)
        except Exception as e:
            await new_channel.delete(reason="Rollback: overwrite failed")
            await new_role.delete(reason="Rollback: overwrite failed")
            await interaction.followup.send(f"❌ Failed to replace role overwrite: {e}")
            return

        # --- Success ---
        await interaction.followup.send(
            f"✅ Channel created: {new_channel.mention}\n"
            f"➕ Role created: `{new_role.name}`\n"
            f"🔁 Replaced `{sample_role.name}` permissions",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleChannelFactory(bot))
