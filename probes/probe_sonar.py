"""
Probe 1: Sonar API.

Discovers the Sonar webServerAddress via coreProps.json -> GG /subApps,
reads current volumes, then performs a safe round-trip change on the
'media' channel: read -> nudge by +5% -> read -> restore -> read.

Run:
    python probes/probe_sonar.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CORE_PROPS = os.path.join(
    os.environ["ProgramData"],
    "SteelSeries",
    "SteelSeries Engine 3",
    "coreProps.json",
)
TARGET_CHANNEL = "media"
NUDGE = 0.05


def load_core_props() -> dict:
    with open(CORE_PROPS, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_sonar(gg_address: str) -> str:
    r = requests.get(f"https://{gg_address}/subApps", verify=False, timeout=5)
    r.raise_for_status()
    data = r.json()
    sonar = data["subApps"]["sonar"]
    for flag in ("isEnabled", "isReady", "isRunning"):
        if not sonar.get(flag):
            raise SystemExit(f"Sonar subApp not usable: {flag}=False")
    addr = sonar["metadata"]["webServerAddress"]
    if not addr:
        raise SystemExit("Sonar webServerAddress is empty")
    return addr


def get_mode(base: str) -> str:
    r = requests.get(f"{base}/mode/", timeout=5)
    r.raise_for_status()
    return r.json()


def get_volumes(base: str, mode: str) -> dict:
    path = "/volumeSettings/streamer" if mode == "stream" else "/volumeSettings/classic"
    r = requests.get(f"{base}{path}", timeout=5)
    r.raise_for_status()
    return r.json()


def read_channel_volume(volumes: dict, channel: str, mode: str) -> float:
    dev = volumes["devices"][channel]
    if mode == "stream":
        return dev["stream"]["streaming"]["volume"]
    return dev["classic"]["volume"]


def set_channel_volume(base: str, mode: str, channel: str, value: float) -> None:
    if mode == "stream":
        url = f"{base}/volumeSettings/streamer/streaming/{channel}/Volume/{json.dumps(value)}"
    else:
        url = f"{base}/volumeSettings/classic/{channel}/Volume/{json.dumps(value)}"
    r = requests.put(url, timeout=5)
    r.raise_for_status()


def main() -> int:
    props = load_core_props()
    gg_addr = props["ggEncryptedAddress"]
    print(f"[ok] coreProps.json read; ggEncryptedAddress = {gg_addr}")

    sonar_base = discover_sonar(gg_addr)
    print(f"[ok] Sonar webServerAddress = {sonar_base}")

    mode = get_mode(sonar_base)
    print(f"[ok] Sonar mode = {mode!r}")

    volumes = get_volumes(sonar_base, mode)
    print(f"[ok] GET volumes succeeded ({len(volumes['devices'])} channels)")
    for ch in volumes["devices"]:
        v = read_channel_volume(volumes, ch, mode)
        print(f"     {ch:12s} = {v:.3f}")

    original = read_channel_volume(volumes, TARGET_CHANNEL, mode)
    print(f"\n[test] target channel = {TARGET_CHANNEL!r}, current volume = {original:.3f}")

    target = max(0.0, min(1.0, original + NUDGE if original < 0.95 else original - NUDGE))
    print(f"[test] setting {TARGET_CHANNEL} -> {target:.3f}")
    set_channel_volume(sonar_base, mode, TARGET_CHANNEL, target)

    after = read_channel_volume(get_volumes(sonar_base, mode), TARGET_CHANNEL, mode)
    print(f"[test] readback after change = {after:.3f}")
    if abs(after - target) > 1e-3:
        print(f"[FAIL] expected {target:.3f}, got {after:.3f}")
        return 1

    print(f"[test] restoring {TARGET_CHANNEL} -> {original:.3f}")
    set_channel_volume(sonar_base, mode, TARGET_CHANNEL, original)
    restored = read_channel_volume(get_volumes(sonar_base, mode), TARGET_CHANNEL, mode)
    print(f"[test] readback after restore = {restored:.3f}")
    if abs(restored - original) > 1e-3:
        print(f"[FAIL] restore failed: expected {original:.3f}, got {restored:.3f}")
        return 1

    print("\n[PASS] Sonar discovery + read + set + restore all work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
