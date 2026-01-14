# cogs/role_channel_factory.py
# Versioned Channel Factory (Final Clean Model)
# Assumptions:
# - Category visibility is controlled ONLY by a global role (e.g. EA FC Player)
# - @everyone has NO access to the category
# - Versioned channels grant:
#   * Full access to newest version role
#   * Read-only access to ALL older version roles
# - @everyone is NEVER touched at channel level

import discord
from discord.ext import commands
from discord import app_commands

SUPPORTED_TYPES = (
    discord.ChannelType.text,
    discord.ChannelType.forum,
    discord.ChannelType.voice,
    discord.ChannelType.stage_voice,
)

READ_ONLY = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=False,
    create_public_threads=False,
    create_private_threads=False,
    send_messages_in_threads=False,
    # read_message_history is inherited from category (EA FC Player)
)

class RoleChannelFactory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="role_channel_new",
        description="Clone a versioned channel and generate a new version role",
    )
    @app_commands.describe(
        source_channel="Sample version channel",
        new_role_name="New version role name",
        new_channel_name="Optional new channel name",
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

        # ---------- Validation ----------
        if source_channel.type not in SUPPORTED_TYPES:
            await interaction.response.send_message(
                "❌ Unsupported channel type",
                ephemeral=True,
            )
            return

        # Identify sample version role (exactly ONE)
        sample_role: discord.Role | None = None
        for target in source_channel.overwrites:
            if not isinstance(target, discord.Role):
                continue
            if target.is_default():
                continue
            if target.permissions.administrator:
                continue
            if sample_role is not None:
                await interaction.response.send_message(
                    "❌ Source channel must contain exactly ONE version role overwrite",
                    ephemeral=True,
                )
                return
            sample_role = target

        if sample_role is None:
            await interaction.response.send_message(
                "❌ No version role found in source channel",
                ephemeral=True,
            )
            return

        # Ensure new role does not exist
        if discord.utils.get(guild.roles, name=new_role_name):
            await interaction.response.send_message(
                f"❌ Role `{new_role_name}` already exists",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # ---------- Create new role ----------
        try:
            new_role = await guild.create_role(
                name=new_role_name,
                reason="Version upgrade: create new version role",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create role: {e}")
            return

        # ---------- Clone channel ----------
        channel_name = new_channel_name or f"{source_channel.name}_temp"
        try:
            new_channel = await source_channel.clone(
                name=channel_name,
                reason="Version upgrade: clone channel",
            )
        except Exception as e:
            await new_role.delete(reason="Rollback: channel clone failed")
            await interaction.followup.send(f"❌ Failed to clone channel: {e}")
            return

        # ---------- Build overwrites ----------
        try:
            overwrites = new_channel.overwrites

            # Full access for new version role (copied from sample)
            overwrites[new_role] = overwrites[sample_role]

            # Read-only for ALL other legacy version roles
            prefix = sample_role.name.split()[0]
            for role in guild.roles:
                if role == new_role or role == sample_role:
                    continue
                if role.permissions.administrator:
                    continue
                if prefix not in role.name:
                    continue
                overwrites[role] = READ_ONLY

            # Remove sample role overwrite
            overwrites.pop(sample_role, None)

            # NEVER touch @everyone

            await new_channel.edit(overwrites=overwrites)
        except Exception as e:
            await new_channel.delete(reason="Rollback: overwrite failure")
            await new_role.delete(reason="Rollback: overwrite failure")
            await interaction.followup.send(f"❌ Failed to apply permissions: {e}")
            return

        # ---------- Success ----------
        await interaction.followup.send(
            f"✅ New version channel created: {new_channel.mention}\n"
            f"➕ New role created: `{new_role.name}`\n"
            f"🔒 Legacy versions set to read-only"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleChannelFactory(bot))
