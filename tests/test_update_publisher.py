from __future__ import annotations

import tempfile
import unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from features.update_publisher import (
    AnnouncementDraft,
    build_announcement_embed,
    build_announcement_text,
    game_name_from_forum,
    game_draft_from_pending,
    get_pending_games,
    mark_games_published,
    record_created_game,
)
from cogs.update_publisher import AnnouncementDetailsModal, VersionSelectionView, DraftReviewView


class UpdatePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "game_announcements.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_created_games_are_pending_until_manually_marked_published(self) -> None:
        first = record_created_game(
            guild_id=1,
            name="Game A",
            detail="已建立 <#10>。",
            path=self.path,
        )
        second = record_created_game(
            guild_id=1,
            name="Game B",
            detail="已建立 <#11>。",
            path=self.path,
        )

        self.assertEqual([game.name for game in get_pending_games(1, path=self.path)], ["Game A", "Game B"])

        mark_games_published(1, (first.id,), message_id=99, path=self.path)

        self.assertEqual([game.name for game in get_pending_games(1, path=self.path)], ["Game B"])
        self.assertEqual(get_pending_games(2, path=self.path), [])
        self.assertNotEqual(first.id, second.id)

    def test_game_draft_previews_all_selected_games(self) -> None:
        games = [
            record_created_game(guild_id=1, name="Game A", detail="新專區 A", path=self.path),
            record_created_game(guild_id=1, name="Game B", detail="新專區 B", path=self.path),
        ]

        draft = game_draft_from_pending(games, intro="一齊玩啦。")
        embed = build_announcement_embed(draft, games=games)

        self.assertEqual(draft.game_ids, tuple(game.id for game in games))
        self.assertEqual(embed.title, "🎮 遊戲專區更新")
        self.assertEqual(embed.description, "一齊玩啦。")
        self.assertIn("**Game A**｜新專區 A", embed.fields[0].value)
        self.assertIn("**Game B**｜新專區 B", embed.fields[0].value)

    def test_feature_draft_does_not_need_game_records(self) -> None:
        draft = AnnouncementDraft(kind="feature", title="✨ 功能更新", body="已改善載入速度。")

        embed = build_announcement_embed(draft)

        self.assertEqual(embed.title, "✨ 功能更新")
        self.assertEqual(embed.description, "已改善載入速度。")
        self.assertEqual(len(embed.fields), 0)

    def test_game_preview_splits_long_lists_into_valid_embed_fields(self) -> None:
        games = [
            record_created_game(guild_id=1, name=f"Game {index}", detail="x" * 600, path=self.path)
            for index in range(2)
        ]

        embed = build_announcement_embed(game_draft_from_pending(games), games=games)

        self.assertEqual(len(embed.fields), 2)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))

    def test_existing_forum_backfill_is_not_duplicated_while_pending(self) -> None:
        first = record_created_game(
            guild_id=1,
            name="FC27",
            detail="<#10> 已開放。",
            source_key="forum:10",
            role_id=100,
            path=self.path,
        )
        second = record_created_game(
            guild_id=1,
            name="FC27",
            detail="<#10> 已開放；專用身份：<@&200>",
            source_key="forum:10",
            role_id=200,
            path=self.path,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(len(get_pending_games(1, path=self.path)), 1)
        self.assertEqual(second.role_id, 200)
        self.assertIn("<@&200>", second.detail)

    def test_game_name_is_derived_from_forum_name(self) -> None:
        self.assertEqual(game_name_from_forum("fc27-專區"), "fc27")
        self.assertEqual(game_name_from_forum("NBA 2K27"), "NBA 2K27")

    def test_plain_announcement_matches_version_date_and_feature_format(self) -> None:
        games = [
            record_created_game(
                guild_id=1,
                name="FC27",
                detail="<#10> 已開放；專用身份：<@&100>",
                path=self.path,
            )
        ]
        draft = AnnouncementDraft(
            kind="game",
            title="Con9sole 更新公告",
            body="新增遊戲專區",
            game_ids=(games[0].id,),
            version="3.8.0",
            announcement_date="17.09.2026",
        )

        text = build_announcement_text(draft, games=games)

        self.assertIn("📣 **Con9sole 更新公告 — v3.8.0**", text)
        self.assertIn("📅 **17.09.2026**", text)
        self.assertIn("🆕 **新功能**", text)
        self.assertIn("• 新增遊戲專區", text)
        self.assertIn("🎮 **新增遊戲專區**", text)
        self.assertIn("• **FC27**｜<#10> 已開放；專用身份：<@&100>", text)
        self.assertIn("🧭 **加入方法**", text)
        self.assertIn("<id:customize>", text)
        self.assertIn("勾選想加入的遊戲角色，即可看到對應專區", text)

    def test_game_modal_suggests_new_feature_copy(self) -> None:
        game_a = record_created_game(guild_id=1, name="FC27", detail="FC27 detail", path=self.path)
        game_b = record_created_game(guild_id=1, name="NBA 2K27", detail="NBA detail", path=self.path)

        async def build_modal() -> str | None:
            modal = AnnouncementDetailsModal(kind="game", games=[game_a, game_b])
            return modal.new_features.default

        self.assertEqual(asyncio.run(build_modal()), "新增 FC27、NBA 2K27 遊戲專區")


if __name__ == "__main__":
    unittest.main()


class VersionButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_versions_follow_latest_published_record(self):
        with patch("cogs.update_publisher.latest_announcement_version", return_value=(3, 9, 2)):
            view = VersionSelectionView(owner_id=1, guild_id=2, kind="feature", games=[])
        self.assertEqual([button.version for button in view.children], ["v3.9.3", "v3.10.0", "v4.0.0"])
        interaction = SimpleNamespace(response=SimpleNamespace(send_modal=AsyncMock()))
        await view.children[1].callback(interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.version, "v3.10.0")
        self.assertEqual(len(modal.children), 2)

    async def test_first_announcement_has_version_button(self):
        with patch("cogs.update_publisher.latest_announcement_version", return_value=None):
            view = VersionSelectionView(owner_id=1, guild_id=2, kind="feature", games=[])
        self.assertEqual([button.version for button in view.children], ["v1.0.0"])

    async def test_edit_preserves_current_version_and_rejects_stale_picker(self):
        review = DraftReviewView(owner_id=1, guild_id=2,
            draft=AnnouncementDraft(kind="feature", title="test", body="body", version="v3.9.1"), games=[])
        with patch("cogs.update_publisher.latest_announcement_version", return_value=(3, 9, 1)):
            view = VersionSelectionView(owner_id=1, guild_id=2, kind="feature", games=[], review_view=review)
        self.assertEqual(view.children[0].version, "v3.9.1")
        interaction = SimpleNamespace(response=SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock()))
        for state in ("cancelled", "publishing", "editing"):
            setattr(review, state, True)
            await view.children[1].callback(interaction)
            setattr(review, state, False)
        review.revision += 1
        await view.children[1].callback(interaction)
        self.assertEqual(interaction.response.send_message.await_count, 4)
        interaction.response.send_modal.assert_not_awaited()
