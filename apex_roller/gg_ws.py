"""GG core WebSocket client.

Sonar's GG UI updates by listening to broadcasts on its own /sock endpoint.
Those broadcasts only fire when Sonar's *action handler* path runs (not when
the REST controllers run directly). The action handler is triggered when GG
core relays a `EVENT_SUB_APP_ACTIONS_DATA_CHANGED` event from any Service-group
WebSocket client to all other Service-group clients (Sonar is one of them).

So to make the Sonar GG UI redraw live: connect to GG core's Service-group
WebSocket at `wss://<ggEncryptedAddress>/eventing` and emit one
`EVENT_SUB_APP_ACTIONS_DATA_CHANGED` per change with the corresponding action
name and a percentage value.

See [[sonar-ui-sync-internals]] memory for the full decompilation trail.
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import uuid
from typing import Optional

import websocket  # websocket-client (NOT 'websockets')

log = logging.getLogger(__name__)

EVENT_NAME = "EVENT_SUB_APP_ACTIONS_DATA_CHANGED"
SUB_APP_NAME = "sonar"

# Action names from decompiled VolumeActionProvider.CreateActions().
# Each is a FiniteRange action whose value is a percentage 0..100.
# Index by (slider, channel_key) for streamer mode.
STREAMER_ACTIONS: dict[tuple[str, str], str] = {
    ("monitoring", "master"):     "MONITOR_MASTER_VOLUME",
    ("streaming",  "master"):     "STREAMING_MASTER_VOLUME",
    ("monitoring", "game"):       "MONITOR_GAME_VOLUME",
    ("streaming",  "game"):       "STREAMING_GAME_VOLUME",
    ("monitoring", "chatRender"): "MONITOR_CHAT_VOLUME",
    ("streaming",  "chatRender"): "STREAMING_CHAT_VOLUME",
    ("monitoring", "media"):      "MONITOR_MEDIA_VOLUME",
    ("streaming",  "media"):      "STREAMING_MEDIA_VOLUME",
    ("monitoring", "aux"):        "MONITOR_AUX_VOLUME",
    ("streaming",  "aux"):        "STREAMING_AUX_VOLUME",
}

# Classic-mode VolumeActionProvider only exposes MIC_MUTE as a typed action, so
# we don't have a direct UI-sync action for classic master/game/etc. Live UI
# sync in classic mode would need a different path; out of scope for v0.1.


class GGEventClient:
    """Maintains a wss connection to GG core's /eventing endpoint and fires
    `EVENT_SUB_APP_ACTIONS_DATA_CHANGED` messages on demand."""

    def __init__(self, gg_encrypted_address: str, *, reconnect_delay: float = 1.0):
        self._url = f"wss://{gg_encrypted_address}/eventing"
        self._ws: Optional[websocket.WebSocket] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reconnect_delay = reconnect_delay

    def _ensure_open(self) -> None:
        if self._ws is not None and self._ws.connected:
            return
        # GG core's cert is self-signed; we already trust the local socket here.
        ws = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
        ws.connect(self._url, timeout=5)
        self._ws = ws
        log.info("connected to GG eventing socket: %s", self._url)

    def send_action(self, action_name: str, value_pct: float) -> None:
        """Fire an EVENT_SUB_APP_ACTIONS_DATA_CHANGED event. `value_pct` is 0..100."""
        msg = {
            "event": EVENT_NAME,
            "data": {
                "SubAppName": SUB_APP_NAME,
                "Id": str(uuid.UUID(int=0)),  # handler looks up by ActionName, Id is unused
                "ActionName": action_name,
                "Value": float(value_pct),
            },
        }
        payload = json.dumps(msg)
        with self._lock:
            try:
                self._ensure_open()
                assert self._ws is not None
                self._ws.send(payload)
            except Exception as first:
                log.warning("GG /eventing send failed (%s); reconnecting once", first)
                self._close_locked()
                try:
                    self._ensure_open()
                    assert self._ws is not None
                    self._ws.send(payload)
                except Exception:
                    log.exception("GG /eventing reconnect failed; UI sync will be missed for this event")

    def _close_locked(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._close_locked()
