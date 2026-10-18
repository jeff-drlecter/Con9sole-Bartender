import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from quick_bar_fakes import interaction, member

from cogs.teams import TeamCountView, Teams, TeamState, TeamView, infer_game_name
from features import team_storage


class TeamFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(
            team_storage, "STATS_DB", Path(self.temp.name) / "teams.sqlite3"
        )
        self.patch.start()
        team_storage.init_team_db()
        self.cog = Teams(MagicMock())

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def state(self, *, required=2):
        return TeamState(
            leader_id=10,
            required=required,
            mode="GTA",
            channel_id=100,
            guild_id=1,
            message_id=500,
        )

    async def test_game_forum_thread_infers_game(self):
        parent = MagicMock(spec=discord.ForumChannel)
        parent.name = "gta-vi-專區"
        thread = MagicMock(spec=discord.Thread)
        thread.parent = parent
        self.assertEqual(infer_game_name(thread), "gta-vi")

    async def test_general_channel_does_not_guess_a_game(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "吹水"
        channel.category = None
        self.assertIsNone(infer_game_name(channel))

    async def test_count_button_creates_without_a_mode_modal_in_game_context(self):
        self.cog.create_team = AsyncMock(return_value=True)
        view = TeamCountView(self.cog, 10, game="GTA")
        i = interaction()
        await next(
            button for button in view.children if getattr(button, "count", None) == 1
        ).callback(i)
        self.cog.create_team.assert_awaited_once_with(i, 1, "GTA")
        i.response.send_modal.assert_not_awaited()

    async def test_unknown_game_only_asks_for_details_after_count(self):
        self.cog.create_team = AsyncMock()
        view = TeamCountView(self.cog, 10)
        i = interaction()
        await next(
            button for button in view.children if getattr(button, "count", None) == 1
        ).callback(i)
        i.response.send_modal.assert_awaited_once()
        self.cog.create_team.assert_not_awaited()

    async def test_create_then_restore_active_card_after_restart(self):
        i = interaction()
        with patch("cogs.teams.record_usage_sync"):
            self.assertTrue(await self.cog.create_team(i, 2, "GTA"))
        bot = MagicMock()
        bot.wait_until_ready = AsyncMock()
        bot.is_closed.return_value = True
        restored = Teams(bot)
        await restored.cog_load()
        try:
            self.assertEqual(restored.states[500].mode, "GTA")
            self.assertTrue(restored.views[500].is_persistent())
            self.assertTrue(
                any(
                    call.kwargs.get("message_id") == 500
                    for call in bot.add_view.call_args_list
                )
            )
        finally:
            await restored.cog_unload()

    async def test_concurrent_join_does_not_overfill_last_slot(self):
        state = self.state(required=1)
        view = TeamView(self.cog, state)
        first, second = interaction(member(20)), interaction(member(30))
        await asyncio.gather(
            view.join(first, later=False), view.join(second, later=False)
        )
        self.assertEqual(len(state.join_now), 1)
        self.assertEqual(len(team_storage.load_teams()), 1)

    async def test_duplicate_join_and_leave_keep_counts_consistent(self):
        state = self.state()
        view = TeamView(self.cog, state)
        await view.join(interaction(member(20)), later=False)
        await view.join(interaction(member(20)), later=True)
        self.assertEqual(state.join_now, {20})
        self.assertFalse(state.join_later)
        await view.leave.callback(interaction(member(20)))
        self.assertFalse(state.join_now)

    async def test_failed_save_does_not_leave_a_phantom_join(self):
        state = self.state()
        view = TeamView(self.cog, state)
        with patch.object(team_storage, "save_team", side_effect=OSError("disk full")):
            with self.assertLogs("con9sole-bartender.teams", level="ERROR"):
                await view.join(interaction(member(20)), later=False)
        self.assertFalse(state.join_now)

    async def test_expired_card_rejects_join(self):
        state = self.state()
        state.created_at = time.time() - 7 * 3600
        view = TeamView(self.cog, state)
        self.assertFalse(await view.interaction_check(interaction(member(20))))
        await view.join(interaction(member(20)), later=False)
        self.assertFalse(state.join_now)

    async def test_same_leader_cannot_open_second_active_card(self):
        self.cog.states[500] = self.state()
        i = interaction()
        self.assertFalse(await self.cog.create_team(i, 2, "Another game"))
        i.edit_original_response.assert_not_awaited()

    async def test_read_only_channel_cannot_create_team(self):
        i = interaction(can_send=False)
        self.assertFalse(await self.cog.create_team(i, 2, "GTA"))
        self.assertFalse(team_storage.load_teams())

    async def test_failed_close_save_keeps_recruitment_open(self):
        state = self.state()
        view = TeamView(self.cog, state)
        with patch.object(team_storage, "save_team", side_effect=OSError("disk full")):
            with self.assertLogs("con9sole-bartender.teams", level="ERROR"):
                await view.finish(interaction())
        self.assertFalse(state.cancelled)
