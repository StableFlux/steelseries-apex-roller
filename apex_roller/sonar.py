"""Sonar HTTP client. Endpoint contract validated 2026-05-20.

Channels accepted by Sonar (we use a subset): master, game, chatRender,
chatCapture, media, aux. In the JSON returned by GET /volumeSettings, `master`
lives under top-level `masters` while the rest live under `devices[channel]`;
the PUT URL pattern is uniform across all of them.

Streamer-mode sliders ('streaming' and 'monitoring') are independent
user-facing controls and must NEVER be set together. Callers pass `slider`
explicitly in streamer mode.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

import requests
import urllib3

from . import coreprops

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

Mode = Literal["stream", "classic"]
Slider = Literal["streaming", "monitoring"]


class SonarError(Exception):
    pass


class Sonar:
    def __init__(self, gg_encrypted_address: str | None = None, *, timeout: float = 5.0):
        self.timeout = timeout
        self._gg_base = ""
        self.base_url: str = ""
        self.mode: Mode = "classic"
        if gg_encrypted_address is None:
            self.reconnect()
        else:
            self._set_gg_address(gg_encrypted_address)
            self._discover()
            self.refresh_mode()

    def _set_gg_address(self, gg_encrypted_address: str) -> None:
        self._gg_base = f"https://{gg_encrypted_address}"

    def reconnect(self) -> None:
        """Re-read coreProps.json and re-discover. Used after a transient failure
        (e.g. GG restart rotated the Sonar port)."""
        props = coreprops.load()
        self._set_gg_address(props.gg_encrypted_address)
        self._discover()
        self.refresh_mode()

    def _discover(self) -> None:
        r = requests.get(f"{self._gg_base}/subApps", verify=False, timeout=self.timeout)
        r.raise_for_status()
        sub = r.json().get("subApps", {}).get("sonar")
        if sub is None:
            raise SonarError("Sonar sub-app not present in /subApps response")
        for flag in ("isEnabled", "isReady", "isRunning"):
            if not sub.get(flag):
                raise SonarError(f"Sonar sub-app reports {flag}=False")
        addr = sub.get("metadata", {}).get("webServerAddress")
        if not addr:
            raise SonarError("Sonar webServerAddress is empty")
        self.base_url = addr

    def refresh_mode(self) -> Mode:
        r = requests.get(f"{self.base_url}/mode/", timeout=self.timeout)
        r.raise_for_status()
        self.mode = r.json()
        return self.mode

    def _volume_path(self) -> str:
        return "/volumeSettings/streamer" if self.mode == "stream" else "/volumeSettings/classic"

    def get_volumes(self) -> dict:
        r = requests.get(f"{self.base_url}{self._volume_path()}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_volume(self, channel: str, slider: Slider | None = None) -> float:
        return self._with_reconnect(lambda: self._get_volume(channel, slider))

    def set_volume(self, channel: str, value: float, slider: Slider | None = None) -> float:
        value = max(0.0, min(1.0, float(value)))
        return self._with_reconnect(lambda: self._set_volume(channel, value, slider))

    def _get_volume(self, channel: str, slider: Slider | None) -> float:
        data = self.get_volumes()
        node = data["masters"] if channel == "master" else data["devices"][channel]
        if self.mode == "stream":
            if slider is None:
                raise SonarError("slider is required in streamer mode")
            return float(node["stream"][slider]["volume"])
        return float(node["classic"]["volume"])

    def _set_volume(self, channel: str, value: float, slider: Slider | None) -> float:
        encoded = json.dumps(value)
        if self.mode == "stream":
            if slider is None:
                raise SonarError("slider is required in streamer mode")
            url = f"{self.base_url}/volumeSettings/streamer/{slider}/{channel}/Volume/{encoded}"
        else:
            url = f"{self.base_url}/volumeSettings/classic/{channel}/Volume/{encoded}"
        r = requests.put(url, timeout=self.timeout)
        r.raise_for_status()
        return value

    def _with_reconnect(self, fn):
        try:
            return fn()
        except Exception as first:
            log.warning("Sonar call failed (%s); attempting one reconnect", first)
            self.reconnect()
            return fn()
