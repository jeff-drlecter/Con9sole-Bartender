from __future__ import annotations

import discord
import config


HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = set(getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper", "helpers"]))


def is_admin_or_helper(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True

    for role in member.roles:
        if role.id in HELPER_ROLE_IDS:
            return True
        if role.name in HELPER_ROLE_NAMES:
            return True

    return False


def is_verified_member(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    verified_role_id = getattr(config, "VERIFIED_ROLE_ID", None)
    if verified_role_id is None:
        return False

    return any(role.id == verified_role_id for role in member.roles)
