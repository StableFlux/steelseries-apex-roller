"""WH_KEYBOARD_LL hook with callback-based dispatch.

Callbacks run on a worker thread fed by a queue, so the hook procedure itself
returns within microseconds. Heavy work (HTTP, OLED) inside a low-level hook
callback would cause Windows to silently un-register us once it crosses
LowLevelHooksTimeout (registry-configurable, ~300ms-2s by default).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)

# --- Win32 constants ----------------------------------------------------------
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# KBDLLHOOKSTRUCT.flags bits
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10  # set on events synthesized via SendInput / keybd_event


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(wt.LPARAM, ctypes.c_int, wt.WPARAM, wt.LPARAM)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.SetWindowsHookExW.restype = wt.HHOOK
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
_user32.CallNextHookEx.restype = wt.LPARAM
_user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
_user32.UnhookWindowsHookEx.restype = wt.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_kernel32.GetCurrentThreadId.restype = wt.DWORD


class MediaHook:
    def __init__(
        self,
        on_volume_up: Callable[[], None] | None = None,
        on_volume_down: Callable[[], None] | None = None,
        on_media_button: Callable[[], None] | None = None,
        *,
        suppress: bool = True,
        injected_only: bool = True,
    ):
        self._cb_up = on_volume_up
        self._cb_down = on_volume_down
        self._cb_media = on_media_button
        self.suppress = suppress
        self.injected_only = injected_only
        self.paused = False

        self._handle: int | None = None
        self._hook_thread_id: int = 0
        self._cb_ref: HOOKPROC | None = None  # keep alive against GC

        self._actions: queue.Queue[str] = queue.Queue()
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None

    # --- worker thread (does HTTP work for the callbacks) ---------------------
    def _worker_loop(self) -> None:
        dispatch = {
            "vol_up": self._cb_up,
            "vol_down": self._cb_down,
            "media": self._cb_media,
        }
        while not self._worker_stop.is_set():
            try:
                kind = self._actions.get(timeout=0.2)
            except queue.Empty:
                continue
            cb = dispatch.get(kind)
            if cb is None:
                continue
            try:
                cb()
            except Exception:
                log.exception("hook callback %s raised", kind)

    # --- hook procedure (must return quickly) --------------------------------
    def _make_hookproc(self) -> HOOKPROC:
        def proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode != 0 or self.paused:
                return _user32.CallNextHookEx(self._handle, nCode, wParam, lParam)
            if wParam not in (WM_KEYDOWN, WM_SYSKEYDOWN):
                return _user32.CallNextHookEx(self._handle, nCode, wParam, lParam)
            kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT))[0]
            # Skip events that don't come from GG's SendInput synth (i.e. real
            # hardware media keys on a second keyboard) so we don't fight them.
            if self.injected_only and not (kbd.flags & LLKHF_INJECTED):
                return _user32.CallNextHookEx(self._handle, nCode, wParam, lParam)
            vk = kbd.vkCode
            handled = False
            if vk == VK_VOLUME_UP and self._cb_up is not None:
                self._actions.put("vol_up")
                handled = True
            elif vk == VK_VOLUME_DOWN and self._cb_down is not None:
                self._actions.put("vol_down")
                handled = True
            elif vk == VK_MEDIA_PLAY_PAUSE and self._cb_media is not None:
                self._actions.put("media")
                handled = True
            if handled and self.suppress:
                return 1
            return _user32.CallNextHookEx(self._handle, nCode, wParam, lParam)

        return HOOKPROC(proc)

    # --- lifecycle ------------------------------------------------------------
    def run_forever(self) -> None:
        """Install the hook on the current thread and pump messages until stop()."""
        self._cb_ref = self._make_hookproc()
        self._handle = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._cb_ref, None, 0)
        if not self._handle:
            err = ctypes.get_last_error()
            raise OSError(f"SetWindowsHookExW failed: {err}")
        self._hook_thread_id = _kernel32.GetCurrentThreadId()

        self._worker = threading.Thread(target=self._worker_loop, name="hook-worker", daemon=True)
        self._worker.start()

        msg = wt.MSG()
        try:
            while True:
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._handle:
                _user32.UnhookWindowsHookEx(self._handle)
                self._handle = None
            self._worker_stop.set()

    def stop(self) -> None:
        if self._hook_thread_id:
            _user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
