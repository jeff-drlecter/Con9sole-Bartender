from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DrinkState:
    version: int = 1
    # discord user id -> unix timestamp (utc)
    cooldowns: dict[str, float] = field(default_factory=dict)
    # discord user id -> recent drink keys (last N)
    recent_drinks: dict[str, list[str]] = field(default_factory=dict)
    # discord user id -> stats counters
    stats: dict[str, dict[str, int]] = field(default_factory=dict)
    # discord user id -> owned drink keys
    collections: dict[str, list[str]] = field(default_factory=dict)


def _default_stats() -> dict[str, int]:
    return {
        "total": 0,
        "gift": 0,
        "rare": 0,
        "legendary": 0,
    }


def _is_corrupt_json(path: Path) -> bool:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return True

    try:
        json.loads(raw)
        return False
    except Exception:
        return True


def _get_safe_path() -> Path:
    raw = os.getenv("DRINK_STATE_PATH", "data/drink_state.json")
    p = Path(raw)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # last-resort fallback
        pass
    return p


def _load_state_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Attempt to detect corrupt JSON and rotate
        try:
            if _is_corrupt_json(path):
                suffix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                backup = path.with_suffix(path.suffix + f".corrupt.{suffix}")
                try:
                    shutil.move(str(path), str(backup))
                except Exception:
                    pass
        finally:
            return None


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp_dir = path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(tmp_dir),
            prefix=path.name,
            suffix=".tmp",
            encoding="utf-8",
        ) as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
            tmp = Path(fh.name)

        tmp.replace(path)
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


class DrinkStateStore:
    """Simple persisted store for Drink cog.

    Reload-safe: new imports re-load from JSON.
    """

    def __init__(self, path: Path):
        self.path = path
        loaded = _load_state_file(path)

        if not loaded:
            self.state = DrinkState()
        else:
            # tolerant upgrades/downgrades
            s = DrinkState()
            s.version = int(loaded.get("version", 1))
            s.cooldowns = {str(k): float(v) for k, v in loaded.get("cooldowns", {}).items()}
            s.recent_drinks = {str(k): list(v) for k, v in loaded.get("recent_drinks", {}).items()}
            s.stats = {}
            for k, v in loaded.get("stats", {}).items():
                if isinstance(v, dict):
                    s.stats[str(k)] = {
                        "total": int(v.get("total", 0)),
                        "gift": int(v.get("gift", 0)),
                        "rare": int(v.get("rare", 0)),
                        "legendary": int(v.get("legendary", 0)),
                    }
            s.collections = {str(k): list(v) for k, v in loaded.get("collections", {}).items()}
            self.state = s

    @classmethod
    def from_env(cls) -> "DrinkStateStore":
        return cls(_get_safe_path())

    def save(self) -> None:
        _atomic_write(self.path, asdict(self.state))

    def now_ts(self) -> float:
        return time.time()

    def get_stats(self, user_id: int) -> dict[str, int]:
        sid = str(user_id)
        if sid not in self.state.stats:
            self.state.stats[sid] = _default_stats()
        return self.state.stats[sid]

    def get_recent(self, user_id: int) -> list[str]:
        sid = str(user_id)
        if sid not in self.state.recent_drinks:
            self.state.recent_drinks[sid] = []
        return self.state.recent_drinks[sid]

    def get_collection(self, user_id: int) -> list[str]:
        sid = str(user_id)
        if sid not in self.state.collections:
            self.state.collections[sid] = []
        return self.state.collections[sid]

    def get_cooldown_ts(self, user_id: int) -> float:
        sid = str(user_id)
        return float(self.state.cooldowns.get(sid, 0.0))

    def set_cooldown_ts(self, user_id: int, ts: float) -> None:
        self.state.cooldowns[str(user_id)] = float(ts)
