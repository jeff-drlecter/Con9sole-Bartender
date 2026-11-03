import types
import unittest
from unittest.mock import AsyncMock, patch

from cogs.activity_reminder import Activity, ActivityReminder, Schedule
from cogs.squad_cards import SquadCards
from cogs import twitch_relay


class ReviewRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_failed_roster_edit_retries_then_stops_after_success(self):
        member = types.SimpleNamespace(id=1, display_name="Jeff", bot=False)
        channel = types.SimpleNamespace(id=10, category_id=20, members=[member])
        guild = types.SimpleNamespace(voice_channels=[channel], afk_channel=None)
        session = {"message": 99, "participants": {}, "roster": []}
        cog = types.SimpleNamespace(
            state={"settings": {"routes": {"20": 30}}, "sessions": {"10": session}},
            bot=types.SimpleNamespace(get_guild=lambda _: guild),
            render=AsyncMock(side_effect=RuntimeError("temporary failure")),
            save=lambda: None,
        )
        with self.assertRaises(RuntimeError):
            await SquadCards.reconcile(cog)
        self.assertEqual(session["roster"], [])
        cog.render.side_effect = None
        await SquadCards.reconcile(cog)
        self.assertEqual(cog.render.await_count, 2)
        self.assertEqual(session["roster"], [1])
        await SquadCards.reconcile(cog)
        self.assertEqual(cog.render.await_count, 2)

    async def test_twitch_relay_blocks_all_mentions_without_changing_text(self):
        class FakeTwitchBot:
            def __init__(self, **kwargs):
                self.nick = "bartender"
                self.connect = AsyncMock()
                self.close = AsyncMock()

        destination = types.SimpleNamespace(send=AsyncMock())
        message = types.SimpleNamespace(
            echo=False, content="@everyone @here <@123> <@&456>",
            author=types.SimpleNamespace(name="viewer", display_name="Viewer"),
            channel=types.SimpleNamespace(name="stream"), tags={"id": "regression-mention"},
        )
        with patch.object(twitch_relay.twitch_commands, "Bot", FakeTwitchBot), \
             patch.object(twitch_relay, "BOT_OAUTH", "test-only"), \
             patch.object(twitch_relay, "RELAY_CONFIG", [{"twitch_channel": "stream", "discord_channel_id": 30}]), \
             patch.object(twitch_relay, "_safe_get_messageable_channel", AsyncMock(return_value=destination)), \
             patch.dict(twitch_relay._recent_td, {}, clear=True), \
             patch.dict(twitch_relay._recent_tw_ids, {}, clear=True):
            relay = twitch_relay.TwitchRelay(object())
            try:
                await relay.twitch_bot.event_message(message)
                destination.send.assert_awaited_once()
                args, kwargs = destination.send.call_args
                self.assertEqual(args[0], "[Twitch] Viewer: " + message.content)
                self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse": []})
            finally:
                await relay.cog_unload()

    async def test_activity_lists_split_without_losing_content(self):
        for count, name_length in ((1, 10), (15, 40), (35, 40), (1, 4500)):
            with self.subTest(count=count, name_length=name_length):
                cog = object.__new__(ActivityReminder)
                cog.activities = {
                    str(i): Activity(str(i), "A" * name_length, 123456789012345678,
                                     123456789012345678, [Schedule(list(range(7)), "20:00")])
                    for i in range(count)
                }
                interaction = types.SimpleNamespace(
                    response=types.SimpleNamespace(send_message=AsyncMock()),
                    followup=types.SimpleNamespace(send=AsyncMock()),
                )
                await ActivityReminder.activity_list.callback(cog, interaction)
                initial = interaction.response.send_message.call_args
                followups = interaction.followup.send.call_args_list
                calls = [initial, *followups]
                for call in calls:
                    self.assertTrue(0 < len(call.args[0]) <= 2000)
                    self.assertTrue(call.kwargs["ephemeral"])
                actual = "".join(call.args[0] for call in (followups or [initial]))
                lines = []
                for activity in cog.activities.values():
                    lines.extend([
                        f"**{activity.name}**  （ID: `{activity.id}`）",
                        f"- 頻道：<#{activity.channel_id}>",
                        f"- Tag：<@&{activity.ping_role_id}>",
                        f"- 時段 #1：{cog._format_schedule(activity.schedules[0])}", "",
                    ])
                self.assertEqual(actual, "\n".join(lines).strip())
