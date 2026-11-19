"""Bounded, external diagnostic logging for the desktop application."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


generation_logger = logging.getLogger("jpg_boundary.generation")


def configure_generation_log(directory: Path | None = None) -> Path | None:
    """Initialize at application startup, not while importing core/GUI modules."""
    if directory is None:
        directory = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "JpgBoundaryToKmz"
    try:
        path = (directory / "generation.log").resolve()
        for handler in generation_logger.handlers:
            if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path:
                return path
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        # A logging failure must not prevent startup or exporting; Details is
        # still available for the current generation in the app.
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s\n"))
    generation_logger.addHandler(handler)
    generation_logger.setLevel(logging.INFO)
    generation_logger.propagate = False
    return path
