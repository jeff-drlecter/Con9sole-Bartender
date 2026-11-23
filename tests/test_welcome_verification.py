"""Synthetic REST payloads exercise discord.py's actual member/role resolution."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import AsyncMock, patch

import discord

import config
from cogs.member_entry import MemberEntry, MemberEntryView
from cogs.welcome_log import WelcomeLog, welcome_message
from features import welcome_verification as v


GUILD = config.GUILD_ID
WELCOME = config.WELCOME_CHANNEL_ID
VERIFIED = config.VERIFIED_ROLE_ID
HELPER = config.HELPER_ROLE_IDS[0]
BOT, NEW, STAFF, GREETED, OTHER = 11, 22, 33, 44, 55
BOT_ROLE, GAME, HIGH = 1001, 1002, 1003
JOINED = datetime.now(timezone.utc) - timedelta(minutes=5)


def role(rid, name, position, **permissions):
    return dict(id=str(rid), name=name, position=position,
                permissions=str(discord.Permissions(**permissions).value))


def member(uid, roles=(), *, bot=False):
    return dict(user=dict(id=str(uid), username='test', discriminator='0', avatar=None, bot=bot),
                roles=list(map(str, roles)), pending=False, flags=0, joined_at=JOINED.isoformat())


class VerifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch(v, 'STATS_DB', Path(tmp.name) / 'members.sqlite3')
        self.client = discord.Client(intents=discord.Intents.none())
        self.state = self.client._connection
        self.members = {BOT: member(BOT, [BOT_ROLE], bot=True), NEW: member(NEW, [GAME]),
                        STAFF: member(STAFF, [HELPER]), GREETED: member(GREETED), OTHER: member(OTHER)}
        self.roles = [role(GUILD, '@everyone', 0, view_channel=True, read_message_history=True),
                      role(VERIFIED, '會員', 5, bypass_slowmode=True, send_tts_messages=True), role(HELPER, 'helpers', 3),
                      role(GAME, 'Game', 1), role(HIGH, 'Rank', 6),
                      role(BOT_ROLE, 'Bot', 10, manage_roles=True)]
        self.guild_data = dict(id=str(GUILD), owner_id='99', name='Guild', roles=self.roles,
                               features=['MEMBER_VERIFICATION_GATE_ENABLED'])
        self.source_data = dict(id=str(WELCOME), guild_id=str(GUILD), type=0, name='welcome',
                                position=0, permission_overwrites=[])
        self.get_guild = AsyncMock(side_effect=lambda *a, **kw: discord.Guild(state=self.state, data=self.guild_data))
        self.patch(self.state.http, 'get_channel', AsyncMock(side_effect=lambda *_: deepcopy(self.source_data)))
        self.patch(self.state.http, 'get_member', AsyncMock(side_effect=lambda gid, uid: deepcopy(self.members[uid])))
        self.channel_list = AsyncMock(side_effect=lambda *_: [deepcopy(self.source_data)])
        self.patch(self.state.http, 'get_all_guild_channels', self.channel_list)
        self.add = AsyncMock(side_effect=lambda gid, uid, rid, **kw: self.members[uid]['roles'].append(str(rid)))
        self.remove = AsyncMock(side_effect=lambda gid, uid, rid, **kw: self.members[uid]['roles'].remove(str(rid)))
        self.patch(self.state.http, 'add_role', self.add)
        self.patch(self.state.http, 'remove_role', self.remove)
        self.old_button = discord.Button(dict(type=2, style=3, label='我是活人', custom_id='entry:verify:v1'))
        self.message = N(id=1234, author=N(id=BOT), webhook_id=None, created_at=JOINED - timedelta(days=1),
                         content=f'🎉 歡迎 <@{GREETED}> 加入 **Guild**！',
                         components=[N(children=[self.old_button])])
        self.patch(discord.TextChannel, 'fetch_message', AsyncMock(return_value=self.message))
        self.bot = N(user=N(id=BOT, mention=f'<@{BOT}>'), fetch_guild=self.get_guild)
        self.cog = MemberEntry(self.bot)
        self.bot.get_cog = lambda _: self.cog

    def patch(self, obj, name, value):
        mock = patch.object(obj, name, value)
        self.addCleanup(mock.stop)
        return mock.start()

    def click(self, uid=NEW):
        return N(guild_id=GUILD, guild=N(id=GUILD), channel_id=WELCOME, message=N(id=self.message.id),
                 user=N(id=uid, bot=False), client=self.bot, response=N(defer=AsyncMock()),
                 edit_original_response=AsyncMock())

    async def verify(self, interaction=None):
        i = interaction or self.click()
        view = MemberEntryView(welcome=True)
        await view.children[-1].callback(i)
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        response = i.edit_original_response.await_args.kwargs
        self.assertEqual(response['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        return response['content']

    async def revoke(self, actor=STAFF):
        i = self.click(actor)
        await self.cog.revoke_verification.callback(self.cog, i, N(id=NEW))
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        return i.edit_original_response.await_args.kwargs['content']

    async def test_welcome_only_and_copy_before_press(self):
        view = MemberEntryView(welcome=True)
        self.assertEqual([item.label for item in view.children],
                         ['選擇遊戲', '開主選單', '搵 Helper', '我是人類'])
        self.assertEqual(view.children[-1].custom_id, self.old_button.custom_id)
        self.assertTrue(view.is_persistent())
        self.assertNotIn(v.VERIFY_BUTTON, [item.custom_id for item in MemberEntryView().children])
        copy = welcome_message(N(mention='<@22>', guild=N(name='x')), '<#7>', '')
        for word in ('<#7>', '打招呼', '搵隊友', '我是人類', '任何人嘅歡迎訊息', '解鎖完整會員功能', '搵 Helper'):
            self.assertIn(word, copy)
        guild = await self.get_guild(GUILD)
        ch = await guild.fetch_channel(WELCOME)
        self.patch(discord.Guild, 'get_channel', lambda _, rid: ch if rid == WELCOME else None)
        send = self.patch(discord.TextChannel, 'send', AsyncMock())
        joined = await guild.fetch_member(NEW)
        joined.pending = True
        await WelcomeLog(self.bot).on_member_join(joined)
        self.assertIn(v.VERIFY_BUTTON, [b.custom_id for b in send.await_args.kwargs['view'].children])
        self.assertEqual(send.await_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        joined.pending = False
        await WelcomeLog(self.bot).on_member_join(joined)
        self.assertIn(v.VERIFY_BUTTON, [b.custom_id for b in send.await_args.kwargs['view'].children])

    async def test_shared_game_chooser_links_only_the_current_opted_in_reader(self):
        forum_id, opt_in = 1279353169671098408, 1574308758182699109
        forum = dict(self.source_data, id=str(forum_id), type=15, name='遊戲開發與試玩', nsfw=True)
        self.roles.append(role(opt_in, '試玩遊戲', 1))
        self.members[NEW]['roles'].append(str(opt_in))
        self.guild_data['channels'] = [self.source_data, forum]
        guild = await self.get_guild(GUILD)
        self.patch(self.state.http, 'get_roles', AsyncMock(side_effect=lambda _: deepcopy(self.roles)))
        fetch_channel = self.patch(self.state.http, 'get_channel', AsyncMock(
            side_effect=lambda cid: deepcopy(self.source_data if cid == WELCOME else forum)))
        welcome = guild.get_channel(WELCOME)
        send = self.patch(discord.TextChannel, 'send', AsyncMock())
        await WelcomeLog(self.bot).on_member_join(await guild.fetch_member(NEW))
        shared_view = send.await_args.kwargs['view']
        self.assertFalse(any(button.url for button in shared_view.children))
        self.assertEqual([b.custom_id for b in shared_view.children],
                         ['entry:games:v2', 'entry:menu:v2', 'entry:help:v2', v.VERIFY_BUTTON])
        chooser = shared_view.children[0]

        async def click_chooser(clicker):
            i = self.click()
            i.guild, i.channel, i.user = guild, welcome, clicker
            i.response.is_done = lambda: False
            i.followup = N(send=AsyncMock())
            await chooser.callback(i)
            result = i.followup.send.await_args.kwargs
            self.assertTrue(result['ephemeral'])
            self.assertIn('<id:customize>', result['content'])
            return [b for b in result['view'].children if b.url]

        opted_in = await guild.fetch_member(NEW)
        other = await guild.fetch_member(OTHER)
        self.assertEqual(await click_chooser(other), [])
        links = await click_chooser(opted_in)
        self.assertEqual([(str(b.emoji), b.label, b.url) for b in links], [
            ('🧪', '遊戲開發與試玩（18+）', f'https://discord.com/channels/{GUILD}/{forum_id}')])
        self.members[NEW]['roles'].remove(str(opt_in))
        fetch_channel.reset_mock()
        self.assertEqual(await click_chooser(opted_in), [])  # stale interaction still holds the role
        self.assertEqual([call.args[0] for call in fetch_channel.await_args_list], [WELCOME])
        self.members[NEW]['roles'].append(str(opt_in))
        for permission in ('view_channel', 'read_message_history'):
            forum['permission_overwrites'] = [dict(id=str(NEW), type=1, allow='0',
                                                   deny=str(discord.Permissions(**{permission: True}).value))]
            self.assertEqual(await click_chooser(opted_in), [])
        forum['permission_overwrites'] = []
        forum['nsfw'] = False
        self.assertEqual(await click_chooser(opted_in), [])
        forum['nsfw'] = True
        forum['type'] = 0
        self.assertEqual(await click_chooser(opted_in), [])
        self.add.assert_not_awaited()
        self.remove.assert_not_awaited()

    async def test_multiple_members_can_verify_themselves_on_someone_elses_older_card(self):
        for uid in (NEW, OTHER):
            self.assertIn('已完成', await self.verify(self.click(uid)))
            self.assertEqual(self.add.await_args.args, (GUILD, uid, VERIFIED))
        self.assertEqual(self.add.await_count, 2)
        self.assertEqual(self.members[GREETED]['roles'], [])

    async def test_concurrent_click_restart_removal_and_staff_recovery(self):
        outcomes = await asyncio.gather(self.verify(), self.verify())
        self.assertTrue(any('已完成' in outcome for outcome in outcomes))
        self.add.assert_awaited_once()
        self.assertEqual(self.add.await_args.args, (GUILD, NEW, VERIFIED))
        self.assertEqual(self.members[NEW]['roles'], [str(GAME), str(VERIFIED)])
        self.members[NEW]['roles'].remove(str(VERIFIED))  # Native removal while bot offline
        self.cog = MemberEntry(self.bot)
        self.assertEqual(await self.verify(), v.REVIEW)
        self.members[NEW]['roles'].append(str(VERIFIED))  # Native staff restoration
        self.assertIn('已經有', await self.verify())
        self.assertEqual(self.add.await_count, 1)

    async def test_helper_with_lower_role_can_only_revoke_verified(self):
        self.members[NEW]['roles'].append(str(VERIFIED))
        self.assertIn('已撤回', await self.revoke())
        self.assertEqual(self.remove.await_args.args, (GUILD, NEW, VERIFIED))
        self.assertEqual(self.members[NEW]['roles'], [str(GAME)])
        self.assertEqual(await self.verify(), v.REVIEW)

    async def test_unauthorized_helper_and_protected_targets(self):
        self.members[NEW]['roles'].append(str(VERIFIED))
        self.members[STAFF]['roles'] = [str(GAME)]
        self.roles[3]['name'] = 'Helpers'  # A name match cannot authorize a Helper.
        self.assertIn('只限', await self.revoke())
        self.roles[3]['name'] = 'Game'
        self.members[STAFF]['roles'] = [str(HELPER)]
        for protected in (HELPER, HIGH):
            self.members[NEW]['roles'].append(str(protected))
            self.assertIn('唔適用', await self.revoke())
            self.members[NEW]['roles'].remove(str(protected))
        self.guild_data['owner_id'] = str(NEW)
        self.assertIn('唔適用', await self.revoke())
        self.remove.assert_not_awaited()

    async def test_rules_must_be_enabled_and_explicitly_passed(self):
        for features in ([], ['COMMUNITY'], None):
            if features is None:
                del self.guild_data['features']
            else:
                self.guild_data['features'] = features
            self.assertIn('入群守則確認', await self.verify())
        self.guild_data['features'] = ['MEMBER_VERIFICATION_GATE_ENABLED']
        for field, value in (('pending', True), ('pending', None), ('pending', 0), ('flags', 4), ('flags', None)):
            original = self.members[NEW].pop(field)
            if value is not None:
                self.members[NEW][field] = value
            self.assertEqual(await self.verify(), v.RULES)
            self.members[NEW][field] = original
        self.add.assert_not_awaited()

    async def test_wrong_source_webhook_and_hidden_channel_are_private_noops(self):
        i = self.click()
        i.channel_id += 1
        await self.verify(i)
        i = self.click()
        i.guild_id += 1
        await self.verify(i)
        self.get_guild.assert_not_awaited()
        for attr, invalid in [('author', N(id=123)), ('webhook_id', BOT), ('components', []),
                              ('components', [N(children=[N(custom_id=v.VERIFY_BUTTON)])]),
                              ('content', '🎉 歡迎大家！')]:
            with patch.object(self.message, attr, invalid):
                self.assertEqual(await self.verify(), v.WELCOME_ONLY)
        with patch.object(self.old_button, 'disabled', True):
            self.assertEqual(await self.verify(), v.WELCOME_ONLY)
        self.source_data['permission_overwrites'] = [
            dict(id=str(NEW), type=1, deny=str(discord.Permissions(view_channel=True).value), allow='0')]
        self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.add.assert_not_awaited()

    async def test_privilege_drift_channel_overwrite_managed_role_and_wrong_id(self):
        for field, value in (('permissions', str(discord.Permissions(manage_webhooks=True).value)),
                             ('permissions', str(1 << 60)), ('managed', True), ('name', 'Helpers'),
                             ('position', 11)):
            with patch.dict(self.roles[1], {field: value}):
                self.assertEqual(await self.verify(), v.UNAVAILABLE)
        with patch.object(config, 'VERIFIED_ROLE_ID', GAME):
            self.assertEqual(await self.verify(), v.UNAVAILABLE)
        unsafe = deepcopy(self.source_data)
        unsafe.update(id='7', type=20, permission_overwrites=[dict(id=str(VERIFIED), type=0, deny='0',
                      allow=str(discord.Permissions(manage_messages=True).value))])
        self.channel_list.side_effect = lambda *_: [self.source_data, unsafe]
        self.assertEqual(await self.verify(), v.UNAVAILABLE)
        unsafe['permission_overwrites'][0]['allow'] = str(1 << 60)
        self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.add.assert_not_awaited()

    async def test_unrecognized_channel_type_does_not_block_safe_role(self):
        directory = dict(id='10111', type=20, permission_overwrites=[])
        self.channel_list.side_effect = lambda *_: [self.source_data, directory]
        self.assertIn('已完成', await self.verify())
        self.add.assert_awaited_once()

    async def test_missing_clicker_join_time_blocks_grant_until_member_data_is_complete(self):
        joined_at = self.members[NEW].pop('joined_at')
        self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.add.assert_not_awaited()
        self.members[NEW]['joined_at'] = joined_at
        self.assertIn('已完成', await self.verify())

    async def test_bot_hierarchy_unknown_member_roles_and_timeout(self):
        with patch.dict(self.roles[-1], permissions='0'):
            self.assertEqual(await self.verify(), v.UNAVAILABLE)
        for rid in (BOT_ROLE, 988):
            with patch.dict(self.members[NEW], roles=[str(rid)]):
                self.assertEqual(await self.verify(), v.UNAVAILABLE)
        until = datetime.now(timezone.utc) + timedelta(days=1)
        with patch.dict(self.members[NEW], communication_disabled_until=until.isoformat()):
            self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.add.assert_not_awaited()

    async def test_ambiguous_grant_and_store_failure_fail_closed(self):
        with patch.object(v, 'remember', side_effect=sqlite3.OperationalError('locked')):
            self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.add.assert_not_awaited()
        self.add.side_effect = OSError('response lost')
        self.assertEqual(await self.verify(), v.UNAVAILABLE)
        self.assertEqual(await self.verify(), v.REVIEW)
        self.add.assert_awaited_once()

    async def test_remember_observed_manual_role_change(self):
        guild = await self.get_guild(GUILD)
        before = await guild.fetch_member(NEW)
        self.members[NEW]['roles'].append(str(VERIFIED))
        after = await guild.fetch_member(NEW)
        await self.cog.on_member_update(before, after)
        self.members[NEW]['roles'].remove(str(VERIFIED))
        self.assertEqual(await self.verify(), v.REVIEW)
        self.add.assert_not_awaited()

    async def test_audit_event_remembers_removal_without_cached_member(self):
        event = N(guild=N(id=GUILD), action=discord.AuditLogAction.member_role_update,
                  before=N(roles=[N(id=VERIFIED)]), after=N(), target=N(id=NEW))
        await self.cog.on_audit_log_entry_create(event)
        self.assertEqual(await self.verify(), v.REVIEW)
        self.add.assert_not_awaited()
