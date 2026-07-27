"""Push alert text into RivaTuner Statistics Server's on-screen display.

This is the only way to draw inside an exclusive-fullscreen game without writing a
D3D/Vulkan hook: RTSS already hooks the game, and exposes a shared-memory block where
external clients can claim an OSD slot.

All field offsets are derived from the header at runtime rather than hardcoded. The
OSD entry has grown across RTSS versions (szOSD 256B, then szOSDOwner, then szOSDEx,
then an extended graphics buffer), so a hardcoded layout would break on upgrade.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .config import RtssCfg

_FILE_MAP_ALL_ACCESS = 0x000F001F
# RTSS sets dwSignature from the C++ multi-char literal 'RTSS', which MSVC encodes as
# 'R'<<24 | 'T'<<16 | 'S'<<8 | 'S'. Stored little-endian the bytes read "SSTR".
_SIGNATURE = 0x52545353
_MAX_SANE_SIZE = 64 * 1024 * 1024

# Offsets within RTSS_SHARED_MEMORY_OSD_ENTRY
_OSD_TEXT_OFF, _OSD_TEXT_LEN = 0, 256
_OSD_OWNER_OFF, _OSD_OWNER_LEN = 256, 256
_OSD_EX_OFF, _OSD_EX_LEN = 512, 4096

# Offsets within RTSS_SHARED_MEMORY_APP_ENTRY
_APP_PID_OFF = 0
_APP_TIME1_OFF = 272
_APP_STALE_MS = 3000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenFileMappingW.restype = wintypes.HANDLE
_kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_kernel32.MapViewOfFile.restype = ctypes.c_void_p
_kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_kernel32.UnmapViewOfFile.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetTickCount.restype = wintypes.DWORD


class _Header(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwVersion", ctypes.c_uint32),
        ("dwAppEntrySize", ctypes.c_uint32),
        ("dwAppArrOffset", ctypes.c_uint32),
        ("dwAppArrSize", ctypes.c_uint32),
        ("dwOSDEntrySize", ctypes.c_uint32),
        ("dwOSDArrOffset", ctypes.c_uint32),
        ("dwOSDArrSize", ctypes.c_uint32),
        ("dwOSDFrame", ctypes.c_uint32),
    ]


def sanitize(text: str) -> str:
    """RTSS renders a byte string; keep it to plain ASCII it can definitely draw."""
    return (
        text.replace("°", "")
        .replace("·", "-")
        .replace("—", "-")
        .replace("–", "-")
        .encode("ascii", "ignore")
        .decode("ascii")
    )


class RtssSink:
    """Attach lazily and degrade quietly — RTSS may not be running at all."""

    def __init__(self, cfg: RtssCfg) -> None:
        self.cfg = cfg
        self._handle = None
        self._view: int | None = None
        self._header: _Header | None = None
        self._slot: int | None = None
        self._last_text = ""
        self._next_attach = 0.0
        self.version = ""
        self.last_error = "not attached"

    # -- lifecycle ------------------------------------------------------------

    @property
    def attached(self) -> bool:
        return self._view is not None

    def ensure_attached(self) -> bool:
        """Attach if possible, retrying at most every 5s so a missing RTSS is cheap."""
        if self.attached:
            return True
        if not self.cfg.enabled or time.time() < self._next_attach:
            return False
        self._next_attach = time.time() + 5.0
        return self.attach()

    def attach(self) -> bool:
        self.detach()
        handle = _kernel32.OpenFileMappingW(_FILE_MAP_ALL_ACCESS, False, "RTSSSharedMemoryV2")
        if not handle:
            self.last_error = "RTSS shared memory not found (is RivaTuner Statistics Server running?)"
            return False
        view = _kernel32.MapViewOfFile(handle, _FILE_MAP_ALL_ACCESS, 0, 0, 0)
        if not view:
            _kernel32.CloseHandle(handle)
            self.last_error = f"MapViewOfFile failed (error {ctypes.get_last_error()})"
            return False

        # Copy the header out before validating: on any failure path the view gets
        # unmapped, and a ctypes struct still bound to that address would fault the
        # moment it is read.
        header = _Header.from_buffer_copy(ctypes.string_at(view, ctypes.sizeof(_Header)))

        def reject(reason: str) -> bool:
            _kernel32.UnmapViewOfFile(ctypes.c_void_p(view))
            _kernel32.CloseHandle(handle)
            self.last_error = reason
            return False

        if header.dwSignature != _SIGNATURE:
            return reject(f"bad RTSS signature 0x{header.dwSignature:08X}")
        if header.dwOSDEntrySize < _OSD_OWNER_OFF + _OSD_OWNER_LEN or header.dwOSDArrSize == 0:
            return reject("unexpected RTSS OSD entry layout")
        # Both arrays must fit inside something plausible; in_game() and _write()
        # index into them, so a bogus geometry here becomes an access violation there.
        for what, need in (
            ("OSD", header.dwOSDArrOffset + header.dwOSDArrSize * header.dwOSDEntrySize),
            ("app", header.dwAppArrOffset + header.dwAppArrSize * header.dwAppEntrySize),
        ):
            if need > _MAX_SANE_SIZE:
                return reject(f"implausible RTSS {what} array geometry ({need} bytes)")

        self._handle, self._view = handle, view
        self._header = _Header.from_address(view)  # live view, valid while mapped
        self.version = f"{header.dwVersion >> 16}.{header.dwVersion & 0xFFFF}"
        self.last_error = ""
        return True

    def detach(self) -> None:
        if self._view is not None:
            try:
                self.clear()
                self._release_slot()
            except OSError:
                pass
            _kernel32.UnmapViewOfFile(ctypes.c_void_p(self._view))
        if self._handle:
            _kernel32.CloseHandle(self._handle)
        self._handle, self._view, self._header, self._slot = None, None, None, None
        self._last_text = ""

    close = detach

    # -- raw access -----------------------------------------------------------

    def _entry_addr(self, index: int) -> int:
        h = self._header
        return self._view + h.dwOSDArrOffset + index * h.dwOSDEntrySize

    def _read_str(self, addr: int, length: int) -> str:
        raw = ctypes.string_at(addr, length)
        return raw.split(b"\0", 1)[0].decode("ascii", "ignore")

    def _write_str(self, addr: int, length: int, text: str) -> None:
        payload = text.encode("ascii", "ignore")[: length - 1] + b"\0"
        ctypes.memmove(addr, payload, len(payload))

    def _claim_slot(self) -> int | None:
        """Take the slot we already own, else the first free one."""
        if self._slot is not None:
            addr = self._entry_addr(self._slot)
            if self._read_str(addr + _OSD_OWNER_OFF, _OSD_OWNER_LEN) == self.cfg.owner:
                return self._slot
            self._slot = None

        for i in range(self._header.dwOSDArrSize):
            owner = self._read_str(self._entry_addr(i) + _OSD_OWNER_OFF, _OSD_OWNER_LEN)
            if owner in ("", self.cfg.owner):
                self._write_str(self._entry_addr(i) + _OSD_OWNER_OFF, _OSD_OWNER_LEN, self.cfg.owner)
                self._slot = i
                return i
        self.last_error = "no free RTSS OSD slot"
        return None

    def _release_slot(self) -> None:
        if self._slot is not None and self._header is not None:
            self._write_str(self._entry_addr(self._slot) + _OSD_OWNER_OFF, _OSD_OWNER_LEN, "")
            self._slot = None

    # -- public API -----------------------------------------------------------

    def in_game(self) -> bool:
        """True when RTSS currently has a live 3D application hooked."""
        if not self.attached:
            return False
        h = self._header
        if h.dwAppEntrySize < _APP_TIME1_OFF + 4:
            return False
        now = _kernel32.GetTickCount()
        for i in range(h.dwAppArrSize):
            base = self._view + h.dwAppArrOffset + i * h.dwAppEntrySize
            pid = ctypes.c_uint32.from_address(base + _APP_PID_OFF).value
            if not pid:
                continue
            t1 = ctypes.c_uint32.from_address(base + _APP_TIME1_OFF).value
            # GetTickCount wraps every ~49 days; unsigned subtraction handles it.
            if ((now - t1) & 0xFFFFFFFF) < _APP_STALE_MS:
                return True
        return False

    def show(self, text: str) -> bool:
        if not self.ensure_attached():
            return False
        text = sanitize(text)
        if text == self._last_text:
            return True
        return self._write(text)

    def clear(self) -> bool:
        if not self.attached or self._slot is None:
            return False
        if self._last_text == "":
            return True
        return self._write("")

    def _write(self, text: str) -> bool:
        slot = self._claim_slot()
        if slot is None:
            return False
        try:
            addr = self._entry_addr(slot)
            self._write_str(addr + _OSD_TEXT_OFF, _OSD_TEXT_LEN, text)
            if self._header.dwOSDEntrySize >= _OSD_EX_OFF + _OSD_EX_LEN:
                # Newer RTSS prefers szOSDEx; write both so either is correct.
                self._write_str(addr + _OSD_EX_OFF, _OSD_EX_LEN, text)
            # Bumping the frame counter is what makes RTSS repaint.
            ctypes.c_uint32.from_address(self._view + _Header.dwOSDFrame.offset).value = (
                self._header.dwOSDFrame + 1
            ) & 0xFFFFFFFF
        except OSError as exc:
            self.last_error = f"RTSS write failed: {exc}"
            self.detach()
            return False
        self._last_text = text
        return True
