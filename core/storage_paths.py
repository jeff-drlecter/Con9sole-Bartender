from __future__ import annotations

import os
from pathlib import Path


PROJECT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def resolve_data_dir(raw_path: str | None, *, fallback: Path = PROJECT_DATA_DIR) -> Path:
    candidate = Path(raw_path or "/data")
    return candidate if candidate.exists() else fallback


DATA_DIR = resolve_data_dir(os.getenv("DRINK_DATA_DIR"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATS_DB = Path(os.getenv("STATS_DB_PATH", str(DATA_DIR / "community_stats.sqlite3")))
STATS_DB.parent.mkdir(parents=True, exist_ok=True)
DRINK_STATE_PATH = Path(os.getenv("DRINK_STATE_PATH", str(DATA_DIR / "drink_state.json")))
