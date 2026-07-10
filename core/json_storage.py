from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("con9sole-bartender.storage.json")


def _corrupt_backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return path.with_suffix(path.suffix + f".corrupt.{timestamp}")


def load_json_object(
    path: str | Path,
    default_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Load a JSON object, rotating malformed content before using defaults."""
    source = Path(path)
    if not source.exists():
        return default_factory()

    try:
        raw = source.read_text(encoding="utf-8")
    except OSError:
        log.exception("Failed to read JSON state: path=%s", source)
        return default_factory()

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON state root must be an object")
        return parsed
    except (json.JSONDecodeError, ValueError):
        backup = _corrupt_backup_path(source)
        try:
            source.replace(backup)
            log.error("Rotated malformed JSON state: path=%s backup=%s", source, backup)
        except OSError:
            log.exception("Failed to rotate malformed JSON state: path=%s", source)
        return default_factory()


def atomic_write_json(path: str | Path, data: dict[str, Any]) -> None:
    """Durably replace a JSON file without exposing a partially written state."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)

        temp_path.replace(destination)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                log.warning("Failed to remove temporary JSON file: path=%s", temp_path)
