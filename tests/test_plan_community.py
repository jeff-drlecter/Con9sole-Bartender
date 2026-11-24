"""Exercise both draft paths, the persisted plan and the room naming handoff offline."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from cogs.squad_plans import ManageView, PlanView, prepare_plan_voice
from features.community_directory import Directory
from features.plan_browse_ui import InstantDraft
from features.plan_community import sync_community_rooms
from features.plan_delivery_ui import Draft
from features.squad_plans import PlanBook


class PlanCommunityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.now = int(time.time()) // 60 * 60
        self.book = PlanBook(folder / 'plans.json', clock=lambda: self.now)
        self.member = N(id=42, display_name='Host', bot=False, roles=[])
        self.guild = N(id=config.GUILD_ID, me=N(id=9), fetch_member=AsyncMock(return_value=self.member))
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.name, self.channel.guild = 200, 'fc-吹水組隊', self.guild
        self.channel.category_id, self.channel.category = 40, N(name='EA SPORTS FC')
        self.channel.send = AsyncMock(return_value=N(id=222))
        self.room = MagicMock(spec=discord.VoiceChannel)
        self.room.id, self.room.guild = 300, self.guild
        self.temp = N(room_for_plan=AsyncMock(return_value=self.room), set_community_name=AsyncMock(return_value=True))
        self.directory = Directory(folder / 'directory.json', config.GUILD_ID)
        self.team = self.directory.save('team-a', create=True, name='A 隊', game='FC',
                                        pic_id=98765, notes='PIC note', status='open')
        self.modules = {'TempVC': self.temp, 'SquadCards': N(state={'settings': {'routes': {'40': 200}}}),
                        'CommunityDirectory': N(directory=self.directory)}
        bot = N(get_cog=self.modules.get, get_channel=lambda ident: {300: self.room, 200: self.channel}.get(ident))
        self.cog = N(book=self.book, bot=bot, lock=asyncio.Lock(), refresh=AsyncMock(return_value=True))
        self.data = dict(game='FC', mode='Clubs', party=1, start=self.now + 3600, capacity=3)
        self.enterContext(patch('cogs.squad_plans.allowed', return_value=True))
        self.enterContext(patch('features.plan_services.fresh_source', new=AsyncMock(return_value=(self.member, self.channel))))
        self.enterContext(patch('features.plan_browse_ui.fresh_source', new=AsyncMock(return_value=(self.member, self.channel))))
        self.enterContext(patch('features.plan_community.fresh_source', new=AsyncMock(return_value=(self.member, self.channel))))
        self.enterContext(patch('features.member_activity.complete_task', new=AsyncMock()))

    def click(self, uid=42):
        return N(user=self.member if uid == 42 else N(id=uid), guild=self.guild, guild_id=self.guild.id,
                 channel=self.channel, channel_id=self.channel.id, edit_original_response=AsyncMock(),
                 response=N(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False),
                 followup=N(send=AsyncMock()))

    def create(self, key='team-a'):
        plan = self.book.create(owner=42, guild=self.guild.id, channel=200, community_key=key, **self.data)
        self.book.publish(plan['id'], 222)
        return self.book.get(plan['id'])

    async def test_select_and_publish_on_both_drafts(self):
        for draft in (InstantDraft(self.cog, self.channel, 42, dict(game='FC', mode='Clubs', party=1, missing=2), self.member),
                      Draft(self.cog, self.channel, self.member, self.data)):
            with self.subTest(type=type(draft).__name__):
                async def choose(interaction, bot, selected, *, current_key):
                    self.assertIsNone(current_key)
                    await selected(self.click(), 'team-a')

                with patch('features.plan_community.choose_community', side_effect=choose):
                    button = next(b for b in draft.children if b.label == '選擇公會（選填）')
                    await button.callback(self.click())
                self.assertIn('A 隊', draft.summary())
                await draft.publish.callback(self.click())
                posted = self.channel.send.await_args.kwargs
                self.assertIn('A 隊', str(posted['embed'].to_dict()))
                self.assertNotIn('98765', str(posted['embed'].to_dict()))
                self.assertNotIn('PIC note', str(posted['embed'].to_dict()))
                self.assertTrue(any(b.label == '查看公會' for b in posted['view'].children))
                self.assertEqual(posted['allowed_mentions'].to_dict(), {'parse': []})
                self.channel.send.reset_mock()
        reopened = PlanBook(self.book.path).all()
        self.assertEqual([p['community_key'] for p in reopened], ['team-a', 'team-a'])
        self.assertEqual({p['instant'] for p in reopened}, {False, True})

    async def test_open_room_apply_once_and_recover_after_reboot(self):
        p = self.create()
        self.temp.set_community_name.return_value = False
        result = await prepare_plan_voice(self.cog, self.click(), p)
        self.assertIn('加入語音', result)
        self.assertIn('待同步', result)
        self.cog.book = PlanBook(self.book.path, clock=lambda: self.now)
        self.temp.set_community_name.return_value = True
        self.assertTrue(await sync_community_rooms(self.cog, self.cog.book.get(p['id'])))
        await prepare_plan_voice(self.cog, self.click(), self.cog.book.get(p['id']))
        self.temp.room_for_plan.assert_awaited_once()
        self.assertEqual(self.temp.set_community_name.await_count, 2)
        self.temp.set_community_name.assert_awaited_with(self.room, 'A 隊', owner_id=42, source=f"plan:{p['id']}")
        self.assertNotIn('community_rooms_pending', self.cog.book.get(p['id']))

    async def test_archived_before_open_and_unselected_legacy(self):
        p = self.create(key=None)
        self.assertNotIn('community_key', p)
        self.assertNotIn('查看公會', [b.label for b in PlanView(self.cog, p).children])
        result = await prepare_plan_voice(self.cog, self.click(), p)
        self.assertIn('加入語音', result)
        self.temp.set_community_name.assert_not_awaited()
        self.book.act(p['id'], 42, 'cancel')
        tagged = self.create()
        self.directory.save('team-a', archived=True)
        await prepare_plan_voice(self.cog, self.click(), tagged)
        self.temp.set_community_name.assert_awaited_once_with(self.room, None, owner_id=42, source=f"plan:{tagged['id']}")

    async def test_remove_from_live_plan_preserves_rsvp_and_blocks_stale_picker(self):
        p = self.create()
        self.book.act(p['id'], 43, 'join')
        bound = self.book.link_voice(p['id'], 42, 300)
        self.book.sync_session(p['id'], 300, 'session1')
        with self.assertRaises(ValueError):
            self.book.set_community(p['id'], 43, None, expected=bound)
        with self.assertRaises(ValueError):
            self.book.set_community(p['id'], 42, None, expected=p)
        updated = self.book.set_community(p['id'], 42, None, expected=bound)
        self.assertEqual(updated['members'], [43])
        self.assertEqual(updated['status'], 'live')
        self.assertTrue(await sync_community_rooms(self.cog, updated))
        self.temp.set_community_name.assert_awaited_once_with(self.room, None, owner_id=42, source=f"plan:{p['id']}")

    async def test_non_owner_cannot_open_picker_from_management(self):
        p = self.create()
        with patch('features.plan_community.choose_community', new=AsyncMock()) as picker:
            click = self.click(43)
            await ManageView(self.cog, p['id'], False, True).community.callback(click)
        picker.assert_not_awaited()
        click.response.send_message.assert_awaited_once()

    async def test_change_game_releases_only_the_previous_binding(self):
        p = self.create()
        self.book.link_voice(p['id'], 42, 300)
        edited = self.book.act(p['id'], 42, 'edit', changes=dict(self.data, game='GTA'))
        self.assertNotIn('voice', edited)
        self.assertEqual(edited['community_key'], 'team-a')
        await sync_community_rooms(self.cog, edited)
        self.temp.set_community_name.assert_awaited_once_with(self.room, None, owner_id=42, source=f"plan:{p['id']}")
