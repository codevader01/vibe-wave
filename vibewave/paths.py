"""Application data locations. Library data never lives inside the install folder."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("VIBEWAVE_DATA")
    if override:
        root = Path(override)
    else:
        base = os.environ.get("APPDATA")
        root = Path(base) / "VibeWave" if base else Path.home() / ".vibewave"
    root.mkdir(parents=True, exist_ok=True)
    (root / "artwork").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    return root


def db_path() -> Path:
    return data_dir() / "library.db"


def artwork_dir() -> Path:
    return data_dir() / "artwork"


def log_path() -> Path:
    return data_dir() / "logs" / "vibewave.log"
