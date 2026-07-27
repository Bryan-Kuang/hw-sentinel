"""Read sensors from LibreHardwareMonitor's built-in web server.

LHM exposes a nested tree at /data.json in which every value is a *display string*
carrying its unit ("62.5 °C", "1.234 V") and formatted in the OS locale. This module
flattens that tree into stable, sluggified paths and parses the numbers back out.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NUM_RE = re.compile(r"^\s*([-+]?[\d][\d.,]*)\s*(.*?)\s*$")


class SourceError(Exception):
    """LHM could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Reading:
    path: str          # e.g. "amd-ryzen-7-9800x3d/temperatures/core-tctl-tdie"
    name: str          # e.g. "Core (Tctl/Tdie)"
    hardware: str      # e.g. "AMD Ryzen 7 9800X3D"
    group: str         # e.g. "Temperatures"
    value: float
    unit: str          # e.g. "°C"

    def format(self, decimals: int = 1) -> str:
        return f"{self.value:.{decimals}f} {self.unit}".strip()


def slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")


def parse_value(raw: str) -> tuple[float, str] | None:
    """Split "62,5 °C" into (62.5, "°C"). Returns None for blank/placeholder cells."""
    if not raw or raw.strip() in ("", "-", "N/A"):
        return None
    m = _NUM_RE.match(raw)
    if not m:
        return None
    number, unit = m.group(1), m.group(2)

    # Locale-dependent formatting: LHM renders with the OS separators. If both
    # separators appear, the comma is grouping; if only a comma appears, it is the
    # decimal point.
    if "," in number and "." in number:
        number = number.replace(",", "")
    elif "," in number:
        number = number.replace(",", ".")
    try:
        return float(number), unit
    except ValueError:
        return None


def flatten(tree: dict) -> dict[str, Reading]:
    """Walk the LHM node tree depth-first, yielding one Reading per numeric leaf."""
    readings: dict[str, Reading] = {}

    def walk(node: dict, trail: list[str]) -> None:
        text = str(node.get("Text", "")).strip()
        children = node.get("Children") or []
        here = trail + [text] if text else trail

        if not children:
            parsed = parse_value(str(node.get("Value", "")))
            if parsed is None or len(here) < 2:
                return
            value, unit = parsed
            path = "/".join(slug(part) for part in here[1:])  # drop the "Sensor" root
            # Duplicate leaf names under one group are possible; disambiguate rather
            # than silently dropping one.
            if path in readings:
                n = 2
                while f"{path}-{n}" in readings:
                    n += 1
                path = f"{path}-{n}"
            # here is [root, machine, hardware, group, sensor] — LHM nests everything
            # under the computer name, and motherboards nest a chip under the board.
            # Counting back from the leaf gets the real hardware either way.
            readings[path] = Reading(
                path=path,
                name=text,
                hardware=here[-3] if len(here) >= 3 else here[1] if len(here) > 1 else "",
                group=here[-2] if len(here) >= 2 else "",
                value=value,
                unit=unit,
            )
            return

        for child in children:
            if isinstance(child, dict):
                walk(child, here)

    walk(tree, [])
    return readings


class LhmSource:
    def __init__(self, url: str, timeout: float = 2.0) -> None:
        self.url = url
        self.timeout = timeout

    def poll(self) -> dict[str, Reading]:
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                payload = resp.read()
        except urllib.error.URLError as exc:
            raise SourceError(
                f"cannot reach LibreHardwareMonitor at {self.url} ({exc.reason}). "
                "Is it running with Options -> Remote Web Server -> Run enabled?"
            ) from exc
        except OSError as exc:
            raise SourceError(f"cannot reach LibreHardwareMonitor at {self.url}: {exc}") from exc

        try:
            tree = json.loads(payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise SourceError(f"LHM returned invalid JSON: {exc}") from exc

        readings = flatten(tree)
        if not readings:
            raise SourceError("LHM returned no readable sensors")
        return readings


class SensorResolver:
    """Map config aliases onto real sensor paths.

    Exact paths are brittle across LHM versions and driver updates, so a pattern is
    matched exactly first, then by suffix, then by substring. Ambiguity is an error:
    quietly picking one of several matching temperature sensors is exactly how you
    end up alerting on the wrong thing.
    """

    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self._cache: dict[str, str] = {}

    def resolve(self, alias: str, readings: dict[str, Reading]) -> Reading:
        pattern = self.aliases.get(alias, alias)
        cached = self._cache.get(alias)
        if cached and cached in readings:
            return readings[cached]

        path = self._match(pattern, readings)
        self._cache[alias] = path
        return readings[path]

    def _match(self, pattern: str, readings: dict[str, Reading]) -> str:
        needle = "/".join(slug(p) for p in pattern.split("/") if p.strip())

        if needle in readings:
            return needle
        for matcher in (
            lambda p: p.endswith("/" + needle),
            lambda p: needle in p,
        ):
            hits = [p for p in readings if matcher(p)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise SourceError(
                    f"sensor pattern '{pattern}' is ambiguous, matches {len(hits)}: "
                    + ", ".join(sorted(hits)[:5])
                    + ("..." if len(hits) > 5 else "")
                )
        raise SourceError(f"sensor pattern '{pattern}' matched no sensor (run 'discover' to list them)")


def grouped(readings: dict[str, Reading]) -> Iterator[tuple[str, list[Reading]]]:
    """Readings bucketed by hardware, for the discover command's output."""
    buckets: dict[str, list[Reading]] = {}
    for r in readings.values():
        buckets.setdefault(r.hardware, []).append(r)
    for hardware in sorted(buckets):
        yield hardware, sorted(buckets[hardware], key=lambda r: r.path)
