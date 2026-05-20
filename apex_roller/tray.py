"""System tray icon + menu.

Tray runs on the main thread (pystray requirement on Windows). The keyboard
hook runs on its own thread with its own Win32 message loop -- the two are
independent.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

from . import RELEASES_URL, paths, startup
from .app import App

log = logging.getLogger(__name__)


def _make_icon_image(size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (24, 28, 40, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.55))
    except OSError:
        font = ImageFont.load_default()
    text = "AR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, fill=(220, 235, 255, 255), font=font)
    return img


class Tray:
    def __init__(self, app: App):
        self.app = app
        app.on_state_change = self.refresh_tooltip
        self.icon = pystray.Icon(
            "apex_roller",
            icon=_make_icon_image(),
            title=self._tooltip_text(),
            menu=self._build_menu(),
        )

    def _tooltip_text(self) -> str:
        if self.app.hook.paused:
            return "Apex Roller (paused)"
        pct = int(round(self.app.volume * 100))
        return f"Apex Roller - {self.app.position.label} {pct}%"

    def refresh_tooltip(self) -> None:
        try:
            self.icon.title = self._tooltip_text()
            self.icon.update_menu()
        except Exception:
            log.exception("tooltip refresh failed")

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _: self._tooltip_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause",
                self._toggle_pause,
                checked=lambda _: self.app.hook.paused,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Include Master channel",
                self._toggle_master,
                checked=lambda _: self.app.config.include_master,
            ),
            pystray.MenuItem(
                "Include Streaming sliders",
                self._toggle_streaming,
                checked=lambda _: self.app.config.include_streaming,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Run at Startup",
                self._toggle_startup,
                checked=lambda _: startup.is_installed(),
                enabled=lambda _: startup.can_install_startup(),
            ),
            pystray.MenuItem("Check for Updates", self._check_updates),
            pystray.MenuItem("Open Logs Folder", self._open_logs),
            pystray.MenuItem("About", self._about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _toggle_master(self, icon, item) -> None:
        self.app.update_config(include_master=not self.app.config.include_master)
        self.refresh_tooltip()

    def _toggle_streaming(self, icon, item) -> None:
        self.app.update_config(include_streaming=not self.app.config.include_streaming)
        self.refresh_tooltip()

    def _toggle_pause(self, icon, item) -> None:
        self.app.hook.paused = not self.app.hook.paused
        log.info("paused=%s", self.app.hook.paused)
        if self.app.hook.paused:
            try:
                self.app.gs.show("Apex Roller", "    Paused    ")
            except Exception:
                log.exception("OLED paused notice failed")
        else:
            self.app._push_oled()
        self.refresh_tooltip()

    def _toggle_startup(self, icon, item) -> None:
        try:
            if startup.is_installed():
                startup.uninstall()
            else:
                startup.install()
        except Exception:
            log.exception("startup toggle failed")

    def _open_logs(self, *_) -> None:
        target = paths.log_dir()
        log.info("opening logs folder: %s", target)
        try:
            subprocess.Popen(["explorer.exe", str(target)])
        except Exception:
            log.exception("could not open logs folder via explorer.exe")

    def _check_updates(self, *_) -> None:
        log.info("opening releases page: %s", RELEASES_URL)
        try:
            webbrowser.open(RELEASES_URL)
        except Exception:
            log.exception("could not open releases page")

    def _about(self, *_) -> None:
        from . import PROJECT_URL, __version__
        log.info("Apex Roller v%s - %s", __version__, PROJECT_URL)
        try:
            webbrowser.open(PROJECT_URL)
        except Exception:
            log.exception("could not open project page")

    def _quit(self, icon, item) -> None:
        log.info("tray quit")
        try:
            self.app.shutdown()
        finally:
            self.icon.stop()

    def run(self) -> None:
        self.icon.run()
