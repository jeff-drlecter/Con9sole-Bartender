import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import config
from core.news_channel_inventory import convert_inventory, fetch_news_channels
from core.news_channel_ui import safe_roles
from features.news_channel_categories import CHANNELS


class InventoryTests(unittest.IsolatedAsyncioTestCase):
    def guild(self):
        return SimpleNamespace(id=config.GUILD_ID, _state=SimpleNamespace(
            http=SimpleNamespace(get_all_guild_channels=AsyncMock())),
            get_role=lambda rid: None, get_member=lambda rid: None,
            get_channel=lambda cid: None)

    async def test_unknown_channel_keeps_role_and_member_overwrites(self):
        guild = self.guild()
        guild._state.http.get_all_guild_channels.return_value = [
            dict(id='888', type=20, permission_overwrites=[
                dict(id='11', type=0, allow='1024', deny='0'),
                dict(id='12', type=1, allow='0', deny='1024')])]
        result = await fetch_news_channels(guild)
        self.assertEqual(result[0].id, 888)
        entries = {(t.id, t.type): ow for t, ow in result[0].overwrites.items()}
        self.assertTrue(entries[11, discord.Role].view_channel)
        self.assertFalse(entries[12, discord.Member].view_channel)
        guild._state.http.get_all_guild_channels.assert_awaited_once_with(config.GUILD_ID)

    def test_real_announcement_channel_constructs_with_unknown_neighbor(self):
        guild = self.guild()
        row = dict(id=str(CHANNELS['ps']), type=5, name='ps-news', position=1,
                   parent_id=None, permission_overwrites=[], topic=None, nsfw=False,
                   rate_limit_per_user=0, last_message_id=None)
        result = convert_inventory(guild, [dict(id='888', type=20), row])
        self.assertIsInstance(result[1], discord.TextChannel)
        self.assertEqual(result[1].type, discord.ChannelType.news)
        self.assertEqual(result[1].id, CHANNELS['ps'])

    def test_unknown_news_channel_and_unknown_overwrite_target_refused(self):
        with self.assertRaises(ValueError):
            convert_inventory(self.guild(), [dict(id=str(CHANNELS['ps']), type=20)])
        with self.assertRaises(ValueError):
            convert_inventory(self.guild(), [dict(id='888', type=20,
                permission_overwrites=[dict(id='11', type=7, allow='0', deny='0')])])

    async def test_news_role_grant_on_unknown_type_blocks_member_selector(self):
        from unittest.mock import patch, Mock
        from features.news_channel_categories import ROLE_NAMES
        roles = []
        ids = {}
        for key, rid in zip(CHANNELS, (11, 12, 13)):
            r = Mock(spec=discord.Role)
            r.id, r.name, r.managed, r.permissions = rid, ROLE_NAMES[key], False, discord.Permissions.none()
            ids[key] = rid; roles.append(r)
        guild = self.guild(); guild.fetch_roles = AsyncMock(return_value=roles)
        guild._state.http.get_all_guild_channels.return_value = [dict(id='888', type=20,
            permission_overwrites=[dict(id='11', type=0, allow='1024', deny='0')])]
        with patch('core.news_channel_ui.settings', return_value=ids):
            with self.assertRaisesRegex(ValueError, '涉及其他區域'):
                await safe_roles(guild)


if __name__ == '__main__': unittest.main()
