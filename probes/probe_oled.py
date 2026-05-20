"""
Probe 2: Push a test string to the Apex Pro OLED via GameSense.

Flow:
  1. POST /game_metadata           - register a game
  2. POST /bind_game_event         - declare a TEXT event with screened handler
  3. POST /game_event (x3)         - send three frames so visible change is unambiguous
  4. POST /remove_game             - clean up registration

Run:
    python probes/probe_oled.py

Watch the keyboard OLED. You should see three lines change every ~1.5s,
ending on the final 'Probe OK 3/3' frame, then the display returns to normal
after this script exits.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

CORE_PROPS = os.path.join(
    os.environ["ProgramData"],
    "SteelSeries",
    "SteelSeries Engine 3",
    "coreProps.json",
)
GAME = "APEX_ROLLER_PROBE"
EVENT = "TEXT"


def gamesense_base() -> str:
    with open(CORE_PROPS, "r", encoding="utf-8") as f:
        props = json.load(f)
    return f"http://{props['address']}"


def post(base: str, path: str, body: dict) -> dict:
    r = requests.post(f"{base}{path}", json=body, timeout=5)
    if r.status_code >= 400:
        raise SystemExit(f"POST {path} -> HTTP {r.status_code}: {r.text}")
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


def main() -> int:
    base = gamesense_base()
    print(f"[ok] GameSense REST = {base}")

    print("[step] register game")
    post(base, "/game_metadata", {
        "game": GAME,
        "game_display_name": "Apex Roller Probe",
        "developer": "local-probe",
    })

    print("[step] bind TEXT event with screened handler")
    post(base, "/bind_game_event", {
        "game": GAME,
        "event": EVENT,
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

    frames = [
        {"line1": "Apex Roller", "line2": "Probe OK 1/3"},
        {"line1": "Apex Roller", "line2": "Probe OK 2/3"},
        {"line1": "Apex Roller", "line2": "Probe OK 3/3"},
    ]
    for i, f in enumerate(frames, 1):
        print(f"[step] game_event {i}/3: {f}  (showing for 4s)")
        post(base, "/game_event", {"game": GAME, "event": EVENT, "data": {"frame": f}})
        time.sleep(4)

    print("[step] holding final frame for 6s so you can see it")
    time.sleep(6)

    print("[step] remove game registration")
    post(base, "/remove_game", {"game": GAME})

    print("\n[PASS-IF] you saw 'Probe OK 1/3' -> '2/3' -> '3/3' on the keyboard OLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
