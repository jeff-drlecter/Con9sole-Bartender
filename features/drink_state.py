from __future__ import annotations

import atexit
import logging
import time

from data.drink_data import DRINK_COOLDOWN_SECONDS
from core.json_storage import atomic_write_json, load_json_object
from features.drink_storage import DATA_DIR

log = logging.getLogger("con9sole-bartender.drink.state")

DRINK_STATE_PATH = DATA_DIR / "drink_state.json"


def _default_drink_state() -> dict[str, object]:
    return {
        "version": 2,
        "cooldowns": {},
        "gift_cooldowns": {},
        "recent_drinks": {},
    }


def _load_drink_state() -> dict[str, object]:
    raw = load_json_object(DRINK_STATE_PATH, _default_drink_state)
    raw.setdefault("version", 2)
    raw.setdefault("cooldowns", {})
    raw.setdefault("gift_cooldowns", {})
    raw.setdefault("recent_drinks", {})
    return raw


_DRINK_STATE: dict[str, object] = _load_drink_state()


def state_cooldowns() -> dict[str, float]:
    data = _DRINK_STATE.setdefault("cooldowns", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["cooldowns"] = data
    return data  # type: ignore[return-value]


def state_gift_cooldowns() -> dict[str, float]:
    data = _DRINK_STATE.setdefault("gift_cooldowns", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["gift_cooldowns"] = data
    return data  # type: ignore[return-value]


def state_recent_drinks() -> dict[str, list[str]]:
    data = _DRINK_STATE.setdefault("recent_drinks", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["recent_drinks"] = data
    return data  # type: ignore[return-value]


def save_drink_state() -> None:
    try:
        atomic_write_json(DRINK_STATE_PATH, _DRINK_STATE)
    except Exception:
        log.exception("Failed to persist drink state: path=%s", DRINK_STATE_PATH)


DRINK_USER_COOLDOWNS: dict[int, float] = {
    int(user_id): float(ts)
    for user_id, ts in state_cooldowns().items()
    if str(user_id).isdigit()
}

GIFT_DRINK_USER_COOLDOWNS: dict[int, float] = {
    int(user_id): float(ts)
    for user_id, ts in state_gift_cooldowns().items()
    if str(user_id).isdigit()
}

atexit.register(save_drink_state)


def get_drink_retry_after(user_id: int) -> float:
    last_used = DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def get_gift_drink_retry_after(user_id: int) -> float:
    last_used = GIFT_DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def has_drink_cooldown(user_id: int) -> bool:
    return get_drink_retry_after(user_id) > 0


def has_gift_drink_cooldown(user_id: int) -> bool:
    return get_gift_drink_retry_after(user_id) > 0


def touch_drink_cooldown(user_id: int) -> None:
    ts = time.time()
    DRINK_USER_COOLDOWNS[user_id] = ts
    state_cooldowns()[str(user_id)] = ts
    save_drink_state()


def touch_gift_drink_cooldown(user_id: int) -> None:
    ts = time.time()
    GIFT_DRINK_USER_COOLDOWNS[user_id] = ts
    state_gift_cooldowns()[str(user_id)] = ts
    save_drink_state()


def clear_drink_cooldown(user_id: int) -> None:
    DRINK_USER_COOLDOWNS.pop(user_id, None)
    state_cooldowns().pop(str(user_id), None)
    save_drink_state()


def clear_gift_drink_cooldown(user_id: int) -> None:
    GIFT_DRINK_USER_COOLDOWNS.pop(user_id, None)
    state_gift_cooldowns().pop(str(user_id), None)
    save_drink_state()


def load_recent_draw_map() -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for raw_user_id, drinks in state_recent_drinks().items():
        try:
            user_id = int(raw_user_id)
        except Exception:
            continue
        if isinstance(drinks, list):
            result[user_id] = [str(item) for item in drinks]
    return result


def save_recent_draws(user_id: int, drinks: list[str]) -> None:
    state_recent_drinks()[str(user_id)] = list(drinks)
    save_drink_state()
