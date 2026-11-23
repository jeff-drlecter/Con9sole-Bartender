from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.update_publisher import PublisherStartView, send_draft_preview, send_version_picker
from features.language_preferences import ROLE_NAMES
from features.update_publisher import AnnouncementDraft, PendingGame, build_announcement_text


def operator(*codes):
    roles = [
        SimpleNamespace(name=ROLE_NAMES[code], managed=False, permissions=SimpleNamespace(value=0))
        for code in codes
    ]
    return SimpleNamespace(id=1, roles=roles)


def interaction(*codes):
    return SimpleNamespace(
        user=operator(*codes),
        guild_id=2,
        response=AsyncMock(),
        followup=AsyncMock(),
        original_response=AsyncMock(),
    )


GAME = PendingGame(id="game", guild_id=2, name="搵隊友／約局", detail="飲一杯", created_at="")
DRAFT = AnnouncementDraft(
    kind="game", title="更新", body="飲一杯", thread_body="搵 Helper <@&42> https://example.org/{hk}",
    game_ids=(GAME.id,), version="v1.2.3", announcement_date="17.09.2026",
)


class PublisherWordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_preview_localizes_private_copy_only(self):
        public_text = build_announcement_text(DRAFT, games=[GAME])
        for codes in (("hk",), ("tw",), (), ("hk", "tw")):
            with self.subTest(codes=codes):
                i = interaction(*codes)
                await send_draft_preview(i, DRAFT, [GAME])
                sent = i.response.send_message.call_args
                note = "以下係草稿預覽；未發佈。" if codes == ("hk",) else "以下是草稿預覽，尚未發佈。"
                heading = "A 下方的 Thread" if codes == ("hk",) else "公告下方的討論串"
                self.assertEqual(sent.args[0], f"{note}\n\n**內容 A｜公告**\n{public_text}\n\n**內容 B｜{heading}**\n{DRAFT.thread_body}")
                self.assertTrue(sent.kwargs["ephemeral"])

    async def test_edit_uses_submitters_current_preference_for_preview_and_confirmation(self):
        for codes in (("hk",), ("tw",), (), ("hk", "tw")):
            with self.subTest(codes=codes):
                original = interaction("tw" if codes == ("hk",) else "hk")
                await send_draft_preview(original, DRAFT, [GAME])
                review = original.response.send_message.call_args.kwargs["view"]
                i = interaction(*codes)
                with patch("cogs.update_publisher.latest_announcement_version", return_value=(1, 2, 3)):
                    await review.edit_draft.callback(i)
                picker = i.response.send_message.call_args.kwargs["view"]
                await picker.children[0].callback(i)
                modal = i.response.send_modal.call_args.args[0]
                self.assertEqual(modal.new_features.default, DRAFT.body)
                self.assertEqual(modal.thread_content.default, DRAFT.thread_body)
                self.assertIn("中性繁體中文", modal.new_features.label)
                hk = codes == ("hk",)
                self.assertEqual(modal.thread_content.placeholder, "留空就唔開 Thread" if hk else "留空即不建立討論串")

                edited = replace(DRAFT, body="搵 Helper", thread_body="飲一杯 <#123> https://example.org/{hk}")
                fields = (
                    (modal.announcement_date, edited.announcement_date),
                    (modal.new_features, edited.body),
                    (modal.thread_content, edited.thread_body),
                )
                for item, value in fields:
                    item._refresh_state(i, {"value": value})
                with patch("cogs.update_publisher._publisher_access_allowed", return_value=True):
                    await modal.on_submit(i)
                preview = review.message.edit.call_args.kwargs["content"]
                self.assertTrue(preview.startswith("以下係草稿預覽；未發佈。" if hk else "以下是草稿預覽，尚未發佈。"))
                self.assertIn(build_announcement_text(edited, games=[GAME]), preview)
                self.assertTrue(preview.endswith(edited.thread_body))
                i.followup.send.assert_awaited_once_with(
                    "✅ 改好草稿，未發佈。" if hk else "✅ 草稿已更新，尚未發佈。", ephemeral=True)

    async def test_game_picker_and_creation_modal_preserve_supplied_values(self):
        i = interaction("tw")
        with patch("cogs.update_publisher.get_pending_games", return_value=[GAME]):
            await PublisherStartView(owner_id=1, guild_id=2).game_draft.callback(i)
        sent = i.response.send_message.call_args
        self.assertIn("請選擇", sent.args[0])
        option = sent.kwargs["view"].children[0].options[0]
        self.assertEqual((option.label, option.description, option.value), (GAME.name, GAME.detail, GAME.id))

        with patch("cogs.update_publisher.latest_announcement_version", return_value=None):
            await send_version_picker(i, kind="game", games=[GAME])
        picker = i.response.send_message.call_args.kwargs["view"]
        await picker.children[0].callback(i)
        modal = i.response.send_modal.call_args.args[0]
        self.assertEqual(modal.new_features.default, f"新增 {GAME.name} 遊戲專區")
        self.assertIn("中性繁體中文", modal.thread_content.label)
        self.assertEqual(modal.thread_content.placeholder, "留空即不建立討論串")

    async def test_denial_uses_clicking_operators_own_preference(self):
        view = PublisherStartView(owner_id=99, guild_id=2)
        for codes in (("hk",), ("tw",), (), ("hk", "tw")):
            with self.subTest(codes=codes):
                i = interaction(*codes)
                self.assertFalse(await view.interaction_check(i))
                i.response.send_message.assert_awaited_once_with(
                    "呢份草稿工具只限開啟者使用。" if codes == ("hk",) else "這個草稿工具僅供開啟者使用。",
                    ephemeral=True,
                )
