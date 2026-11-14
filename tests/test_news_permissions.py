import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import config
from features import news_permissions as policy, anti_scam_fix as journal
from features.news_channel_categories import CHANNELS, ROLE_NAMES


def role(rid, name, **perms):
    r = Mock(spec=discord.Role)
    r.id, r.name, r.managed = rid, name, False
    r.permissions = discord.Permissions(**perms)
    return r


class NewsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ids = dict(zip(CHANNELS, (11, 12, 13)))
        self.roles = [role(config.GUILD_ID, '@everyone'),
                      role(config.HELPER_ROLE_IDS[0], 'Helpers'),
                      role(config.MOD_ROLE_ID, 'Mod'),
                      role(config.VERIFIED_ROLE_ID, 'Verified'),
                      role(20, 'news-sub'), role(21, 'no-news-sub')]
        self.roles += [role(self.ids[k], ROLE_NAMES[k]) for k in CHANNELS]
        self.by_id = {r.id:r for r in self.roles}
        self.channels = []
        for key, cid in CHANNELS.items():
            c = Mock(spec=discord.TextChannel)
            c.id, c.name, c.category_id = cid, key, 500
            c.type, c.permissions_synced = discord.ChannelType.text, False
            c.overwrites = {
                self.by_id[config.GUILD_ID]: discord.PermissionOverwrite(view_channel=False),
                self.by_id[self.ids[key]]: discord.PermissionOverwrite(view_channel=True),
                self.by_id[config.MOD_ROLE_ID]: discord.PermissionOverwrite(view_channel=True),
                self.by_id[config.HELPER_ROLE_IDS[0]]: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            }
            c.overwrites_for.side_effect = lambda r, ch=c: copy.deepcopy(ch.overwrites.get(r, discord.PermissionOverwrite()))
            async def write(r, overwrite, reason, ch=c):
                if overwrite is None: ch.overwrites.pop(r, None)
                else: ch.overwrites[r] = copy.deepcopy(overwrite)
            c.set_permissions = AsyncMock(side_effect=write)
            self.channels.append(c)
        self.guild = SimpleNamespace(id=config.GUILD_ID,
            fetch_roles=AsyncMock(side_effect=lambda:self.roles),
            fetch_channels=AsyncMock(side_effect=lambda:self.channels),
            fetch_channel=AsyncMock(side_effect=lambda cid: next(c for c in self.channels if c.id==cid)))
        self.tmp = tempfile.TemporaryDirectory()
        self.dbpatch = patch.object(journal, 'PATH', Path(self.tmp.name)/'plans.sqlite3')
        self.dbpatch.start()
        self.settingspatch = patch('core.news_channel_ui.settings', return_value=self.ids)
        self.settingspatch.start()

    def tearDown(self):
        self.settingspatch.stop(); self.dbpatch.stop(); self.tmp.cleanup()

    def build(self):
        return policy.build(self.roles, self.channels, config.GUILD_ID, 42, self.ids)

    async def test_apply_preserves_other_bits_and_restore(self):
        plan = self.build()
        for c in self.channels:
            self.assertIs(c.overwrites_for(self.by_id[config.HELPER_ROLE_IDS[0]]).view_channel, True)
        self.assertEqual(len(plan['ops']), 3)
        self.assertFalse(plan['blockers'])
        journal.save(plan)
        await policy.execute(self.guild, plan, AsyncMock(return_value=True))
        self.assertEqual({o['state'] for o in plan['ops']}, {'verified'})
        self.assertFalse(self.build()['ops'])
        for c in self.channels:
            ow = c.overwrites_for(self.by_id[config.HELPER_ROLE_IDS[0]])
            self.assertIsNone(ow.view_channel)
            self.assertIs(ow.send_messages, False)
            self.assertIs(c.overwrites_for(self.by_id[config.MOD_ROLE_ID]).view_channel, True)
        await policy.execute(self.guild, plan, AsyncMock(return_value=True), restore=True)
        self.assertEqual({o['state'] for o in plan['ops']}, {'restored'})

    async def test_changed_snapshot_stops_all_writes(self):
        plan = self.build()
        self.channels[0].overwrites[self.by_id[config.GUILD_ID]].send_messages = False
        with self.assertRaisesRegex(ValueError, '設定已改變'):
            await policy.execute(self.guild, plan, AsyncMock(return_value=True))
        for c in self.channels: c.set_permissions.assert_not_awaited()

    async def test_revoked_admin_stops_all_writes(self):
        with self.assertRaises(ValueError):
            await policy.execute(self.guild, self.build(), AsyncMock(return_value=False))
        for c in self.channels: c.set_permissions.assert_not_awaited()

    async def test_ambiguous_write_receipt_blocks_replay_and_restores(self):
        plan = self.build(); journal.save(plan)
        c = self.channels[0]
        original = c.set_permissions.side_effect
        async def fail_after_write(*args, **kwargs):
            await original(*args, **kwargs)
            raise OSError('connection lost')
        c.set_permissions.side_effect = fail_after_write
        with self.assertRaises(OSError):
            await policy.execute(self.guild, plan, AsyncMock(return_value=True))
        saved = journal.load(plan['id'], config.GUILD_ID, 42)
        self.assertEqual(saved['ops'][0]['state'], 'uncertain')
        with self.assertRaises(ValueError):
            await policy.execute(self.guild, saved, AsyncMock(return_value=True))
        c.set_permissions.side_effect = original
        await policy.execute(self.guild, saved, AsyncMock(return_value=True), restore=True)
        self.assertIs(c.overwrites_for(self.by_id[config.HELPER_ROLE_IDS[0]]).view_channel, True)

    async def test_restore_conflict_does_not_overwrite_manual_change(self):
        plan = self.build()
        await policy.execute(self.guild, plan, AsyncMock(return_value=True))
        c = self.channels[-1]
        c.overwrites[self.by_id[config.HELPER_ROLE_IDS[0]]].view_channel = False
        c.set_permissions.reset_mock()
        await policy.execute(self.guild, plan, AsyncMock(return_value=True), restore=True)
        c.set_permissions.assert_not_awaited()
        self.assertEqual(plan['ops'][-1]['state'], 'conflict')

    def test_member_and_unknown_role_grants_block(self):
        target = SimpleNamespace(id=999, name='unknown')
        member = Mock(spec=discord.Member); member.id, member.name = 999, 'member'
        self.channels[0].overwrites[member] = discord.PermissionOverwrite(view_channel=True)
        self.assertTrue(self.build()['blockers'])
        self.channels[0].overwrites.pop(member)
        r = role(999, 'game'); self.roles.append(r)
        self.channels[0].overwrites[r] = discord.PermissionOverwrite(view_channel=True)
        self.assertTrue(self.build()['blockers'])

    def test_missing_channel_synced_channel_bad_role_refused(self):
        original = self.channels.pop()
        with self.assertRaises(ValueError): self.build()
        self.channels.append(original); original.permissions_synced = True
        with self.assertRaises(ValueError): self.build()
        original.permissions_synced = False
        self.by_id[11].permissions.manage_roles = True
        with self.assertRaises(ValueError): self.build()

    def test_legacy_allow_removed_denial_and_official_untouched(self):
        legacy = self.by_id[20]
        self.channels[0].overwrites[legacy] = discord.PermissionOverwrite(view_channel=True, embed_links=True)
        self.channels[1].overwrites[legacy] = discord.PermissionOverwrite(view_channel=False)
        official = Mock(spec=discord.TextChannel)
        official.id = 1426666904692457624
        official.overwrites = {legacy: discord.PermissionOverwrite(view_channel=True)}
        self.channels.append(official)
        plan = self.build()
        self.assertEqual(len(plan['ops']), 4)
        self.assertNotIn(official.id, {o['channel'] for o in plan['ops']})
        change = next(o for o in plan['ops'] if o['target']==20)
        self.assertEqual((change['before'][0] ^ change['after'][0]), policy.VIEW)

    def test_news_role_used_elsewhere_blocks(self):
        other = Mock(spec=discord.TextChannel); other.id = 888
        other.overwrites = {self.by_id[11]: discord.PermissionOverwrite(view_channel=True)}
        self.channels.append(other)
        self.assertTrue(self.build()['blockers'])

    async def test_panel_ownership_and_ephemeral(self):
        from cogs.news_permissions import NewsPermissionPanel
        panel = NewsPermissionPanel(None, 42, self.build())
        inter = SimpleNamespace(user=SimpleNamespace(id=43), guild_id=config.GUILD_ID,
                                response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await panel.interaction_check(inter))
        self.assertTrue(inter.response.send_message.call_args.kwargs['ephemeral'])


if __name__ == '__main__': unittest.main()
