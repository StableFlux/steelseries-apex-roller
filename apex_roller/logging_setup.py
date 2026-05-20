"""Logging configuration. File-based with rotation, plus optional console echo."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_dir

LOG_FILE_NAME = "apex-roller.log"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup(level: int = logging.INFO, console: bool = True) -> logging.Logger:
    root = logging.getLogger()
    # Idempotent: clear any existing handlers so re-init doesn't double-log.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    fmt = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)

    fh = RotatingFileHandler(
        log_dir() / LOG_FILE_NAME,
        maxBytes=512 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console and sys.stdout is not None:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # urllib3 is too chatty at INFO when we hit the GG/Sonar APIs repeatedly.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return root
