"""Append-only JSONL record of every trip and clear.

A quiet log is the goal: if a normal gaming session produces no entries, the
thresholds are tuned right and the screen stays empty.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Config
from .rules import Event, EventKind


class LogSink:
    def __init__(self, cfg: Config) -> None:
        self.enabled = cfg.log.enabled
        self.path: Path = cfg.resolve(cfg.log.path)
        self.last_error = ""

    def write(self, event: Event) -> None:
        # UPDATE fires every poll while an alert holds; only edges are worth recording.
        if not self.enabled or event.kind is EventKind.UPDATE:
            return
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event.kind.value,
            "rule": event.alert.key,
            "severity": event.alert.severity,
            "value": round(event.alert.value, 2),
            "unit": event.alert.unit,
            "detail": event.alert.detail,
        }
        if event.kind is EventKind.CLEAR:
            record["held_seconds"] = round(max(0.0, time.time() - event.alert.since), 1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.last_error = f"cannot write {self.path}: {exc}"
