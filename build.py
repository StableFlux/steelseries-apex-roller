"""Build apex-roller.exe via PyInstaller. Run from project root: `python build.py`."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def main() -> int:
    # Clean prior build artifacts so we don't ship stale bytes.
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
    for s in ROOT.glob("*.spec"):
        s.unlink()

    icon = ROOT / "apex_roller" / "assets" / "apex-roller.ico"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", "apex-roller",
        "--icon", str(icon),
        # Bundle the .ico so tray.py can load it at runtime (PyInstaller --onefile
        # extracts data files into sys._MEIPASS at startup).
        "--add-data", f"{icon}{os.pathsep}apex_roller/assets",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT),
        "--noconfirm",
        # pystray's Windows backend isn't auto-detected by PyInstaller's analysis.
        "--collect-submodules", "pystray",
        str(ROOT / "launcher.py"),
    ]
    print(">>", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / "apex-roller.exe"
    if not exe.exists():
        print("ERROR: expected output not found:", exe)
        return 1
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\nBuilt {exe} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
