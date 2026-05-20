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


def main() -> int:
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
