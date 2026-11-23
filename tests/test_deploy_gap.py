import json
import os
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
import tempfile
import unittest
from unittest.mock import patch

from scripts import measure_deploy_gap as gap


MACHINE = "abc012"
SHA = "a" * 40
SINCE = datetime.fromisoformat("2026-11-23T12:39:38Z")
STOP = "\x1b[32m INFO\x1b[0m Sending signal SIGINT to main child process w/ PID 642"
READY = "2026-11-23 12:40:00,123 INFO con9sole-bartender: Release ready commit=" + SHA


def entry(message, timestamp, machine=MACHINE):
    return json.dumps({"message": message, "timestamp": timestamp, "instance": machine}, indent=2) + "\n"


class DeployGapTests(unittest.TestCase):
    def test_correlates_machine_image_and_rollout_and_deduplicates_fly_buffers(self):
        stop = entry(STOP, "2026-11-23T12:39:50.200000001Z")
        ready = entry(READY, "2026-11-23T12:40:00.450Z")
        raw = (ready + stop + stop + entry(STOP, "2026-11-22T20:10:00Z")
               + entry(STOP, "2026-11-23T12:39:55Z", "other")
               + entry(READY.replace(SHA, "b" * 40), "2026-11-23T12:39:56Z")
               + entry("private member text: " + READY, "2026-11-23T12:39:59Z"))
        events = set(gap.lifecycle_events(raw, MACHINE, SHA, SINCE))
        self.assertEqual(len(events), 2)
        self.assertIn("10.25 seconds", gap.summary(events))
        for extra in (entry(STOP, "2026-11-23T12:39:58Z"), entry(READY, "2026-11-23T12:40:01Z")):
            self.assertIn("Unavailable", gap.summary(events | set(gap.lifecycle_events(extra, MACHINE, SHA, SINCE))))

    def test_no_estimate_for_missing_or_reversed_markers(self):
        for raw in ("", entry(STOP, "2026-11-23T12:39:50Z"), entry(READY, "2026-11-23T12:39:51Z"),
                    entry(READY, "2026-11-23T12:39:42Z") + entry(STOP, "2026-11-23T12:39:50Z")):
            self.assertIn("Unavailable", gap.summary(set(gap.lifecycle_events(raw, MACHINE, SHA, SINCE))))

    def test_observer_retains_old_marker_until_a_later_buffer_after_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            finished = Path(tmp) / "result"
            stop = CompletedProcess([], 0, entry(STOP, "2026-11-23T12:39:50Z"))
            ready = CompletedProcess([], 0, entry(READY, "2026-11-23T12:40:00Z"))
            with (patch.object(gap.subprocess, "run", side_effect=[stop, TimeoutExpired("flyctl", 6), ready]),
                  patch.object(gap.time, "sleep", side_effect=lambda _: finished.write_text("0"))):
                self.assertIn("10.00 seconds", gap.observe(MACHINE, SHA, SINCE, finished))
            finished.write_text("1")
            with patch.object(gap.subprocess, "run") as fetch:
                self.assertIn("did not succeed", gap.observe(MACHINE, SHA, SINCE, finished))
                fetch.assert_not_called()
            finished.write_text("0")
            with (patch.object(gap.subprocess, "run", side_effect=TimeoutExpired("flyctl", 6)),
                  patch.object(gap.time, "monotonic", side_effect=[0, 21])):
                self.assertIn("Unavailable", gap.observe(MACHINE, SHA, SINCE, finished))


class BotReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_requires_usable_persistent_button_and_is_emitted_only_once(self):
        from bot import Bot
        from cogs.member_entry import MemberEntryView
        from features.welcome_verification import VERIFY_BUTTON

        async with Bot() as bot:
            with patch.dict(os.environ, APP_COMMIT=SHA), self.assertLogs("con9sole-bartender") as logs:
                bot.add_view(MemberEntryView())
                await bot.on_ready()
                bot._ready.set()
                await bot.on_ready()
                view = MemberEntryView(welcome=True)
                verify = next(item for item in view.children if item.custom_id == VERIFY_BUTTON)
                verify.disabled = True
                bot.add_view(view)
                await bot.on_ready()
                self.assertFalse(any("Release ready" in text for text in logs.output))
                verify.disabled = False
                await bot.on_ready()
                await bot.on_ready()
            self.assertEqual(sum(f"Release ready commit={SHA}" in text for text in logs.output), 1)
