"""Role Tools must enforce caller authority independently of Bot permissions."""
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import cogs.role as roles


class Role:
    def __init__(self, uid, position, *, name='game', managed=False, **permissions):
        self.id, self.position, self.name, self.managed = uid, position, name, managed
        self.permissions = discord.Permissions(**permissions)
        self.mention = f'<@&{uid}>'
    def is_default(self): return self.id == 1
    def __ge__(self, other): return self.position >= other.position
    def __gt__(self, other): return self.position > other.position


def member(uid, position, *, helper=False, administrator=False):
    value = MagicMock(spec=discord.Member)
    value.id, value.top_role = uid, Role(uid + 1000, position)
    value.bot = False
    value.roles = [Role(987, position, name='helpers')] if helper else []
    value.guild_permissions = discord.Permissions(administrator=administrator)
    value.mention = f'<@{uid}>'
    value.add_roles, value.remove_roles = AsyncMock(), AsyncMock()
    return value


class RoleAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = member(10, 20, helper=True)
        self.target = member(11, 5)
        self.role = Role(50, 10)
        self.bot_member = member(999, 100, administrator=True)
        self.bot_member.guild_permissions = discord.Permissions(administrator=True, manage_roles=True)
        self.guild = types.SimpleNamespace(me=self.bot_member, owner=member(99, 101),
            get_role=lambda uid: self.role if uid == self.role.id else None, members=[self.actor, self.target])
        self.bot = MagicMock()
        self.bot.get_cog.return_value = None
        self.inter = types.SimpleNamespace(guild=self.guild, user=self.actor,
            response=types.SimpleNamespace(is_done=lambda: True),
            followup=types.SimpleNamespace(send=AsyncMock()))
        self.cog = roles.RoleManager(self.bot)

    async def apply(self, *, target=None, bulk=None, mode='add'):
        await self.cog._apply_role_change(self.inter, str(self.role.id),
            target if bulk is None else None, bulk, False, mode)

    async def test_helper_cannot_self_grant_or_revoke_administrator_role(self):
        self.role = Role(50, 10, administrator=True)
        for mode in ('add', 'remove'):
            await self.apply(target=self.actor, mode=mode)
        self.actor.add_roles.assert_not_awaited()
        self.actor.remove_roles.assert_not_awaited()

    async def test_manage_guild_cannot_delegate_management_powers(self):
        self.actor.guild_permissions = discord.Permissions(manage_guild=True)
        for permission in ('manage_roles', 'ban_members', 'manage_messages', 'manage_webhooks'):
            self.role = Role(50, 10, **{permission: True})
            await self.apply(target=self.target)
        self.target.add_roles.assert_not_awaited()

    async def test_actor_role_and_target_hierarchy_are_enforced(self):
        for position in (20, 50):
            self.role = Role(50, position)
            await self.apply(target=self.actor)
        self.actor.add_roles.assert_not_awaited()
        self.role = Role(50, 10)
        self.target.top_role = Role(61, 25)
        await self.apply(target=self.target)
        self.target.add_roles.assert_not_awaited()

    async def test_direct_shared_engine_rejects_unprivileged_caller(self):
        self.actor.roles = []
        await self.apply(target=self.target)
        self.target.add_roles.assert_not_awaited()

    async def test_safe_lower_game_role_still_works(self):
        await self.apply(target=self.target)
        self.target.add_roles.assert_awaited_once()

    async def test_only_safe_self_mod_exception_is_retained(self):
        self.role = Role(roles.MOD_ROLE_ID, 40)
        await self.apply(target=self.actor)
        self.actor.add_roles.assert_awaited_once()
        await self.apply(target=self.target)
        self.target.add_roles.assert_not_awaited()
        self.actor.add_roles.reset_mock()
        self.role = Role(roles.MOD_ROLE_ID, 40, manage_roles=True)
        await self.apply(target=self.actor)
        self.actor.add_roles.assert_not_awaited()

    async def test_generic_tools_cannot_touch_level_managed_roles(self):
        self.actor.guild_permissions = discord.Permissions(administrator=True)
        self.bot.get_cog.return_value = types.SimpleNamespace(cfg={'rewards': {'15': 50}})
        for mode in ('add', 'remove'):
            await self.apply(target=self.target, mode=mode)
        self.target.add_roles.assert_not_awaited()
        self.target.remove_roles.assert_not_awaited()

    async def test_bulk_skips_higher_members_and_processes_lower_members(self):
        self.actor.guild_permissions = discord.Permissions(administrator=True)
        group = Role(70, 1)
        high = member(12, 40)
        high.roles.append(group)
        self.target.roles.append(group)
        self.guild.members = [high, self.target]
        with patch.object(roles.asyncio, 'sleep', new=AsyncMock()):
            await self.apply(bulk=group)
        high.add_roles.assert_not_awaited()
        self.target.add_roles.assert_awaited_once()

    async def test_helper_cannot_bulk_change_even_safe_roles(self):
        group = Role(70, 1)
        self.target.roles.append(group)
        await self.apply(bulk=group)
        self.target.add_roles.assert_not_awaited()

    async def test_bulk_privileged_role_is_rejected_before_first_member(self):
        group = Role(70, 1)
        self.target.roles.append(group)
        self.role = Role(50, 10, administrator=True)
        await self.apply(bulk=group)
        self.target.add_roles.assert_not_awaited()

    async def test_managed_system_role_cannot_be_changed(self):
        self.role = Role(50, 10, managed=True)
        await self.apply(target=self.target)
        self.target.add_roles.assert_not_awaited()
