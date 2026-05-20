"""GameSense REST client for the screened (OLED) handler."""
from __future__ import annotations

import logging
import threading

import requests

from . import coreprops

log = logging.getLogger(__name__)


class GameSenseError(Exception):
    pass


class GameSense:
    def __init__(
        self,
        address: str | None = None,
        *,
        game: str = "APEX_ROLLER",
        display_name: str = "Apex Roller",
        developer: str = "local",
        event: str = "DISPLAY",
        timeout: float = 5.0,
    ):
        self.base = ""
        self.game = game
        self.display_name = display_name
        self.developer = developer
        self.event = event
        self.timeout = timeout
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self._registered = False
        if address is None:
            self.reconnect()
        else:
            self.base = f"http://{address}"

    def _post(self, path: str, body: dict) -> None:
        r = requests.post(f"{self.base}{path}", json=body, timeout=self.timeout)
        if r.status_code >= 400:
            raise GameSenseError(f"POST {path} -> {r.status_code}: {r.text}")

    def register(self) -> None:
        self._post("/game_metadata", {
            "game": self.game,
            "game_display_name": self.display_name,
            "developer": self.developer,
        })
        self._post("/bind_game_event", {
            "game": self.game,
            "event": self.event,
            "value_optional": True,
            "handlers": [{
                "device-type": "screened",
                "mode": "screen",
                "zone": "one",
                "datas": [{
                    "lines": [
                        {"has-text": True, "context-frame-key": "line1"},
                        {"has-text": True, "context-frame-key": "line2"},
                    ],
                }],
            }],
        })
        self._registered = True

    def reconnect(self) -> None:
        """Re-read coreProps for a fresh GameSense address, then re-register."""
        props = coreprops.load()
        self.base = f"http://{props.gamesense_address}"
        self._registered = False
        self.register()

    def show(self, line1: str, line2: str) -> None:
        body = {
            "game": self.game,
            "event": self.event,
            "data": {"frame": {"line1": line1, "line2": line2}},
        }
        try:
            self._post("/game_event", body)
        except Exception as first:
            log.warning("GameSense show failed (%s); attempting one reconnect", first)
            self.reconnect()
            self._post("/game_event", body)

    def start_heartbeat(self, interval: float = 10.0) -> None:
        def loop():
            while not self._hb_stop.wait(interval):
                try:
                    self._post("/game_heartbeat", {"game": self.game})
                except Exception:
                    # Heartbeat failures are common during GG restarts; the next
                    # user-driven show() will reconnect, so we just keep going.
                    pass
        self._hb_thread = threading.Thread(target=loop, name="gamesense-heartbeat", daemon=True)
        self._hb_thread.start()

    def shutdown(self) -> None:
        self._hb_stop.set()
        try:
            self._post("/remove_game", {"game": self.game})
        except Exception:
            pass
