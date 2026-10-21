"""Keyboard routing without installing a system-wide hook."""
from __future__ import annotations

import ctypes

import pytest

from apex_roller import hook as hook_mod
from apex_roller.hook import (
    KBDLLHOOKSTRUCT, LLKHF_INJECTED, MediaHook, VK_MEDIA_PLAY_PAUSE,
    VK_VOLUME_DOWN, VK_VOLUME_MUTE, VK_VOLUME_UP, WM_KEYDOWN, WM_KEYUP,
)

PASSTHROUGH = 42


@pytest.fixture
def send_key(monkeypatch):
    monkeypatch.setattr(hook_mod._user32, "CallNextHookEx", lambda *_: PASSTHROUGH)
    monkeypatch.setattr(hook_mod._user32, "GetAsyncKeyState", lambda _: 0)

    def _send(hook, vk=VK_MEDIA_PLAY_PAUSE, *, flags=LLKHF_INJECTED, message=WM_KEYDOWN):
        event = KBDLLHOOKSTRUCT(vkCode=vk, flags=flags)
        return hook._make_hookproc()(0, message, ctypes.addressof(event))

    return _send


@pytest.mark.parametrize("preserve,shift_state,cycles", [
    (False, 0, True),           # Existing behavior remains the default.
    (True, 0, False),           # Plain presses reach the media player.
    (True, 1, False),           # A previous Shift press is not a held Shift.
    (True, -32768, True),       # The high bit means Shift is currently held.
    (True, -32767, True),
])
def test_media_button_routing(send_key, monkeypatch, preserve, shift_state, cycles):
    monkeypatch.setattr(hook_mod._user32, "GetAsyncKeyState", lambda _: shift_state)
    hook = MediaHook(on_media_button=lambda: None, preserve_media_play_pause=preserve)

    assert send_key(hook) == (1 if cycles else PASSTHROUGH)
    if cycles:
        assert hook._actions.get_nowait() == "media"
    assert hook._actions.empty()


@pytest.mark.parametrize("vk,action", [
    (VK_VOLUME_UP, "vol_up"),
    (VK_VOLUME_DOWN, "vol_down"),
    (VK_VOLUME_MUTE, "mute"),
])
def test_preserving_playback_keeps_roller_controls(send_key, vk, action):
    hook = MediaHook(
        on_volume_up=lambda: None,
        on_volume_down=lambda: None,
        on_mute_button=lambda: None,
        preserve_media_play_pause=True,
    )

    assert send_key(hook, vk) == 1
    assert hook._actions.get_nowait() == action


@pytest.mark.parametrize("flags,paused,message", [
    (0, False, WM_KEYDOWN),               # Other keyboards still pass through.
    (LLKHF_INJECTED, True, WM_KEYDOWN),   # Pausing bypasses the shortcut too.
    (LLKHF_INJECTED, False, WM_KEYUP),
])
def test_media_passthrough_guards(send_key, monkeypatch, flags, paused, message):
    monkeypatch.setattr(hook_mod._user32, "GetAsyncKeyState", lambda _: -32768)
    hook = MediaHook(on_media_button=lambda: None, preserve_media_play_pause=True)
    hook.paused = paused

    assert send_key(hook, flags=flags, message=message) == PASSTHROUGH
    assert hook._actions.empty()
