"""App behaviour against fake Sonar / GameSense / GG eventing clients."""
from __future__ import annotations

import pytest

from apex_roller.app import App, format_level
from apex_roller.config import Config
from apex_roller.tray import Tray


class FakeSonar:
    def __init__(self, mode: str = "stream"):
        self.mode = mode
        self.volumes: dict[tuple, float] = {}
        self.muted: dict[tuple, bool] = {}
        self.set_volume_calls: list[tuple] = []
        self.set_muted_calls: list[tuple] = []

    def get_volume(self, channel, slider=None):
        return self.volumes.get((channel, slider), 0.5)

    def set_volume(self, channel, value, slider=None):
        self.volumes[(channel, slider)] = value
        self.set_volume_calls.append((channel, value, slider))
        return value

    def get_muted(self, channel, slider=None):
        return self.muted.get((channel, slider), False)

    def set_muted(self, channel, muted, slider=None):
        self.muted[(channel, slider)] = muted
        self.set_muted_calls.append((channel, muted, slider))
        return muted


class FakeGameSense:
    def __init__(self):
        self.frames: list[tuple[str, str]] = []

    def show(self, line1, line2):
        self.frames.append((line1, line2))

    def stop_game(self):
        pass

    def shutdown(self):
        pass


class FakeGG:
    def __init__(self):
        self.sent: list[tuple[str, object]] = []

    def send_action(self, action_name, value):
        self.sent.append((action_name, value))

    def close(self):
        pass


@pytest.fixture
def make_app():
    apps: list[App] = []

    def _make(mode: str = "stream", **config) -> App:
        app = App(
            config=Config(**config),
            sonar=FakeSonar(mode),
            gs=FakeGameSense(),
            gg_ws=FakeGG(),
        )
        apps.append(app)
        return app

    yield _make
    for app in apps:
        if app._release_timer is not None:
            app._release_timer.cancel()


# --- OLED line 2 ---------------------------------------------------------------

def test_format_level_shows_bar_and_percent():
    assert format_level(0.67, muted=False) == "[=====---]  67%"


def test_format_level_muted_keeps_percent_and_width():
    line = format_level(0.5, muted=True)
    assert line == "[ MUTED  ]  50%"
    assert len(line) == len(format_level(0.5, muted=False))


# --- cycle button pops the Sonar overlay -----------------------------------------

def test_media_button_resends_current_volume_for_overlay(make_app):
    app = make_app()
    app.sonar.volumes[("chatRender", "monitoring")] = 0.4
    app.next_channel()  # Game Monitor -> Chat Monitor
    assert app.position.label == "Chat Monitor"
    assert app.gg_ws.sent[-1] == ("MONITOR_CHAT_VOLUME", 40.0)
    # Re-sending the current value must not write to the audio engine.
    assert app.sonar.set_volume_calls == []


def test_media_button_classic_mode_sends_nothing(make_app):
    app = make_app(mode="classic")
    app.next_channel()
    assert app.gg_ws.sent == []


# --- roller press toggles mute ---------------------------------------------------

def test_mute_button_toggles_selected_slider_only(make_app):
    app = make_app(include_streaming=True)
    assert app.position.label == "Game Monitor"
    app._on_mute_button()
    assert app.sonar.set_muted_calls == [("game", True, "monitoring")]
    assert app.gg_ws.sent[-1] == ("MONITOR_GAME_MUTE", True)
    assert app.gs.frames[-1] == ("Game Monitor", "[ MUTED  ]  50%")

    app._on_mute_button()
    assert app.sonar.set_muted_calls[-1] == ("game", False, "monitoring")
    assert app.gg_ws.sent[-1] == ("MONITOR_GAME_MUTE", False)
    # The streaming slider for the same channel is never touched.
    assert all(slider == "monitoring" for _, _, slider in app.sonar.set_muted_calls)


def test_mute_button_classic_mode_uses_rest_only(make_app):
    app = make_app(mode="classic")
    app._on_mute_button()
    assert app.sonar.set_muted_calls == [("game", True, None)]
    assert app.gg_ws.sent == []


def test_rolling_while_muted_stays_muted(make_app):
    app = make_app()
    app._on_mute_button()
    app._on_volume_up()
    assert app.sonar.set_muted_calls == [("game", True, "monitoring")]
    assert app.gs.frames[-1][1].startswith("[ MUTED  ]")


def test_cycling_reads_mute_state_of_new_position(make_app):
    app = make_app()
    app.sonar.muted[("chatRender", "monitoring")] = True
    app.next_channel()
    assert app.muted is True
    assert app.gs.frames[-1] == ("Chat Monitor", "[ MUTED  ]  50%")


# --- playback preservation and tray controls ------------------------------------

@pytest.mark.parametrize("enabled", [False, True])
def test_play_pause_setting_applies_immediately_and_persists(make_app, monkeypatch, tmp_path, enabled):
    monkeypatch.setattr("apex_roller.config.config_path", lambda: tmp_path / "config.json")
    app = make_app(preserve_media_play_pause=not enabled)
    assert app.hook.preserve_media_play_pause is not enabled
    app.next_channel()
    position = app.position

    app.update_config(preserve_media_play_pause=enabled)

    assert app.hook.preserve_media_play_pause is enabled
    assert Config.load().preserve_media_play_pause is enabled
    assert app.position == position


def test_tray_playback_toggle_and_next_channel(make_app, monkeypatch, tmp_path):
    monkeypatch.setattr("apex_roller.config.config_path", lambda: tmp_path / "config.json")
    app = make_app()
    tray = Tray.__new__(Tray)  # Exercise real menu actions without creating an icon.
    tray.app = app
    monkeypatch.setattr(tray, "refresh_tooltip", lambda: None)
    items = {item.text: item for item in tray._build_menu()}
    toggle = items["Preserve media play/pause"]
    next_channel = items["Next channel"]

    assert toggle.checked is False
    toggle(None)
    assert toggle.checked is True
    assert app.hook.preserve_media_play_pause is True
    assert Config.load().preserve_media_play_pause is True

    assert next_channel.enabled is True
    next_channel(None)
    assert app.position.label == "Chat Monitor"
    assert app.gg_ws.sent[-1] == ("MONITOR_CHAT_VOLUME", 50.0)

    app.hook.paused = True
    assert next_channel.enabled is False


def test_existing_config_keeps_media_button_behavior(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"include_master": true, "include_streaming": true}', encoding="utf-8")
    monkeypatch.setattr("apex_roller.config.config_path", lambda: path)

    config = Config.load()

    assert config.preserve_media_play_pause is False
    assert config.include_master is True
    assert config.include_streaming is True
