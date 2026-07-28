"""Locate, launch and supervise LibreHardwareMonitor and RTSS.

With this in play hw-sentinel is the only thing Windows needs to start. Two things
make that work:

* **Elevation is inherited.** The scheduled task runs hw-sentinel with highest
  privileges, and a child process inherits that token — so LibreHardwareMonitor gets
  the administrator rights it needs to read MSRs without its own task or a UAC prompt.
* **Liveness is probed, not guessed.** LHM is alive iff its web server answers; RTSS is
  alive iff its shared memory exists. Both are exact, so we never have to enumerate
  processes or match on executable names, and we never start a second copy of something
  the user was already running.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .sink_rtss import rtss_running

_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def rtss_from_registry() -> Path | None:
    """Where RTSS actually got installed, per its Add/Remove Programs entry.

    Its installer lets the user choose any folder, so probing the default Program Files
    paths misses a relocated install — and then nothing would launch it at logon.
    """
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            root = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_KEY, 0, winreg.KEY_READ | view
            )
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for i in range(count):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                        name, _ = winreg.QueryValueEx(sub, "DisplayName")
                        if "RivaTuner Statistics Server" not in str(name):
                            continue
                        try:
                            location = str(winreg.QueryValueEx(sub, "InstallLocation")[0])
                        except OSError:
                            location = ""
                        if not location:
                            uninst = str(winreg.QueryValueEx(sub, "UninstallString")[0])
                            location = str(Path(uninst.strip('"')).parent)
                        exe = Path(location) / "RTSS.exe"
                        if exe.is_file():
                            return exe
                except OSError:
                    continue
    return None


@dataclass
class DepStatus:
    name: str
    path: Path | None = None
    running: bool = False
    started_by_us: bool = False
    note: str = ""

    def describe(self) -> str:
        if not self.running:
            return f"not running — {self.note or 'not found'}"
        how = "started by hw-sentinel" if self.started_by_us else "already running"
        return f"running ({how}) — {self.path or 'path unknown'}"


@dataclass
class DepSupervisor:
    cfg: Config
    _procs: dict[str, subprocess.Popen] = field(default_factory=dict)
    _last_attempt: dict[str, float] = field(default_factory=dict)
    status: dict[str, DepStatus] = field(default_factory=dict)

    # -- discovery ------------------------------------------------------------

    def _candidates(self, which: str) -> list[Path]:
        program = self.cfg.program_root
        if which == "lhm":
            explicit = self.cfg.deps.lhm_path
            paths = [
                program / "runtime" / "lhm" / "LibreHardwareMonitor.exe",
                Path(r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe"),
            ]
        else:
            explicit = self.cfg.deps.rtss_path
            from_registry = rtss_from_registry()
            paths = [
                program / "runtime" / "rtss" / "RTSS.exe",
                *([from_registry] if from_registry else []),
                Path(r"C:\Program Files (x86)\RivaTuner Statistics Server\RTSS.exe"),
                Path(r"C:\Program Files\RivaTuner Statistics Server\RTSS.exe"),
            ]
        return ([Path(explicit)] if explicit else []) + paths

    def find(self, which: str) -> Path | None:
        return next((p for p in self._candidates(which) if p.is_file()), None)

    # -- liveness -------------------------------------------------------------

    def lhm_alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.cfg.source.url, timeout=2.0):
                return True
        except (urllib.error.URLError, OSError):
            return False

    @staticmethod
    def rtss_alive() -> bool:
        return rtss_running()

    def _alive(self, which: str) -> bool:
        return self.lhm_alive() if which == "lhm" else self.rtss_alive()

    # -- launching ------------------------------------------------------------

    def _launch(self, which: str, path: Path) -> bool:
        try:
            self._procs[which] = subprocess.Popen(
                [str(path)],
                cwd=str(path.parent),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except OSError:
            return False

    def _ensure(self, which: str, wait: float) -> DepStatus:
        label = "LibreHardwareMonitor" if which == "lhm" else "RTSS"
        st = DepStatus(name=label)

        if self._alive(which):
            # Somebody else's copy, or one we started earlier. Either way, adopt it —
            # starting a second instance of RTSS in particular causes real trouble.
            st.running = True
            st.started_by_us = which in self._procs
            st.path = self.find(which)
            return st

        st.path = self.find(which)
        if st.path is None:
            st.note = "not found in any known location"
            return st

        if not self._launch(which, st.path):
            st.note = f"failed to launch {st.path}"
            return st

        deadline = time.time() + wait
        while time.time() < deadline:
            if self._alive(which):
                st.running = True
                st.started_by_us = True
                return st
            time.sleep(0.5)

        st.note = f"launched {st.path} but it did not come up within {wait:g}s"
        return st

    # -- public API -----------------------------------------------------------

    def start(self) -> dict[str, DepStatus]:
        """Bring both dependencies up. Only LHM's absence actually breaks anything."""
        if not self.cfg.deps.manage:
            self.status = {
                "lhm": DepStatus("LibreHardwareMonitor", self.find("lhm"), self.lhm_alive(),
                                 note="deps.manage is false"),
                "rtss": DepStatus("RTSS", self.find("rtss"), self.rtss_alive(),
                                  note="deps.manage is false"),
            }
            return self.status

        # LHM first and with the full timeout: nothing can be read until it answers.
        self.status = {
            "lhm": self._ensure("lhm", self.cfg.deps.start_timeout),
            "rtss": self._ensure("rtss", 8.0) if self.cfg.rtss.enabled
            else DepStatus("RTSS", note="disabled in config"),
        }
        return self.status

    def heartbeat(self, min_interval: float = 60.0) -> None:
        """Relaunch a dependency that has died. Called from the poll loop.

        Rate-limited so a dependency that refuses to start cannot become a process
        spawn loop.
        """
        if not self.cfg.deps.manage:
            return
        now = time.time()
        for which in ("lhm", "rtss"):
            if which == "rtss" and not self.cfg.rtss.enabled:
                continue
            if self._alive(which):
                continue
            if now - self._last_attempt.get(which, 0.0) < min_interval:
                continue
            self._last_attempt[which] = now
            self.status[which] = self._ensure(which, 8.0)

    def stop(self) -> None:
        """Stop only what we started — never a copy the user was already running."""
        for proc in self._procs.values():
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        self._procs.clear()
