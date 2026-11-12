"""Fail closed if audit copies can be read outside the configured staff audience."""
import discord
import config


def require_private_audit_channel(channel, *, admin_only=False):
    guild=channel.guild
    staff_ids={config.MOD_ROLE_ID, *config.HELPER_ROLE_IDS} if not admin_only else set()

    def trusted_role(role):
        return bool(role.permissions.administrator or role.permissions.manage_guild
                    or role.is_bot_managed() or role.id in staff_ids)

    def trusted_member(member):
        return bool(member and (member.id==guild.owner_id or member.bot
                    or any(trusted_role(role) for role in member.roles)))

    for role in guild.roles:
        if not trusted_role(role) and channel.permissions_for(role).view_channel:
            raise RuntimeError(f'日誌頻道對非授權身份組開放：{role.id}')
    for target,overwrite in channel.overwrites.items():
        if not isinstance(target,discord.Role) and overwrite.view_channel is True:
            if not trusted_member(guild.get_member(target.id)):
                raise RuntimeError(f'日誌頻道對非授權成員開放：{target.id}')
    # Also cover effective permissions from combinations of roles/member overwrites.
    for member in guild.members:
        if not trusted_member(member) and channel.permissions_for(member).view_channel:
            raise RuntimeError(f'日誌頻道對非授權成員可見：{member.id}')
