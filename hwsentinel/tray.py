"""A notification-area icon, so hw-sentinel is something you can see and control.

Without this the tray shows LibreHardwareMonitor and RTSS - the two helpers - and
nothing for the program actually doing the work, which leaves no obvious way to pause
it or shut it down.

Built directly on Shell_NotifyIcon through ctypes to keep the zero-dependency rule; the
usual libraries for this pull in Pillow.

Threading: Windows delivers tray callbacks to the thread that created the window, so
this owns a thread with its own message pump. Menu choices are pushed onto a queue and
acted on by the tk thread, exactly like sensor readings - no UI work happens here.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x0010, 0x0040
MF_STRING, MF_SEPARATOR, MF_GRAYED = 0x0000, 0x0800, 0x0001
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
CW_USEDEFAULT = -0x80000000

# Menu command ids
ID_STATUS = 1
ID_PAUSE = 2
ID_SNOOZE = 3
ID_SETTINGS = 4
ID_LOG = 5
ID_DOCTOR = 6
ID_EXIT = 7

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class TrayIcon:
    """Owns the icon and its thread. Menu choices arrive on `commands`."""

    def __init__(self, idle_icon: Path, alert_icon: Path, tooltip: str = "hw-sentinel") -> None:
        self.commands: queue.Queue[str] = queue.Queue()
        self.last_error = ""
        self._icon_paths = {"idle": idle_icon, "alert": alert_icon}
        self._icons: dict[str, int] = {}
        self._hwnd = None
        self._state = "idle"
        self._tooltip = tooltip
        self._paused = False
        self._alerts = 0
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wndproc = WNDPROC(self._on_message)   # kept alive deliberately: if this
                                                    # is garbage collected Windows calls
                                                    # into freed memory and the process dies

    # -- lifecycle ------------------------------------------------------------

    def start(self, timeout: float = 5.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._hwnd is not None

    def stop(self) -> None:
        self._stop.set()
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    # -- state shown to the user ----------------------------------------------

    def update(self, alerts: int, paused: bool, summary: str = "") -> None:
        """Reflect the current state in the icon and its tooltip."""
        self._alerts, self._paused = alerts, paused
        state = "alert" if alerts and not paused else "idle"
        if paused:
            tip = "hw-sentinel - paused"
        elif alerts:
            tip = summary or f"hw-sentinel - {alerts} alert(s)"
        else:
            tip = "hw-sentinel - monitoring"
        changed = state != self._state
        self._state, self._tooltip = state, tip[:127]
        if self._hwnd:
            self._notify(NIM_MODIFY, icon=changed)

    # -- internals ------------------------------------------------------------

    def _load_icons(self) -> None:
        for key, path in self._icon_paths.items():
            h = user32.LoadImageW(None, str(path), IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                self._icons[key] = h
            else:
                self.last_error = f"could not load {path}"

    def _notify(self, action: int, icon: bool = True) -> bool:
        data = NOTIFYICONDATA()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_TIP | (NIF_ICON if icon else 0)
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self._icons.get(self._state, 0)
        data.szTip = self._tooltip
        return bool(shell32.Shell_NotifyIconW(action, ctypes.byref(data)))

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if self._alerts:
            label = f"{self._alerts} alert(s) active"
        elif self._paused:
            label = "Monitoring paused"
        else:
            label = "Monitoring - all normal"
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, ID_STATUS, label)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_PAUSE,
                           "Resume monitoring" if self._paused else "Pause monitoring")
        user32.AppendMenuW(menu, MF_STRING, ID_SNOOZE, "Snooze all alerts for 15 minutes")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_SETTINGS, "Edit alert thresholds...")
        user32.AppendMenuW(menu, MF_STRING, ID_LOG, "Open event log")
        user32.AppendMenuW(menu, MF_STRING, ID_DOCTOR, "Check setup")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Quit hw-sentinel")

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # Required, and easy to miss: without it the menu refuses to close when the
        # user clicks elsewhere.
        user32.SetForegroundWindow(self._hwnd)
        choice = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                       pt.x, pt.y, 0, self._hwnd, None)
        user32.DestroyMenu(menu)

        for cmd_id, name in ((ID_PAUSE, "toggle-pause"), (ID_SNOOZE, "snooze-all"),
                             (ID_SETTINGS, "settings"), (ID_LOG, "log"),
                             (ID_DOCTOR, "doctor"), (ID_EXIT, "exit")):
            if choice == cmd_id:
                self.commands.put(name)

    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam in (WM_RBUTTONUP, WM_LBUTTONUP):
                self._show_menu()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        try:
            hinst = kernel32.GetModuleHandleW(None)
            cls = WNDCLASSEX()
            cls.cbSize = ctypes.sizeof(WNDCLASSEX)
            cls.lpfnWndProc = self._wndproc
            cls.hInstance = hinst
            cls.lpszClassName = "hwSentinelTray"
            if not user32.RegisterClassExW(ctypes.byref(cls)):
                # Already registered from a previous run in this process; harmless.
                pass
            self._hwnd = user32.CreateWindowExW(
                0, "hwSentinelTray", "hw-sentinel", 0,
                CW_USEDEFAULT, CW_USEDEFAULT, 0, 0, None, None, hinst, None)
            if not self._hwnd:
                self.last_error = f"CreateWindowEx failed ({ctypes.get_last_error()})"
                return
            self._load_icons()
            if not self._notify(NIM_ADD):
                self.last_error = "Shell_NotifyIcon add failed"
        finally:
            self._ready.set()

        if not self._hwnd:
            return

        msg = wintypes.MSG()
        while not self._stop.is_set():
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._notify(NIM_DELETE, icon=False)
        user32.DestroyWindow(self._hwnd)
        self._hwnd = None
