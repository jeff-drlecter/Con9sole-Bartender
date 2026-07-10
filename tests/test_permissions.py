from __future__ import annotations

import unittest
from unittest.mock import Mock

import discord

import config
from core.permissions import is_admin_or_helper, is_verified_member


def make_member(*, administrator: bool = False, manage_guild: bool = False, roles: list[Mock] | None = None) -> Mock:
    member = Mock(spec=discord.Member)
    member.guild_permissions = Mock(
        administrator=administrator,
        manage_guild=manage_guild,
    )
    member.roles = roles or []
    return member


def make_role(role_id: int, name: str) -> Mock:
    role = Mock(spec=discord.Role)
    role.id = role_id
    role.name = name
    return role


class PermissionTests(unittest.TestCase):
    def test_administrator_is_allowed(self) -> None:
        self.assertTrue(is_admin_or_helper(make_member(administrator=True)))

    def test_helper_role_id_is_allowed(self) -> None:
        helper_id = config.HELPER_ROLE_IDS[0]
        member = make_member(roles=[make_role(helper_id, "renamed-helper")])

        self.assertTrue(is_admin_or_helper(member))

    def test_ordinary_member_is_rejected(self) -> None:
        member = make_member(roles=[make_role(123, "member")])

        self.assertFalse(is_admin_or_helper(member))

    def test_verified_role_is_detected(self) -> None:
        member = make_member(roles=[make_role(config.VERIFIED_ROLE_ID, "verified")])

        self.assertTrue(is_verified_member(member))

    def test_non_member_is_rejected(self) -> None:
        user = Mock(spec=discord.User)

        self.assertFalse(is_admin_or_helper(user))
        self.assertFalse(is_verified_member(user))


if __name__ == "__main__":
    unittest.main()
