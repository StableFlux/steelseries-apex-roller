"""Probe: send an EVENT_SUB_APP_ACTIONS_DATA_CHANGED event to GG core's
/eventing WebSocket and confirm the Sonar UI redraws live.

Reads the GG encrypted address from coreProps.json, connects to
wss://<gg>/eventing, and sends three Master-Monitoring volume changes:
40 -> 60 -> 50. Open the Sonar tab in SteelSeries GG and watch the
"Monitor Master" slider during this run; it should jump in real time.

Run:
    python probes/probe_gg_eventing.py
"""
from __future__ import annotations

import json
import os
import ssl
import time
import uuid

import websocket

CORE_PROPS = os.path.join(
    os.environ["ProgramData"],
    "SteelSeries", "SteelSeries Engine 3", "coreProps.json",
)


def main() -> int:
    with open(CORE_PROPS, "r", encoding="utf-8") as f:
        props = json.load(f)
    url = f"wss://{props['ggEncryptedAddress']}/eventing"
    print(f"[ok] connecting to {url}")

    ws = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
    ws.connect(url, timeout=5)
    print("[ok] connected")

    sequence = [40, 60, 50]
    for v in sequence:
        msg = {
            "event": "EVENT_SUB_APP_ACTIONS_DATA_CHANGED",
            "data": {
                "SubAppName": "sonar",
                "Id": str(uuid.UUID(int=0)),
                "ActionName": "MONITOR_MASTER_VOLUME",
                "Value": float(v),
            },
        }
        ws.send(json.dumps(msg))
        print(f"[step] sent MONITOR_MASTER_VOLUME = {v}; sleeping 3s, watch the Sonar UI slider")
        time.sleep(3)

    ws.close()
    print("\n[PASS-IF] the 'Monitor Master' slider in Sonar GG moved to 40% -> 60% -> 50%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
