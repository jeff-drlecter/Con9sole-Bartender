import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from quick_bar_fakes import interaction

import utils
from cogs.tempvc import TempVC
from core.action_guard import shared_async_lock
from features import tempvc_storage


class TempVCFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(
            tempvc_storage, "STATS_DB", Path(self.temp.name) / "vc.sqlite3"
        )
        self.patch.start()
        tempvc_storage.init_tempvc_db()
        utils.TEMP_VC_IDS.clear()
        self.bot = MagicMock()
        self.bot.wait_until_ready = AsyncMock()
        self.bot.guilds = []
        self.bot.is_closed.return_value = False
        self.cog = TempVC(self.bot)

    async def asyncTearDown(self):
        await self.cog.cog_unload()
        utils.TEMP_VC_IDS.clear()
        self.patch.stop()
        self.temp.cleanup()

    async def test_reload_restarts_sweeper_without_new_ready_event(self):
        await self.cog.cog_load()
        await asyncio.sleep(0)
        self.assertIsNotNone(self.cog._sweeper_task)
        old = self.cog._sweeper_task
        await self.cog.cog_unload()
        self.assertTrue(old.done())
        self.cog = TempVC(self.bot)
        await self.cog.cog_load()
        await asyncio.sleep(0)
        self.assertIsNotNone(self.cog._sweeper_task)
        self.assertIsNot(self.cog._sweeper_task, old)

    async def test_named_ordinary_room_is_never_adopted(self):
        guild = MagicMock()
        guild.id = 1
        room = MagicMock(name="小隊call • 1")
        room.id = 123
        guild.voice_channels = [room]
        self.assertEqual(
            await utils.bootstrap_track_temp_vcs(guild, name_prefixes=["小隊call •"]),
            [],
        )
        self.assertFalse(utils.is_temp_vc_id(123))

    async def test_recorded_room_restores_after_name_change(self):
        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        utils.TEMP_VC_IDS.clear()
        guild = MagicMock()
        guild.id = 1
        guild.voice_channels = []
        self.assertEqual(
            await utils.bootstrap_track_temp_vcs(guild, name_prefixes=[]), [123]
        )
        self.assertTrue(utils.is_temp_vc_id(123))
        self.assertEqual(tempvc_storage.owned_ids(1, 10), [123])

    async def test_delete_failure_retains_tracking_and_owner(self):
        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        room = MagicMock(spec=discord.VoiceChannel)
        room.id = 123
        room.name = "room"
        room.delete = AsyncMock(
            side_effect=discord.Forbidden(
                MagicMock(status=403, reason="Forbidden"), "missing permission"
            )
        )
        with self.assertRaises(discord.Forbidden):
            await self.cog._teardown_temp_vc(room)
        self.assertTrue(utils.is_temp_vc_id(123))
        self.assertEqual(tempvc_storage.owned_ids(1, 10), [123])

    async def test_successful_delete_removes_persistent_tracking(self):
        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.name, room.delete = 123, "room", AsyncMock()
        await self.cog._teardown_temp_vc(room)
        self.assertFalse(utils.is_temp_vc_id(123))
        self.assertFalse(tempvc_storage.owned_ids(1, 10))

    async def test_quick_entry_creates_with_defaults_without_modal(self):
        i = interaction()
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.guild, room.mention, room.name, room.user_limit = (
            123,
            i.guild,
            "<#123>",
            "room",
            32,
        )
        self.cog._create_manual_temp_vc = AsyncMock(return_value=room)
        with (
            patch("cogs.tempvc.user_can_run_tempvc", return_value=True),
            patch("cogs.tempvc.record_usage"),
        ):
            await self.cog.menu_entry(i)
        self.cog._create_manual_temp_vc.assert_awaited_once()
        self.assertEqual(self.cog._create_manual_temp_vc.await_args.kwargs["limit"], 32)
        i.response.send_modal.assert_not_awaited()
        view = i.edit_original_response.await_args.kwargs["view"]
        self.assertTrue(any(button.url for button in view.children))

    async def test_unknown_channel_type_does_not_orphan_created_room(self):
        guild = MagicMock()
        guild.id, guild.bitrate_limit = 1, 64000
        guild._state.http.get_all_guild_channels = AsyncMock(return_value=[
            {"id": "900", "type": 20, "parent_id": "20"},
            {"id": "776", "type": 2, "parent_id": "10", "position": 0,
             "name": "開一個小隊 call", "bitrate": 64000, "user_limit": 0},
            {"id": "777", "type": 2, "parent_id": "10", "position": 1,
             "name": "小隊call • 1", "bitrate": 64000, "user_limit": 0},
        ])
        guild._state.http.bulk_channel_update = AsyncMock()
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.guild, room.name = 777, guild, "小隊call • 1"
        guild.create_voice_channel = AsyncMock(return_value=room)
        with patch("cogs.tempvc.schedule_delete_if_empty", new_callable=AsyncMock) as cleanup, \
             patch("cogs.tempvc.get_hub_channel_name", return_value="開一個小隊 call"):
            result = await self.cog._create_manual_temp_vc(guild, MagicMock(id=10), name="測試", creator_id=10)
        self.assertIs(result, room)
        self.assertEqual(tempvc_storage.creator_id(777), 10)
        cleanup.assert_awaited_once_with(room, force=False)
        room.delete.assert_not_called()
        guild._state.http.get_all_guild_channels.assert_awaited_once_with(1)
        guild._state.http.bulk_channel_update.assert_awaited_once_with(1, [
            {"id": 777, "position": 0}, {"id": 776, "position": 1},
        ], reason="Sort small-team calls above their creation hub")

    async def test_existing_owned_room_is_reused(self):
        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        i = interaction()
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.guild, room.mention = 123, i.guild, "<#123>"
        i.guild.get_channel.return_value = room
        self.cog._create_manual_temp_vc = AsyncMock()
        with patch("cogs.tempvc.user_can_run_tempvc", return_value=True):
            await self.cog._create_default_room(i)
        self.cog._create_manual_temp_vc.assert_not_awaited()
        self.assertIn(
            "你的小隊語音房", i.edit_original_response.await_args.kwargs["content"]
        )

    async def test_concurrent_create_requests_do_not_create_two_rooms(self):
        entered, release = asyncio.Event(), asyncio.Event()
        i, j = interaction(), interaction()
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.guild, room.mention, room.name, room.user_limit = (
            123,
            i.guild,
            "<#123>",
            "room",
            32,
        )

        async def create(*args, **kwargs):
            entered.set()
            await release.wait()
            return room

        self.cog._create_manual_temp_vc = AsyncMock(side_effect=create)
        with (
            patch("cogs.tempvc.user_can_run_tempvc", return_value=True),
            patch("cogs.tempvc.record_usage"),
        ):
            task = asyncio.create_task(self.cog._create_default_room(i))
            await entered.wait()
            await self.cog._create_default_room(j)
            release.set()
            await task
        self.cog._create_manual_temp_vc.assert_awaited_once()

    def room_creation_fixture(self):
        i = interaction()
        guild = i.guild
        guild.bitrate_limit = 64000
        category = MagicMock(spec=discord.CategoryChannel)
        category.id, category.channels = 20, []
        i.channel.category = category
        perms = discord.Permissions(view_channel=True, connect=True, speak=True)
        category.permissions_for.return_value = perms
        i.user.pending = False
        i.user.is_timed_out.return_value = False
        i.user.move_to = AsyncMock()
        guild.fetch_member = AsyncMock(return_value=i.user)
        guild.get_member.return_value = i.user
        rooms = {}
        guild.get_channel.side_effect = rooms.get
        guild.fetch_channel = AsyncMock(side_effect=lambda cid: rooms[cid])
        guild._state.http.get_all_guild_channels = AsyncMock(return_value=[])

        def new_room(cid):
            room = MagicMock(spec=discord.VoiceChannel)
            room.id, room.guild, room.category_id = cid, guild, category.id
            room.name, room.mention = f"room {cid}", f"<#{cid}>"
            room.user_limit, room.members = 32, []
            room.permissions_for.return_value = perms
            rooms[cid] = room
            return room

        guild.create_voice_channel = AsyncMock(side_effect=lambda *a, **kw: new_room(123))
        self.enterContext(patch("cogs.tempvc.user_can_run_tempvc", return_value=True))
        self.enterContext(patch("core.permissions.is_verified_member", return_value=True))
        usage = self.enterContext(patch("cogs.tempvc.record_usage", new_callable=AsyncMock))
        cleanup = self.enterContext(patch("cogs.tempvc.schedule_delete_if_empty", new_callable=AsyncMock))

        def reply(**kwargs):
            self.assertFalse(shared_async_lock("voice-create", guild.id).locked())

        i.edit_original_response.side_effect = reply
        return i, new_room, usage, cleanup

    async def assert_plan_creation_race(self, *, plan_first, entry):
        i, new_room, usage, cleanup = self.room_creation_fixture()
        plan_i = interaction(user=i.user, guild=i.guild, channel=i.channel)
        api_entered, api_release, second_waiting = (asyncio.Event() for _ in range(3))
        lock = shared_async_lock("voice-create", i.guild_id)
        lock_calls = 0

        @asynccontextmanager
        async def observed_lock(*key):
            nonlocal lock_calls
            self.assertEqual(key, ("voice-create", i.guild_id))
            lock_calls += 1
            if lock_calls == 2:
                self.assertTrue(lock.locked())
                second_waiting.set()
            async with shared_async_lock(*key):
                yield

        async def create(*args, **kwargs):
            api_entered.set()
            await api_release.wait()
            return new_room(122 + i.guild.create_voice_channel.await_count)

        def mark_attempt():
            self.assertTrue(lock.locked())
            self.assertFalse(tempvc_storage.owned_ids(i.guild_id, i.user.id))
            self.assertEqual(i.guild.create_voice_channel.await_count, 0)

        attempt = MagicMock(side_effect=mark_attempt)
        i.guild.create_voice_channel.side_effect = create
        if entry == "command":
            other = TempVC.vc_new.callback(self.cog, i, name="test", limit=8)
        elif entry == "menu":
            other = self.cog.menu_entry(i)
        else:
            hub = MagicMock(spec=discord.VoiceChannel)
            hub.id, hub.name, hub.category = 99, "開一個小隊 call", i.channel.category
            i.user.voice = MagicMock(channel=hub)
            self.enterContext(patch("cogs.tempvc.get_hub_channel_name", return_value=hub.name))
            other = self.cog.on_voice_state_update(i.user, MagicMock(channel=None), i.user.voice)
        plan = self.cog.room_for_plan(plan_i, before_create=attempt)
        first, second = (plan, other) if plan_first else (other, plan)
        tasks = []
        with patch("cogs.tempvc.shared_async_lock", side_effect=observed_lock):
            try:
                tasks.append(asyncio.create_task(first))
                await asyncio.wait_for(api_entered.wait(), timeout=2)
                self.assertFalse(tempvc_storage.owned_ids(i.guild_id, i.user.id))
                tasks.append(asyncio.create_task(second))
                await asyncio.wait_for(second_waiting.wait(), timeout=2)
                api_release.set()
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
            finally:
                api_release.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        i.guild.create_voice_channel.assert_awaited_once()
        self.assertIs(i.guild.create_voice_channel.await_args.kwargs["category"], i.channel.category)
        if entry == "command" and not plan_first:
            self.assertTrue(i.guild.create_voice_channel.await_args.args[0].endswith("test"))
            self.assertEqual(i.guild.create_voice_channel.await_args.kwargs["user_limit"], 8)
        room = results[0 if plan_first else 1]
        self.assertEqual(room.id, 123)
        self.assertEqual(tempvc_storage.owned_ids(i.guild_id, i.user.id), [123])
        self.assertEqual(attempt.call_count, int(plan_first))
        if entry == "hub":
            i.user.move_to.assert_awaited_once_with(room, reason=(
                "Reuse existing small-team room" if plan_first else "Moved to newly auto-created temp VC"))
        else:
            self.assertIn(room.mention, i.edit_original_response.await_args.kwargs["content"])
            self.assertEqual(usage.await_count, int(not plan_first))
            i.user.move_to.assert_not_awaited()
        self.assertEqual(cleanup.await_count, int(entry != "hub" or plan_first))

    async def test_plan_then_command_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=True, entry="command")

    async def test_command_then_plan_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=False, entry="command")

    async def test_plan_then_menu_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=True, entry="menu")

    async def test_menu_then_plan_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=False, entry="menu")

    async def test_plan_then_hub_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=True, entry="hub")

    async def test_hub_then_plan_creates_one_owned_room(self):
        await self.assert_plan_creation_race(plan_first=False, entry="hub")

    async def test_owned_lookup_failure_does_not_create_or_mark_attempt(self):
        i, _, usage, _ = self.room_creation_fixture()
        utils.track_temp_vc(123, guild_id=i.guild_id, creator_id=i.user.id)
        i.guild.fetch_channel.side_effect = discord.Forbidden(
            MagicMock(status=403, reason="Forbidden"), "cannot inspect existing room")
        attempt = MagicMock()
        await self.cog._create_default_room(i)
        self.assertIn("稍後再試", i.edit_original_response.await_args.kwargs["content"])
        with self.assertRaises(discord.Forbidden):
            await self.cog.room_for_plan(i, before_create=attempt)
        i.guild.create_voice_channel.assert_not_awaited()
        attempt.assert_not_called()
        usage.assert_not_awaited()
        self.assertEqual(tempvc_storage.owned_ids(i.guild_id, i.user.id), [123])

    async def test_manual_reuses_cross_category_room_but_plan_rejects_it(self):
        i, new_room, usage, _ = self.room_creation_fixture()
        room = new_room(123)
        room.category_id = 30
        utils.track_temp_vc(room.id, guild_id=i.guild_id, creator_id=i.user.id)
        attempt = MagicMock()
        with self.assertRaisesRegex(ValueError, "另一個遊戲區"):
            await self.cog.room_for_plan(i, before_create=attempt)
        await self.cog._create_default_room(i)
        self.assertIn(room.mention, i.edit_original_response.await_args.kwargs["content"])
        i.guild.create_voice_channel.assert_not_awaited()
        attempt.assert_not_called()
        usage.assert_not_awaited()

    async def test_inaccessible_owned_room_is_not_replaced(self):
        i, new_room, usage, _ = self.room_creation_fixture()
        room = new_room(123)
        room.permissions_for.return_value = discord.Permissions.none()
        utils.track_temp_vc(room.id, guild_id=i.guild_id, creator_id=i.user.id)
        attempt = MagicMock()
        with self.assertRaisesRegex(ValueError, "無權加入此語音房"):
            await self.cog.room_for_plan(i, before_create=attempt)
        await self.cog._create_default_room(i)
        self.assertIn("無法存取", i.edit_original_response.await_args.kwargs["content"])
        i.guild.create_voice_channel.assert_not_awaited()
        attempt.assert_not_called()
        usage.assert_not_awaited()

    async def test_owned_room_missing_from_cache_is_fetched_and_reused(self):
        i, new_room, usage, _ = self.room_creation_fixture()
        room = new_room(123)
        utils.track_temp_vc(room.id, guild_id=i.guild_id, creator_id=i.user.id)
        i.guild.get_channel.side_effect = lambda cid: None
        attempt = MagicMock()
        self.assertIs(await self.cog.room_for_plan(i, before_create=attempt), room)
        await self.cog._create_default_room(i)
        self.assertEqual(i.guild.fetch_channel.await_count, 2)
        i.guild.create_voice_channel.assert_not_awaited()
        attempt.assert_not_called()
        usage.assert_not_awaited()

    async def test_manual_permission_recheck_blocks_create(self):
        i, _, usage, _ = self.room_creation_fixture()
        with patch("cogs.tempvc.user_can_run_tempvc", side_effect=[True, False]):
            await self.cog._create_default_room(i)
        self.assertIn("存取權限已改變", i.edit_original_response.await_args.kwargs["content"])
        i.guild.create_voice_channel.assert_not_awaited()
        usage.assert_not_awaited()

    async def test_manual_create_failure_replies_after_unlocking(self):
        i, _, usage, _ = self.room_creation_fixture()
        i.guild.create_voice_channel.side_effect = discord.Forbidden(
            MagicMock(status=403, reason="Forbidden"), "cannot create room")
        with self.assertLogs("con9sole-bartender.tempvc", level="ERROR"):
            await self.cog._create_default_room(i)
        self.assertIn("稍後再試", i.edit_original_response.await_args.kwargs["content"])
        self.assertFalse(tempvc_storage.owned_ids(i.guild_id, i.user.id))
        usage.assert_not_awaited()

    async def test_in_room_quick_entry_opens_controls_instead_of_creating(self):
        i = interaction()
        self.cog._get_current_member_temp_vc = MagicMock(
            return_value=(i.user, MagicMock(), None)
        )
        self.cog.open_control_panel_from_menu = AsyncMock()
        self.cog._create_default_room = AsyncMock()
        await self.cog.menu_entry(i)
        self.cog.open_control_panel_from_menu.assert_awaited_once()
        self.cog._create_default_room.assert_not_awaited()

    async def test_repeated_migration_does_not_erase_creator(self):
        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        utils.track_temp_vc(123, guild_id=1)
        self.assertEqual(tempvc_storage.creator_id(123), 10)

    async def test_sweep_does_not_restart_an_existing_empty_room_countdown(self):
        from cogs.tempvc import schedule_delete_if_empty

        utils.track_temp_vc(123, guild_id=1, creator_id=10)
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.members = 123, []
        with patch(
            "cogs.tempvc.set_delete_task", wraps=utils.set_delete_task
        ) as register:
            await schedule_delete_if_empty(room)
            await schedule_delete_if_empty(room, force=True)
            register.assert_called_once()
        utils.cancel_all_delete_tasks()

    async def test_limit_api_failure_gives_a_private_response(self):
        i = interaction()
        room = MagicMock(spec=discord.VoiceChannel)
        room.id, room.members, room.user_limit = 123, [], 32
        room.edit = AsyncMock(
            side_effect=discord.Forbidden(
                MagicMock(status=403, reason="Forbidden"), "no access"
            )
        )
        self.cog._get_control_channel = MagicMock(return_value=(i.user, room, None))
        with (
            patch("cogs.tempvc.user_can_change_vc_limit", return_value=True),
            patch("cogs.tempvc.user_bypasses_vc_limit_cooldown", return_value=True),
        ):
            await self.cog.apply_vc_limit_from_modal(i, 123, 8)
        i.response.defer.assert_awaited_once()
        self.assertTrue(i.followup.send.await_args.kwargs["ephemeral"])
        self.assertIn("修改失敗", i.followup.send.await_args.kwargs["content"])
