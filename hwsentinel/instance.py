"""Stop two monitors running at once.

Nothing prevented it, and it happened: a copy left running from a source checkout
kept going after an installed copy took over, so every alert produced two cards, two
sounds, and two clients writing to the same RTSS slot.

A named mutex is the standard way to do this on Windows and needs no cleanup on a
crash - the kernel drops the handle with the process.

The name is session-local on purpose. Fast user switching gives each signed-in user
their own session, and one monitor per session is correct: they each have their own
screen to draw alerts on.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    """Holds the claim for as long as the object is alive."""

    def __init__(self, name: str = "hw-sentinel-monitor") -> None:
        self.name = f"Local\\{name}"
        self._handle: int | None = None
        self.already_running = False

    def acquire(self) -> bool:
        """True if this process now owns the claim, False if someone else does."""
        handle = _kernel32.CreateMutexW(None, True, self.name)
        err = ctypes.get_last_error()
        if not handle:
            # Cannot tell - do not block monitoring over a diagnostic failing.
            return True
        if err == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            self.already_running = True
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def another_instance_running(name: str = "hw-sentinel-monitor") -> bool:
    """Probe without claiming, for `doctor`. Never reports the caller as a duplicate."""
    probe = SingleInstance(name)
    if probe.acquire():
        probe.release()
        return False
    return True
