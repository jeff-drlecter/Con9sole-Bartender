"""Authorization must block delegated Bot operations before any side effect."""
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from core.permissions import can_use_staff_tool, is_server_admin, is_moderator
from cogs.reload import can_use_reload
from cogs.duplicate import user_can_manage_games
from cogs.update_publisher import _publisher_access_allowed
from cogs.tempvc import user_can_admin_teardown
from features import admin_actions
from features.menu_views import AdminToolView
from features.notification_review_views import permitted


def member(*, helper=False, **perms):
    m=MagicMock(spec=discord.Member)
    m.id=123
    m.guild_permissions=discord.Permissions(**perms)
    m.roles=[types.SimpleNamespace(id=999,name='Helpers')] if helper else []
    return m


class StaffBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_helper_is_not_system_administrator(self):
        m=member(helper=True)
        i=types.SimpleNamespace(user=m,guild=object())
        self.assertFalse(is_server_admin(m))
        self.assertFalse(can_use_reload(m))
        self.assertFalse(user_can_manage_games(i))
        self.assertFalse(_publisher_access_allowed(i))
        self.assertFalse(user_can_admin_teardown(m))
        for key in ('admin_reload','admin_game_tools','admin_update_publisher','community_levels_admin','title_roles_admin','admin_vc_teardown'):
            self.assertFalse(can_use_staff_tool(m,key),key)
        for key in ('admin_stats','admin_ping','bot_health','admin_roles'):
            self.assertTrue(can_use_staff_tool(m,key),key)

    async def test_mod_can_manage_voice_without_system_configuration(self):
        m=member(moderate_members=True,manage_messages=True,move_members=True)
        self.assertTrue(is_moderator(m))
        self.assertTrue(user_can_admin_teardown(m))
        self.assertTrue(can_use_staff_tool(m,'admin_vc_teardown'))
        self.assertFalse(can_use_reload(m))
        self.assertFalse(can_use_staff_tool(m,'admin_update_publisher'))
        # A role called Mod alone must never confer authority.
        m.guild_permissions=discord.Permissions.none()
        m.roles=[types.SimpleNamespace(id=998,name='Mod')]
        self.assertFalse(is_moderator(m))

    async def test_direct_button_action_cannot_bypass_hidden_menu(self):
        i=types.SimpleNamespace(user=member(helper=True),client=MagicMock())
        with patch.object(admin_actions,'send_or_followup',new=AsyncMock()) as send:
            await admin_actions.admin_reload_from_button(i)
            await admin_actions.admin_update_publisher_from_button(i)
            await admin_actions.admin_game_tools_from_button(object(),i)
            await admin_actions.admin_vc_teardown_from_button(i)
            self.assertEqual(send.await_count,4)
        i.client.get_cog.assert_not_called()

    async def test_menu_filters_buttons_and_rechecks_revoked_authority(self):
        m=member(helper=True)
        view=AdminToolView(object(),member=m)
        ids={b.item.id for b in view.children}
        self.assertIn('admin_stats',ids)
        self.assertNotIn('admin_reload',ids)
        # Persistent/old views still contain routes; dispatch must deny them now.
        old=AdminToolView(object())
        item=next(b.item for b in old.children if b.item.id=='admin_reload')
        i=types.SimpleNamespace(user=m,client=MagicMock())
        old._enforce_cooldown=AsyncMock(return_value=True)
        with patch('features.menu_views.send_or_followup',new=AsyncMock()) as send:
            await old.handle_item(i,item)
            send.assert_awaited_once()
        i.client.get_cog.assert_not_called()
        view.stop();old.stop()

    async def test_notification_resolution_rechecks_current_member(self):
        stale=member(administrator=True)
        current=member(helper=True)
        guild=types.SimpleNamespace(get_member=lambda uid:current)
        i=types.SimpleNamespace(user=stale,guild=guild,guild_id=1)
        with patch('config.GUILD_ID',1):
            self.assertFalse(await permitted(i,stale.id))
            current.guild_permissions=discord.Permissions(manage_guild=True)
            self.assertTrue(await permitted(i,stale.id))
        self.assertFalse(is_server_admin(MagicMock(spec=discord.User)))

    async def test_admin_retains_existing_tools(self):
        for p in ('administrator','manage_guild'):
            m=member(**{p:True})
            for key in ('admin_reload','admin_game_tools','admin_update_publisher','admin_roles','admin_vc_teardown'):
                self.assertTrue(can_use_staff_tool(m,key))
