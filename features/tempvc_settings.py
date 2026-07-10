from __future__ import annotations

import re
from collections.abc import Iterable

import config


def get_timeout_seconds() -> float:
    try:
        return float(getattr(config, "TEMP_VC_EMPTY_SECONDS", 120))
    except (TypeError, ValueError):
        return 120.0


def get_sweep_interval_seconds() -> float:
    try:
        return float(getattr(config, "TEMP_VC_SWEEP_SECONDS", 300))
    except (TypeError, ValueError):
        return 300.0


def get_name_prefixes() -> list[str]:
    return [get_temp_channel_base_name()]


def get_hub_channel_name() -> str:
    return str(getattr(config, "TEMP_VC_HUB_NAME", "開call")).strip() or "開call"


def get_temp_channel_base_name() -> str:
    return str(getattr(config, "TEMP_VC_PREFIX", "小隊call •")).strip() or "小隊call •"


def get_auto_vc_user_limit() -> int | None:
    value = getattr(config, "TEMP_VC_DEFAULT_USER_LIMIT", None)
    if value in (None, "", 0, "0"):
        return None

    try:
        return max(1, min(99, int(value)))
    except (TypeError, ValueError):
        return None


def get_vc_limit_user_cooldown_seconds() -> float:
    try:
        return float(getattr(config, "VC_LIMIT_USER_COOLDOWN_SECONDS", 30))
    except (TypeError, ValueError):
        return 30.0


def get_vc_limit_channel_cooldown_seconds() -> float:
    try:
        return float(getattr(config, "VC_LIMIT_CHANNEL_COOLDOWN_SECONDS", 30))
    except (TypeError, ValueError):
        return 30.0


def get_vc_limit_min() -> int:
    try:
        return max(1, int(getattr(config, "VC_LIMIT_MIN", 1)))
    except (TypeError, ValueError):
        return 1


def get_vc_limit_max() -> int:
    try:
        return min(99, max(get_vc_limit_min(), int(getattr(config, "VC_LIMIT_MAX", 99))))
    except (TypeError, ValueError):
        return 99


def normalize_limit(limit: int | str | None, *, default: int = 32) -> int:
    if limit in (None, "", 0, "0"):
        return default

    try:
        return max(1, min(99, int(limit)))
    except (TypeError, ValueError):
        return default


def parse_manual_limit(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def format_seconds(seconds: float) -> str:
    seconds_int = max(0, int(seconds + 0.999))
    minutes, sec = divmod(seconds_int, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


def next_temp_channel_name(existing_names: Iterable[str], *, base: str | None = None) -> str:
    normalized_base = (base or get_temp_channel_base_name()).strip()
    pattern = re.compile(rf"^{re.escape(normalized_base)}\s+(\d+)$")
    used_numbers: set[int] = set()

    for name in existing_names:
        match = pattern.fullmatch(name.strip())
        if match:
            used_numbers.add(int(match.group(1)))

    number = 1
    while number in used_numbers:
        number += 1
    return f"{normalized_base} {number}"
