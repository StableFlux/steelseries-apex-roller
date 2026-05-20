"""Persisted user settings (cycle inclusion toggles, etc.)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields

from .paths import config_path

log = logging.getLogger(__name__)


@dataclass
class Config:
    # When False (default), the cycle skips the Master channel and only adjusts
    # Game / Chat / Media / Aux. Most users want per-channel control and leave
    # master alone.
    include_master: bool = False

    # When False (default), each channel in the cycle has only its monitoring
    # slider (what the user hears locally). When True, each channel takes two
    # positions: monitoring first, then streaming -- giving independent control
    # of the broadcast feed.
    include_streaming: bool = False

    @classmethod
    def load(cls) -> "Config":
        p = config_path()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            log.exception("config read failed, using defaults")
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def save(self) -> None:
        try:
            config_path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            log.exception("config save failed")
