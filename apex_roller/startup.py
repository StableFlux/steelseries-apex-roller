"""Manage a per-user Startup-folder shortcut for auto-launch on Windows login.

We only support this when running as a packaged exe (sys.frozen is set by
PyInstaller). In development, the toggle is disabled because launching a Python
script at login isn't useful for the end user.

We avoid pywin32 by shelling out to PowerShell's WScript.Shell COM helper to
write the .lnk file.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SHORTCUT_NAME = "Apex Roller"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def can_install_startup() -> bool:
    return is_frozen()


def current_exe() -> Path:
    """Path to the executable that should be relaunched at startup."""
    return Path(sys.executable)


def _startup_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return _startup_dir() / f"{SHORTCUT_NAME}.lnk"


def is_installed() -> bool:
    return shortcut_path().exists()


def install(target: Path | None = None) -> Path:
    target = target or current_exe()
    lnk = shortcut_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    # Use PowerShell + WScript.Shell COM so we don't need pywin32.
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{lnk}');"
        f"$s.TargetPath = '{target}';"
        f"$s.WorkingDirectory = '{target.parent}';"
        "$s.WindowStyle = 7;"
        "$s.Save();"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log.info("Startup shortcut installed at %s -> %s", lnk, target)
    return lnk


def uninstall() -> None:
    p = shortcut_path()
    if p.exists():
        p.unlink()
        log.info("Startup shortcut removed: %s", p)
