from __future__ import annotations

import logging
import os


DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def resolve_log_level(raw_level: str | None) -> int:
    level_name = (raw_level or DEFAULT_LOG_LEVEL).strip().upper()
    level = getattr(logging, level_name, None)
    return level if isinstance(level, int) else logging.INFO


def configure_logging() -> None:
    """Configure one consistent, environment-controlled runtime log format."""
    logging.basicConfig(
        level=resolve_log_level(os.getenv("LOG_LEVEL")),
        format=LOG_FORMAT,
    )
    logging.captureWarnings(True)
