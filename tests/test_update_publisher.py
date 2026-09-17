from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.update_publisher import (
    AnnouncementDraft,
    build_announcement_embed,
    game_draft_from_pending,
    get_pending_games,
    mark_games_published,
    record_created_game,
)


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


if __name__ == "__main__":
    unittest.main()
