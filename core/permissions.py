from __future__ import annotations

import discord
import config


HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = {
    str(name).strip().casefold()
    for name in getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper", "helpers"])
    if str(name).strip()
}


def is_helper(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    for role in member.roles:
        if role.id in HELPER_ROLE_IDS:
            return True
        if role.name.strip().casefold() in HELPER_ROLE_NAMES:
            return True

    return False


def is_admin_or_helper(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True

    return is_helper(member)


def is_verified_member(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    verified_role_id = getattr(config, "VERIFIED_ROLE_ID", None)
    if verified_role_id is None:
        return False

    return any(role.id == verified_role_id for role in member.roles)


def is_server_admin(member: discord.Member | discord.User) -> bool:
    """Configuration authority must never come from the Helpers role."""
    return isinstance(member, discord.Member) and bool(
        member.guild_permissions.administrator or member.guild_permissions.manage_guild
    )


def is_moderator(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    return is_server_admin(member) or (
        perms.moderate_members is True and perms.manage_messages is True
    )


def can_use_staff_tool(member: discord.Member | discord.User, item_id: str) -> bool:
    if is_server_admin(member):
        return True
    if item_id in {"admin_tool", "admin_stats", "admin_ping", "bot_health"}:
        return is_helper(member) or is_moderator(member)
    if item_id == "admin_roles":
        return is_helper(member)  # single safe role changes retain their own checks
    if item_id == "admin_vc_teardown":
        return is_moderator(member)
    return False
