"""Standard per-user paths for config, logs, etc."""
from __future__ import annotations

import os
from pathlib import Path


def appdata_dir() -> Path:
    """Per-user data dir: %LocalAppData%\\ApexRoller."""
    base = os.environ.get("LocalAppData") or os.path.expanduser("~\\AppData\\Local")
    p = Path(base) / "ApexRoller"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    p = appdata_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return appdata_dir() / "config.json"
