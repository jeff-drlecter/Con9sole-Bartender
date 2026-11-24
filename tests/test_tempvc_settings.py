from __future__ import annotations

import unittest
from unittest.mock import patch

import config
from features.tempvc_settings import (
    community_room_name,
    format_seconds,
    get_auto_vc_user_limit,
    get_timeout_seconds,
    next_temp_channel_name,
    normalize_limit,
    parse_manual_limit,
)


class TempVCSettingsTests(unittest.TestCase):
    def test_community_name_exact_separator_whitespace_and_no_double_period(self):
        self.assertEqual(community_room_name('Entry Level', 'Clubs 球會'), 'Clubs 球會．Entry Level')
        self.assertEqual(community_room_name(' Entry Level ', '  Clubs   球會．  '), 'Clubs 球會．Entry Level')
        for mode in ('REC.', 'REC．', 'REC。', 'REC... '):
            self.assertEqual(community_room_name('南區聯隊', mode), 'REC．南區聯隊')
        self.assertEqual(community_room_name('南區聯隊'), '南區聯隊')

    def test_community_name_limit_preserves_full_chinese_name(self):
        name = '南區聯隊' * 20
        result = community_room_name(name, 'Clubs 球會 ' * 20)
        self.assertLessEqual(len(result), 100)
        self.assertTrue(result.endswith('．' + name))
        self.assertEqual(result.split('．', 1)[1], name)
        self.assertEqual(community_room_name('全' * 100, 'REC'), '全' * 100)
        with patch.object(config, 'TEMP_VC_HUB_NAME', '開房入口', create=True):
            self.assertEqual(community_room_name('開房入口'), '公會 · 開房入口')
            self.assertEqual(community_room_name('開房入口', 'REC'), 'REC．開房入口')

    def test_next_name_fills_first_available_gap(self) -> None:
        names = ["小隊call • 1", "小隊call • 3", "unrelated 2"]

        self.assertEqual(next_temp_channel_name(names, base="小隊call •"), "小隊call • 2")

    def test_mode_suffix_reserves_room_number(self):
        self.assertEqual(next_temp_channel_name(["REC • 1", "Park • 3"], base="小隊call •"), "小隊call • 2")

    def test_next_name_escapes_regex_characters_in_base(self) -> None:
        names = ["Team [A] 1", "Team [A] 2"]

        self.assertEqual(next_temp_channel_name(names, base="Team [A]"), "Team [A] 3")

    def test_limit_normalization_clamps_to_discord_range(self) -> None:
        self.assertEqual(normalize_limit(-5), 1)
        self.assertEqual(normalize_limit(150), 99)
        self.assertEqual(normalize_limit("8"), 8)
        self.assertEqual(normalize_limit("invalid", default=32), 32)

    def test_manual_limit_parser_rejects_non_integer(self) -> None:
        self.assertEqual(parse_manual_limit("12"), 12)
        self.assertIsNone(parse_manual_limit(""))
        self.assertIsNone(parse_manual_limit("many"))

    def test_seconds_are_rounded_up_for_user_message(self) -> None:
        self.assertEqual(format_seconds(0.1), "1 秒")
        self.assertEqual(format_seconds(60.1), "1 分 1 秒")

    def test_invalid_config_uses_safe_defaults(self) -> None:
        with patch.object(config, "TEMP_VC_EMPTY_SECONDS", "invalid"):
            self.assertEqual(get_timeout_seconds(), 120.0)
        with patch.object(config, "TEMP_VC_DEFAULT_USER_LIMIT", "invalid"):
            self.assertIsNone(get_auto_vc_user_limit())


if __name__ == "__main__":
    unittest.main()
