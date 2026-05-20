"""Entry point: `python -m apex_roller` (dev) or the packaged .exe."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

from . import logging_setup
from .app import App

log = logging.getLogger("apex_roller.main")


def _construct_app_with_wait(stop_event: threading.Event) -> App | None:
    """Wait for GG/Sonar to be reachable, then construct App. Returns None if cancelled."""
    delay = 1.0
    while not stop_event.is_set():
        try:
            return App()
        except Exception as e:
            log.warning("startup failed (%s); will retry in %.1fs (is SteelSeries GG running with Sonar?)",
                        e, delay)
            if stop_event.wait(delay):
                return None
            delay = min(delay * 1.5, 30.0)
    return None


def _run_console(app: App, timeout: float, stop_event: threading.Event) -> None:
    """Run the hook on the main thread; no tray UI."""
    if timeout > 0:
        def _stop():
            time.sleep(timeout)
            log.info("--timeout %.1fs reached", timeout)
            stop_event.set()
            app.shutdown()
        threading.Thread(target=_stop, name="timeout", daemon=True).start()
    app.run()


def _run_tray(app: App, timeout: float, stop_event: threading.Event) -> None:
    """Tray on main thread, hook on worker thread."""
    from .tray import Tray  # imported lazily so dev/console mode doesn't need Pillow

    hook_thread = threading.Thread(target=app.run, name="hook-pump", daemon=True)
    hook_thread.start()

    tray = Tray(app)

    if timeout > 0:
        def _stop():
            time.sleep(timeout)
            log.info("--timeout %.1fs reached", timeout)
            stop_event.set()
            app.shutdown()
            tray.icon.stop()
        threading.Thread(target=_stop, name="timeout", daemon=True).start()

    try:
        tray.run()
    except KeyboardInterrupt:
        app.shutdown()
        tray.icon.stop()
    hook_thread.join(timeout=3)


def _cleanup_and_exit() -> int:
    """Deregister from SteelSeries GameSense, wipe per-user state, and exit.
    Called by the installer's UninstallRun step. Best-effort: GG may not be
    running, files may already be gone.

    NOTE: must not touch sys.stdout/sys.stderr or anything that does -- under
    --noconsole/runhidden both are None and any write attempt crashes.
    """
    # Diagnostic marker so we can see what the uninstaller-spawned cleanup
    # actually saw. Written to %TEMP%; user-readable post-uninstall.
    _marker = None
    try:
        import os, time
        _marker = os.path.join(os.environ.get("TEMP", "C:\\"), "apex-cleanup-marker.txt")
        with open(_marker, "a", encoding="utf-8") as f:
            f.write(f"\n=== cleanup START {time.ctime()} pid={os.getpid()} ===\n")
            f.write(f"  LocalAppData={os.environ.get('LocalAppData')!r}\n")
            f.write(f"  USERPROFILE={os.environ.get('USERPROFILE')!r}\n")
    except Exception:
        pass

    # 1. Actively kill any other apex-roller.exe processes. Inno's
    #    `taskkill /IM` in [UninstallRun] has been observed to no-op against
    #    a running PyInstaller --onefile tray app (the image-name match
    #    sometimes silently fails), so we list PIDs and kill by PID, which
    #    is unambiguous.
    try:
        import os, subprocess, time
        my_pid = os.getpid()
        # Up to ~20s of "kill what's there + recheck" cycles.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["tasklist", "/fi", "imagename eq apex-roller.exe", "/fo", "csv", "/nh"],
                    capture_output=True, text=True, timeout=2,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                pids = []
                for line in result.stdout.splitlines():
                    parts = line.split('","')
                    if len(parts) >= 2:
                        try:
                            pids.append(int(parts[1].strip('"')))
                        except ValueError:
                            pass
                others = [p for p in pids if p != my_pid]
                if _marker:
                    try:
                        with open(_marker, "a", encoding="utf-8") as f:
                            f.write(f"  tasklist pids={pids} others={others}\n")
                    except Exception:
                        pass
                if not others:
                    break
                # Force-kill each leftover apex-roller.exe by PID.
                # NOTE: deliberately NOT using /T -- killing a tree from this
                # context has been observed to also terminate the cleanup
                # process itself, suggesting an unexpected ancestry.
                for pid in others:
                    try:
                        kr = subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, text=True, timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if _marker:
                            try:
                                with open(_marker, "a", encoding="utf-8") as f:
                                    f.write(f"  taskkill /PID {pid} rc={kr.returncode} out={kr.stdout.strip()!r} err={kr.stderr.strip()!r}\n")
                            except Exception:
                                pass
                    except Exception as e:
                        if _marker:
                            try:
                                with open(_marker, "a", encoding="utf-8") as f:
                                    f.write(f"  taskkill /PID {pid} raised: {e}\n")
                            except Exception:
                                pass
            except Exception as e:
                if _marker:
                    try:
                        with open(_marker, "a", encoding="utf-8") as f:
                            f.write(f"  tasklist raised: {e}\n")
                    except Exception:
                        pass
                break
            time.sleep(1.0)
        # Extra beat for the kernel to flush released handles after the kill.
        time.sleep(2.0)
    except Exception:
        pass

    # 2. Deregister 'Apex Roller' from GameSense so it doesn't linger in the
    #    Apps list after uninstall.
    try:
        from . import coreprops
        from .gamesense import GameSense
        props = coreprops.load()
        gs = GameSense(props.gamesense_address)
        gs.shutdown()
    except Exception:
        pass

    # 3. Wipe %LocalAppData%\ApexRoller (config + logs).
    #    Don't trust `Path.exists()` after a recent process kill -- the dir
    #    can be in a "delete pending" state where exists() returns False but
    #    files actually persist. Always attempt rmtree at least once.
    try:
        import os, shutil, time
        from pathlib import Path
        base = os.environ.get("LocalAppData") or os.path.expanduser("~\\AppData\\Local")
        appdata = Path(base) / "ApexRoller"
        if _marker:
            try:
                with open(_marker, "a", encoding="utf-8") as f:
                    f.write(f"  pre-rmtree appdata = {appdata} exists={appdata.exists()}\n")
            except Exception:
                pass
        # Always run rmtree at least once.
        shutil.rmtree(appdata, ignore_errors=True)
        deadline = time.monotonic() + 30.0
        attempt = 1
        while time.monotonic() < deadline:
            try:
                contents = list(appdata.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                contents = []
            except OSError:
                contents = ["<unreadable>"]
            if not contents:
                if _marker:
                    try:
                        with open(_marker, "a", encoding="utf-8") as f:
                            f.write(f"  rmtree clean after {attempt} attempt(s)\n")
                    except Exception:
                        pass
                break
            time.sleep(1.0)
            attempt += 1
            shutil.rmtree(appdata, ignore_errors=True)
        # If still hanging on, schedule deletion on next reboot.
        try:
            if list(appdata.iterdir()):
                import ctypes
                MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
                for sub in sorted(appdata.rglob("*"), key=lambda p: -len(str(p))):
                    ctypes.windll.kernel32.MoveFileExW(str(sub), None, MOVEFILE_DELAY_UNTIL_REBOOT)
                ctypes.windll.kernel32.MoveFileExW(str(appdata), None, MOVEFILE_DELAY_UNTIL_REBOOT)
                if _marker:
                    try:
                        with open(_marker, "a", encoding="utf-8") as f:
                            f.write(f"  scheduled reboot deletion of stragglers\n")
                    except Exception:
                        pass
        except (FileNotFoundError, NotADirectoryError, OSError):
            pass
    except Exception:
        pass

    # 4. Final settle wait. Once we return, the installer will try to delete
    #    files in {app}. Give Windows enough time to release any kernel
    #    objects associated with the processes we just killed, so the
    #    .exe in the install dir isn't still "in use" from the OS's view.
    try:
        import time
        time.sleep(5.0)
    except Exception:
        pass

    if _marker:
        try:
            import time
            with open(_marker, "a", encoding="utf-8") as f:
                f.write(f"=== cleanup END {time.ctime()} ===\n")
        except Exception:
            pass
    return 0


def main() -> int:
    # Detect --cleanup BEFORE argparse. The installer runs us via
    # `Flags: runhidden`, so the PyInstaller --noconsole exe has sys.stdout
    # and sys.stderr set to None. Any argparse error path would call
    # sys.stderr.write(...) and crash with AttributeError.
    if "--cleanup" in sys.argv[1:]:
        return _cleanup_and_exit()

    # Belt-and-braces: any other invocation that lands us here without a
    # console (e.g. a future installer command we forget to handle) should
    # also not crash on argparse diagnostics.
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")

    frozen = bool(getattr(sys, "frozen", False))

    ap = argparse.ArgumentParser(prog="apex_roller")
    ap.add_argument("--timeout", type=float, default=0,
                    help="auto-exit after N seconds (testing aid)")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    # Default UI: tray when packaged, console when run from source (easier dev loop).
    ap.add_argument("--tray", dest="tray", action="store_true", default=frozen,
                    help="run with system tray UI (default when packaged)")
    ap.add_argument("--no-tray", dest="tray", action="store_false",
                    help="run in console mode (default when run from source)")
    ap.add_argument("--cleanup", action="store_true",
                    help="(used by the installer's uninstall step) deregister from GameSense and exit")
    args = ap.parse_args()

    # When packaged with --noconsole there's no stdout; skip the console log handler.
    use_console_log = not frozen
    logging_setup.setup(
        level=logging.DEBUG if args.debug else logging.INFO,
        console=use_console_log,
    )
    log.info("apex-roller starting (pid=%d, frozen=%s, tray=%s)", os.getpid(), frozen, args.tray)

    stop_event = threading.Event()
    app = _construct_app_with_wait(stop_event)
    if app is None:
        log.info("startup cancelled before GG became available")
        return 0

    def on_sigint(*_a):
        log.info("SIGINT received")
        stop_event.set()
        app.shutdown()

    signal.signal(signal.SIGINT, on_sigint)

    try:
        if args.tray:
            _run_tray(app, args.timeout, stop_event)
        else:
            _run_console(app, args.timeout, stop_event)
    except KeyboardInterrupt:
        app.shutdown()
    log.info("apex-roller exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
