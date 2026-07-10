from __future__ import annotations

import unittest

from cogs.activity_reminder import _parse_time_hhmm, _parse_weekdays


class ActivityParsingTests(unittest.TestCase):
    def test_time_is_normalized(self) -> None:
        self.assertEqual(_parse_time_hhmm("9:05"), "09:05")

    def test_invalid_time_is_rejected(self) -> None:
        for value in ("24:00", "12:60", "9", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _parse_time_hhmm(value)

    def test_weekday_aliases_and_duplicates_are_normalized(self) -> None:
        self.assertEqual(_parse_weekdays("mon,週五,5,星期日"), [0, 4, 6])

    def test_weekday_range_can_wrap_across_sunday(self) -> None:
        self.assertEqual(_parse_weekdays("fri-mon"), [0, 4, 5, 6])

    def test_invalid_weekday_is_rejected(self) -> None:
        for value in ("0", "8", "funday", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _parse_weekdays(value)


if __name__ == "__main__":
    unittest.main()
