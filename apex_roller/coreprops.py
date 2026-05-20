"""Read SteelSeries Engine 3 coreProps.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_PATH = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"),
    "SteelSeries",
    "SteelSeries Engine 3",
    "coreProps.json",
)


@dataclass(frozen=True)
class CoreProps:
    gamesense_address: str       # plain HTTP, used by GameSense REST
    gg_encrypted_address: str    # HTTPS (self-signed), used for /subApps discovery


class CorePropsError(Exception):
    pass


def load(path: str = DEFAULT_PATH) -> CoreProps:
    if not os.path.exists(path):
        raise CorePropsError(
            f"coreProps.json not found at {path}. Is SteelSeries GG installed and running?"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    try:
        return CoreProps(
            gamesense_address=data["address"],
            gg_encrypted_address=data["ggEncryptedAddress"],
        )
    except KeyError as e:
        raise CorePropsError(f"coreProps.json missing expected key: {e}") from e
