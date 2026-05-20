"""
Probe 3: Low-level keyboard hook for volume/media keys.

Uses Win32 WH_KEYBOARD_LL via ctypes (no third-party deps).

Modes:
    python probes/probe_hook.py           # observe-only: log events, do NOT suppress
    python probes/probe_hook.py --suppress # log AND swallow VolUp/VolDn/Mute/MediaPlay/Next/Prev/Stop

How to interpret:
  - If observe-only mode logs your roller turns and media-button press, our hook
    sees the keys (i.e. SteelSeries GG isn't using raw-input-exclusive).
  - If --suppress also stops Windows master volume from changing, we are earlier
    in the hook chain than whoever moves the slider -- we can take over the keys.
  - If suppress mode logs events but Windows volume STILL changes, GG (or Sonar)
    is consuming the keys via a higher-priority path (raw input, kernel filter,
    or HID interception) and we'll need a different approach.

Press Ctrl+C in this console to exit.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import signal
import sys
import threading
import time
from datetime import datetime

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_NAMES = {
    0xAD: "VOLUME_MUTE",
    0xAE: "VOLUME_DOWN",
    0xAF: "VOLUME_UP",
    0xB0: "MEDIA_NEXT_TRACK",
    0xB1: "MEDIA_PREV_TRACK",
    0xB2: "MEDIA_STOP",
    0xB3: "MEDIA_PLAY_PAUSE",
    0xB4: "LAUNCH_MAIL",
    0xB5: "LAUNCH_MEDIA_SELECT",
    0xB6: "LAUNCH_APP1",
    0xB7: "LAUNCH_APP2",
}

SUPPRESS_VKS = {0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(wt.LPARAM, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.restype = wt.LPARAM
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel32.GetCurrentThreadId.restype = wt.DWORD

_hook_handle = None
_suppress = False
_event_count = 0
_main_thread_id = 0


def now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def make_callback():
    def callback(nCode, wParam, lParam):
        global _event_count
        if nCode == 0:
            kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT))[0]
            vk = kbd.vkCode
            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)
            if vk in VK_NAMES and is_down:
                _event_count += 1
                name = VK_NAMES[vk]
                action = "SUPPRESS" if (_suppress and vk in SUPPRESS_VKS) else "passthru"
                print(f"[{now()}] #{_event_count:03d}  vk=0x{vk:02X}  {name:20s}  {action}  scan={kbd.scanCode}  flags=0x{kbd.flags:02X}",
                      flush=True)
                if _suppress and vk in SUPPRESS_VKS:
                    return 1
        return user32.CallNextHookEx(_hook_handle, nCode, wParam, lParam)

    return HOOKPROC(callback)


def install_and_pump():
    global _hook_handle, _main_thread_id
    cb = make_callback()
    _hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, None, 0)
    if not _hook_handle:
        err = ctypes.get_last_error()
        raise OSError(f"SetWindowsHookExW failed: {err}")
    _main_thread_id = kernel32.GetCurrentThreadId()
    print(f"[ok] WH_KEYBOARD_LL installed (hook=0x{_hook_handle:X}, thread={_main_thread_id})")
    print("     suppress = " + ("ON  - VolUp/VolDn/Mute/Media* will be swallowed" if _suppress else "OFF - all events pass through"))
    print("     Roll your volume wheel, press the media button, etc.")
    print("     Press Ctrl+C to exit.\n")

    msg = wt.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret in (0, -1):
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    user32.UnhookWindowsHookEx(_hook_handle)
    print(f"\n[exit] hook removed; observed {_event_count} media-range events total.")


def on_sigint(signum, frame):
    print("\n[sigint] stopping...", flush=True)
    user32.PostThreadMessageW(_main_thread_id, WM_QUIT, 0, 0)


def main() -> int:
    global _suppress
    ap = argparse.ArgumentParser()
    ap.add_argument("--suppress", action="store_true", help="swallow volume/media keys instead of passing through")
    ap.add_argument("--timeout", type=float, default=0, help="auto-exit after N seconds (0 = run until Ctrl+C)")
    args = ap.parse_args()
    _suppress = args.suppress
    signal.signal(signal.SIGINT, on_sigint)

    if args.timeout > 0:
        def _stop():
            time.sleep(args.timeout)
            print(f"\n[timeout] {args.timeout}s elapsed, stopping...", flush=True)
            user32.PostThreadMessageW(_main_thread_id, WM_QUIT, 0, 0)
        threading.Thread(target=_stop, daemon=True).start()

    try:
        install_and_pump()
    except Exception as e:
        print(f"[FAIL] {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
