from __future__ import annotations

from types import ModuleType

import config


REQUIRED_POSITIVE_INT_SETTINGS: tuple[str, ...] = (
    "GUILD_ID",
    "VERIFIED_ROLE_ID",
    "WELCOME_CHANNEL_ID",
    "RULES_CHANNEL_ID",
    "GUIDE_CHANNEL_ID",
    "SUPPORT_CHANNEL_ID",
    "LOG_CHANNEL_ID",
)


def validate_config(settings: ModuleType | object = config) -> list[str]:
    """Return actionable warnings without preventing the bot from starting."""
    warnings: list[str] = []
    for name in REQUIRED_POSITIVE_INT_SETTINGS:
        value = getattr(settings, name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            warnings.append(f"{name} must be a positive integer Discord ID")

    helper_role_ids = getattr(settings, "HELPER_ROLE_IDS", [])
    if not isinstance(helper_role_ids, (list, tuple, set)):
        warnings.append("HELPER_ROLE_IDS must be a list, tuple, or set")
    elif any(not isinstance(role_id, int) or isinstance(role_id, bool) or role_id <= 0 for role_id in helper_role_ids):
        warnings.append("HELPER_ROLE_IDS contains an invalid Discord role ID")

    return warnings
