import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from quick_bar_fakes import interaction

import utils
from cogs.tempvc import TempVC
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
            patch("cogs.tempvc.record_usage_sync"),
        ):
            await self.cog.menu_entry(i)
        self.cog._create_manual_temp_vc.assert_awaited_once()
        self.assertEqual(self.cog._create_manual_temp_vc.await_args.kwargs["limit"], 32)
        i.response.send_modal.assert_not_awaited()
        view = i.edit_original_response.await_args.kwargs["view"]
        self.assertTrue(any(button.url for button in view.children))

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
            "你間小隊 call", i.edit_original_response.await_args.kwargs["content"]
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
            patch("cogs.tempvc.record_usage_sync"),
        ):
            task = asyncio.create_task(self.cog._create_default_room(i))
            await entered.wait()
            await self.cog._create_default_room(j)
            release.set()
            await task
        self.cog._create_manual_temp_vc.assert_awaited_once()

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
