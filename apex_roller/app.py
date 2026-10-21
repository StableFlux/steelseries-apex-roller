"""Orchestrator: wires the hook to Sonar (state) and GameSense (OLED).

Cycle order (Master only with config.include_master):
  classic mode  : [Master,] Game, Chat, Media, Aux
  streamer mode : the same channels' monitoring sliders; with
                  config.include_streaming each channel takes two positions,
                  monitoring then streaming (Game Monitor, Game Stream, ...)

Buttons: roller turn = volume, media button = next position (Shift + media
button when preserving play/pause), roller press = mute toggle for the position.
Cycling also pops Sonar's on-screen overlay for the selected position.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from .config import Config
from .coreprops import load as load_core_props
from .gamesense import GameSense
from .gg_ws import STREAMER_ACTIONS, STREAMER_MUTE_ACTIONS, GGEventClient
from .hook import MediaHook
from .sonar import Slider, Sonar

log = logging.getLogger(__name__)

# (sonar channel key, OLED display label) -- order is the cycle order.
CHANNELS: list[tuple[str, str]] = [
    ("master", "Master"),
    ("game", "Game"),
    ("chatRender", "Chat"),
    ("media", "Media"),
    ("aux", "Aux"),
]
VOLUME_STEP = 0.02  # per roller click
OLED_RELEASE_AFTER_S = 3.0  # release the OLED back to the default view after N seconds of inactivity
# Bar width tuned so line 2 stays under ~15 chars total (the Apex Pro OLED
# clips beyond that with the default GameSense font): "[========] 100%" = 15.
BAR_WIDTH = 8


def format_level(volume: float, *, muted: bool) -> str:
    """OLED line 2: "[=====---]  67%", or "[ MUTED  ]  67%" (same width)."""
    pct = int(round(volume * 100))
    if muted:
        inner = "MUTED".center(BAR_WIDTH)
    else:
        filled = max(0, min(BAR_WIDTH, round(volume * BAR_WIDTH)))
        inner = ("=" * filled) + ("-" * (BAR_WIDTH - filled))
    return f"[{inner}] {pct:>3d}%"


@dataclass(frozen=True)
class Position:
    channel: str           # sonar channel key
    slider: Slider | None  # 'monitoring' / 'streaming' / None in classic
    label: str             # OLED line 1 text


def build_positions(mode: str, *, include_master: bool, include_streaming: bool) -> list[Position]:
    channels = [(k, label) for k, label in CHANNELS if include_master or k != "master"]
    if mode == "stream":
        out: list[Position] = []
        for key, label in channels:
            out.append(Position(key, "monitoring", f"{label} Monitor"))
            if include_streaming:
                out.append(Position(key, "streaming", f"{label} Stream"))
        return out
    # Classic mode: one slider per channel; the include_streaming flag is N/A.
    return [Position(key, None, label) for key, label in channels]


class App:
    def __init__(self, *, config: Config | None = None, sonar: Sonar | None = None,
                 gs: GameSense | None = None, gg_ws: GGEventClient | None = None) -> None:
        """Clients default to the real local services; tests inject fakes."""
        self._lock = threading.Lock()
        self.config = config if config is not None else Config.load()

        props = load_core_props() if None in (sonar, gs, gg_ws) else None
        self.sonar = sonar if sonar is not None else Sonar(props.gg_encrypted_address)
        if gs is None:
            gs = GameSense(props.gamesense_address)
            gs.register()
        self.gs = gs
        # Deliberately NOT starting heartbeat: we want GameSense to release the
        # OLED back to its default view shortly after we stop sending events.
        # GG /eventing client used to make the Sonar UI sliders update live
        # and to pop Sonar's on-screen overlay.
        # Live UI sync currently only wired up for streamer-mode actions.
        self.gg_ws = gg_ws if gg_ws is not None else GGEventClient(props.gg_encrypted_address)
        self._release_timer: threading.Timer | None = None

        self.positions = build_positions(
            self.sonar.mode,
            include_master=self.config.include_master,
            include_streaming=self.config.include_streaming,
        )
        self.idx = 0
        self.volume = self._read_current()
        self.muted = self._read_muted()
        self._push_oled()

        self.on_state_change: Callable[[], None] | None = None

        self.hook = MediaHook(
            on_volume_up=self._on_volume_up,
            on_volume_down=self._on_volume_down,
            on_media_button=self.next_channel,
            on_mute_button=self._on_mute_button,
            suppress=True,
            preserve_media_play_pause=self.config.preserve_media_play_pause,
        )

    def _notify(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change()
            except Exception:
                log.exception("state-change callback failed")

    def update_config(self, **changes: bool) -> None:
        """Apply and persist settings, update the hook, and rebuild the cycle.
        Cursor snaps to the closest position (same channel+slider, then channel)."""
        with self._lock:
            for k, v in changes.items():
                setattr(self.config, k, v)
            self.config.save()
            self.hook.preserve_media_play_pause = self.config.preserve_media_play_pause
            old = self.positions[self.idx] if self.positions else None
            self.positions = build_positions(
                self.sonar.mode,
                include_master=self.config.include_master,
                include_streaming=self.config.include_streaming,
            )
            if not self.positions:
                # Degenerate config (e.g. nothing enabled). Restore a safe minimum.
                log.warning("config produced empty cycle; forcing default subset")
                self.positions = build_positions(self.sonar.mode, include_master=False, include_streaming=False)
            new_idx = 0
            if old is not None:
                for i, p in enumerate(self.positions):
                    if p.channel == old.channel and p.slider == old.slider:
                        new_idx = i
                        break
                else:
                    for i, p in enumerate(self.positions):
                        if p.channel == old.channel:
                            new_idx = i
                            break
            self.idx = new_idx
            self.volume = self._read_current()
            self.muted = self._read_muted()
        self._push_oled()
        self._notify()
        log.info("config updated: %s; cycle now %d positions starting at %s",
                 changes, len(self.positions), self.positions[self.idx].label)

    # --- actions (run on hook-worker or tray thread) --------------------------
    def _on_volume_up(self) -> None:
        with self._lock:
            self.volume = min(1.0, self.volume + VOLUME_STEP)
            self._apply()

    def _on_volume_down(self) -> None:
        with self._lock:
            self.volume = max(0.0, self.volume - VOLUME_STEP)
            self._apply()

    def next_channel(self) -> None:
        """Select the next cycle position and refresh Sonar, OLED, and tray."""
        with self._lock:
            self.idx = (self.idx + 1) % len(self.positions)
            self.volume = self._read_current()
            self.muted = self._read_muted()
            # Re-send the unchanged value: Sonar's action handler shows its
            # on-screen overlay for that slider on every set, changed or not.
            self._send_ui_action(STREAMER_ACTIONS, self.volume * 100.0)
        self._push_oled()
        self._notify()

    def _on_mute_button(self) -> None:
        with self._lock:
            p = self.position
            self.muted = not self.muted
            log.info("%s %s", p.label, "muted" if self.muted else "unmuted")
            try:
                self.sonar.set_muted(p.channel, self.muted, p.slider)
            except Exception:
                log.exception("set mute failed for %s", p.label)
            self._send_ui_action(STREAMER_MUTE_ACTIONS, self.muted)
        self._push_oled()
        self._notify()

    # --- helpers -------------------------------------------------------------
    @property
    def position(self) -> Position:
        return self.positions[self.idx]

    def _read_current(self) -> float:
        p = self.position
        try:
            return self.sonar.get_volume(p.channel, p.slider)
        except Exception:
            log.exception("read volume failed for %s", p.label)
            return 0.0

    def _read_muted(self) -> bool:
        p = self.position
        try:
            return self.sonar.get_muted(p.channel, p.slider)
        except Exception:
            log.exception("read mute failed for %s", p.label)
            return False

    def _send_ui_action(self, actions: dict[tuple[str, str], str], value: float | bool) -> None:
        """Push a value through Sonar's action path so the GG UI redraws and the
        overlay pops. Streamer mode only (no classic action names exist)."""
        p = self.position
        if p.slider is None:
            return
        action = actions.get((p.slider, p.channel))
        if action is not None:
            self.gg_ws.send_action(action, value)

    def _apply(self) -> None:
        p = self.position
        try:
            self.sonar.set_volume(p.channel, self.volume, p.slider)
        except Exception:
            log.exception("set volume failed for %s", p.label)
        # Nudge the Sonar GG UI to redraw the slider live (streamer mode only).
        self._send_ui_action(STREAMER_ACTIONS, self.volume * 100.0)
        self._push_oled()
        self._notify()

    def show_status(self, line1: str, line2: str) -> None:
        """Show arbitrary text on the OLED and start the auto-release timer.
        Use this for one-off status displays (e.g. 'Paused')."""
        try:
            self.gs.show(line1, line2)
        except Exception:
            log.exception("OLED push failed")
        self._schedule_oled_release()

    def _push_oled(self) -> None:
        self.show_status(self.position.label, format_level(self.volume, muted=self.muted))

    def _schedule_oled_release(self) -> None:
        """Restart the timer that releases the OLED back to default view."""
        if self._release_timer is not None:
            self._release_timer.cancel()
        t = threading.Timer(OLED_RELEASE_AFTER_S, self._release_oled)
        t.daemon = True
        t.name = "oled-release"
        self._release_timer = t
        t.start()

    def _release_oled(self) -> None:
        try:
            self.gs.stop_game()
        except Exception:
            log.exception("OLED release failed")

    # --- lifecycle -----------------------------------------------------------
    def run(self) -> None:
        log.info("starting: mode=%s positions=%d start=%s (%d%%)",
                 self.sonar.mode, len(self.positions),
                 self.position.label, round(self.volume * 100))
        self.hook.run_forever()

    def shutdown(self) -> None:
        log.info("shutdown requested")
        if self._release_timer is not None:
            self._release_timer.cancel()
        self.hook.stop()
        self.gs.shutdown()
        self.gg_ws.close()
