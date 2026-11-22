"""Offline replay of the scheduled plan form and the same owner's private draft."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import config
from cogs.squad_plans import PlanForm, SquadPlans, open_creation
from features.plan_delivery_ui import Draft, Numbers
from features.squad_plans import HK, PlanBook, parse_start


class PlanDraftReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.trace = []
        self.enterContext(patch.multiple(config, GUILD_ID=101, VERIFIED_ROLE_ID=102))
        data_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with patch("cogs.squad_plans.DATA_DIR", data_dir):
            self.cog = SquadPlans(None)
        now = datetime(2030, 1, 2, 12, tzinfo=HK)
        self.enterContext(patch("cogs.squad_plans.parse_start", partial(parse_start, now=now)))

        roles = [
            SimpleNamespace(id=102, name="測試會員", managed=False, permissions=discord.Permissions.none()),
            SimpleNamespace(id=103, name="語境偏好｜香港", managed=False, permissions=discord.Permissions.none()),
        ]
        self.guild = SimpleNamespace(id=101, create_scheduled_event=AsyncMock())
        self.owner, self.other = [MagicMock(spec=discord.Member) for _ in range(2)]
        for uid, member in [(201, self.owner), (202, self.other)]:
            member.id, member.guild, member.roles, member.bot = uid, self.guild, roles, False
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.category = 301, self.guild, None
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, read_message_history=True, send_messages=True, embed_links=True
        )
        members = {m.id: m for m in (self.owner, self.other)}
        self.guild.fetch_member = AsyncMock(side_effect=members.__getitem__)
        self.guild.fetch_channel = AsyncMock(side_effect={301: self.channel}.__getitem__)
        self.guild.fetch_roles = AsyncMock(return_value=roles)

    def interaction(self, user=None):
        response = SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock(),
                                   defer=AsyncMock(), edit_message=AsyncMock())
        initial_responses = (response.send_modal, response.send_message, response.defer, response.edit_message)
        response.is_done = lambda: any(method.await_count for method in initial_responses)
        followup = AsyncMock()

        def check_transport():
            self.assertEqual(sum(method.await_count for method in initial_responses), 1,
                             "interaction requires exactly one initial response")
            for call in response.send_message.await_args_list:
                self.assertIs(call.kwargs.get("ephemeral"), True, "unexpected public response")
            followup.assert_not_awaited()

        self.addCleanup(check_transport)
        return SimpleNamespace(guild=self.guild, guild_id=self.guild.id, user=user or self.owner,
                               channel=self.channel, channel_id=self.channel.id, response=response,
                               followup=SimpleNamespace(send=followup), edit_original_response=AsyncMock())

    def snapshot(self, step, content, view):
        controls = []
        for row in view.to_components() if hasattr(view, "to_components") else []:
            for field in row.get("components", []):
                control = dict(label=field.get("label", field.get("placeholder", "")), value=None,
                               disabled=field.get("disabled", False))
                if field["type"] == discord.ComponentType.text_input.value:
                    control.update(value=field.get("value", ""), required=field.get("required", True))
                controls.append(control)
        self.trace.append(dict(step=step, content=content, controls=controls))

    def opened_modal(self, step, interaction, expected_type):
        interaction.response.send_modal.assert_awaited_once()
        modal, = interaction.response.send_modal.await_args.args
        self.snapshot(step, getattr(modal, "title", ""), modal)
        self.assertIsInstance(modal, expected_type)
        return modal

    def edited_draft(self, step, interaction):
        interaction.edit_original_response.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        view, content = kwargs.get("view"), kwargs.get("content", "")
        self.snapshot(step, content, view)
        self.assertIsInstance(view, Draft, content)
        return view, content

    async def submit(self, modal, **values):
        interaction = self.interaction()
        # Only submit fields a user could fill or clear in the emitted SDK form.
        entries = {getattr(modal, name).custom_id: value for name, value in values.items()}
        rows = []
        for row in modal.to_components():
            for field in row["components"]:
                key = field["custom_id"]
                value = entries.pop(key, field.get("value", ""))
                self.assertTrue(value or not field.get("required", True),
                                f'{field["label"]} is required and cannot be submitted empty')
                rows.append({"type": 1, "components": [{"type": field["type"], "custom_id": key, "value": value}]})
        self.assertFalse(entries, "Input supplied for a field missing from the SDK form")
        modal._refresh(interaction, rows, {})
        self.assertTrue(await modal.interaction_check(interaction))
        await modal.on_submit(interaction)
        return interaction

    async def press(self, button, user=None):
        interaction = self.interaction(user)
        if await button.view.interaction_check(interaction):
            self.assertFalse(button.disabled, f"button disabled: {button.label}")
            await button.callback(interaction)
        return interaction

    async def test_scheduled_draft_replay(self):
        with self.subTest(step="開啟約定時間表格"):
            entry = self.interaction()
            await open_creation(entry, self.cog, self.channel)
            form = self.opened_modal("開啟約定時間表格", entry, PlanForm)
            self.assertIn(form.start, form.children)

        with self.subTest(step="預覽四人草稿"):
            submitted = await self.submit(form, game="合作測試局", start="聽日 21:00",
                                          mode="PC 合作", party="1", missing="3")
            submitted.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
            draft, content = self.edited_draft("預覽四人草稿", submitted)
            self.assertIn("合作測試局", content)
            self.assertIn("PC 合作", content)
            start = int(datetime(2030, 1, 3, 21, tzinfo=HK).timestamp())
            self.assertIn(f"<t:{start}:F>", content)
            self.assertIn("原有 1 人 · 最高 4 人", content)
            self.assertIn("4 人成局，夠人就自動建立活動", content)
            self.assertIn("有人報名時提我：開啟", content)
            self.assertFalse(draft.auto.disabled)

        with self.subTest(step="其他會員嘗試取消"):
            denied = await self.press(draft.cancel, self.other)
            denied.response.send_message.assert_awaited_once()
            message = denied.response.send_message.await_args
            content = message.args[0] if message.args else message.kwargs.get("content")
            self.snapshot("其他會員嘗試取消", content, message.kwargs.get("view"))
            self.assertIs(message.kwargs.get("ephemeral"), True)
            self.assertIn("唔屬於你", content or "")
            self.assertFalse(draft.used)

        with self.subTest(step="開啟人數設定"):
            numbers = self.opened_modal("開啟人數設定", await self.press(draft.numbers), Numbers)
            self.assertEqual((numbers.minimum.default, numbers.capacity.default), ("4", "4"))
            self.assertFalse(self.trace[-1]["controls"][0]["required"], "成局人數必須容許留空")

        with self.subTest(step="清空成局人數"):
            edited = await self.submit(numbers, minimum="", capacity="4")
            draft, content = self.edited_draft("清空成局人數", edited)
            self.assertIn("最高 4 人", content)
            self.assertIn("唔自動建立活動", content)
            self.assertIn("有人報名時提我：開啟", content)
            self.assertTrue(draft.auto.disabled)
            self.assertIsNone(draft.settings["minimum"])

        with self.subTest(step="關閉報名提醒"):
            draft, content = self.edited_draft("關閉報名提醒", await self.press(draft.notice))
            self.assertIn("有人報名時提我：關閉", content)
            self.assertIn("唔自動建立活動", content)
            self.assertTrue(draft.auto.disabled)

        with self.subTest(step="重開人數設定"):
            reopened = self.opened_modal("重開人數設定", await self.press(draft.numbers), Numbers)
            self.assertEqual(reopened.minimum.value, "", "成局人數重開後應留空")
            self.assertEqual(reopened.capacity.value, "4", "重開後應保留最高四人")
            self.assertEqual([control["value"] for control in self.trace[-1]["controls"]], ["", "4"],
                             "重開時送往 Discord 的表格應顯示空白成局人數和四人上限")
            self.assertFalse(self.trace[-1]["controls"][0]["required"], "重開後成局人數仍須容許留空")

        with self.subTest(step="取消草稿"):
            cancelled = await self.press(draft.cancel)
            cancelled.response.edit_message.assert_awaited_once()
            kwargs = cancelled.response.edit_message.await_args.kwargs
            self.snapshot("取消草稿", kwargs.get("content", ""), kwargs.get("view"))
            self.assertEqual(kwargs["content"], "草稿已取消。")
            self.assertIsNone(kwargs["view"], "取消後必須移除所有按鈕")
            self.assertTrue(draft.used)
            self.assertEqual(self.cog.book.all(), [])
            self.assertEqual(PlanBook(self.cog.book.path).all(), [], "取消後重新載入預約簿應為空")
            self.guild.create_scheduled_event.assert_not_awaited()
            self.channel.send.assert_not_awaited()


class ReplayReportTests(unittest.TestCase):
    def test_empty_cancel_reply_can_be_rendered_as_failure(self):
        from scripts.draft_replay_report import write_report

        step = {"step": "取消草稿", "content": None, "controls": []}
        trace = {"passed": False, "failed_step": step["step"], "steps": [step]}
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder)
            (evidence / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
            page, count = write_report(evidence)
            html = page.read_text(encoding="utf-8")
        self.assertEqual(count, 1)
        self.assertIn("未通過 · 取消草稿", html)
        self.assertIn("<p></p>", html)


if __name__ == "__main__":
    case = PlanDraftReplayTests("test_scheduled_draft_replay")
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(case)
    # Discovery never writes evidence. Only the single-scenario runner reads this opt-in.
    if destination := os.environ.get("CON9SOLE_REPLAY_TRACE"):
        failed_step = next((getattr(test, "params", {}).get("step", "互動或測試環境")
                            for test, _ in result.failures + result.errors), None)
        with Path(destination).open("x", encoding="utf-8") as stream:
            json.dump({"passed": result.wasSuccessful(), "failed_step": failed_step, "steps": case.trace},
                      stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    if not result.wasSuccessful():
        raise SystemExit(1)
