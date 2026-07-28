"""Alert sound — the one signal that reaches you identically on the desktop and
inside an exclusive-fullscreen game.

Plays once on the tripping edge, never on a loop while the condition holds, and is
rate-limited per rule so a sensor flapping across the threshold cannot machine-gun it.
"""

from __future__ import annotations

import time
import winsound
from pathlib import Path

from .config import Config


class SoundSink:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg.sound
        # Sounds ship with the program, so they come from the program root — under
        # Program Files that is read-only, which is fine since we only read them.
        self.paths = {
            "warn": cfg.resolve_program(cfg.sound.warn_wav),
            "critical": cfg.resolve_program(cfg.sound.critical_wav),
        }
        self._last: dict[str, float] = {}
        self.last_error = ""

    def missing(self) -> list[Path]:
        return [p for p in self.paths.values() if not p.exists()]

    def play(self, severity: str, key: str = "") -> bool:
        if not self.cfg.enabled:
            return False
        if self.cfg.critical_only and severity != "critical":
            return False

        now = time.time()
        if now - self._last.get(key or severity, -1e9) < self.cfg.min_interval:
            return False

        path = self.paths.get(severity) or self.paths["warn"]
        if not path.exists():
            self.last_error = f"missing sound file: {path}"
            return False
        try:
            winsound.PlaySound(
                str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except RuntimeError as exc:
            self.last_error = f"PlaySound failed: {exc}"
            return False

        self._last[key or severity] = now
        return True
