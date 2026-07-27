"""Generate the two alert sounds procedurally, so the repo carries no binary blobs.

    py -3 generate_assets.py

warn      soft rising two-tone chime
critical  three urgent beeps, louder and faster
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44100


def tone(freq: float, ms: int, amp: float, decay: float = 4.0) -> list[float]:
    """A sine with a short attack and exponential decay — no clicks at either end."""
    n = int(RATE * ms / 1000)
    attack = int(RATE * 0.005)
    out = []
    for i in range(n):
        env = math.exp(-decay * i / n)
        if i < attack:
            env *= i / attack
        # A little second harmonic keeps it from sounding like a test tone.
        s = math.sin(2 * math.pi * freq * i / RATE) + 0.18 * math.sin(4 * math.pi * freq * i / RATE)
        out.append(amp * env * s / 1.18)
    return out


def silence(ms: int) -> list[float]:
    return [0.0] * int(RATE * ms / 1000)


def write(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    print(f"wrote {path}  ({len(samples) / RATE:.2f}s)")


def main() -> None:
    assets = Path(__file__).parent / "assets"

    warn = tone(784.0, 120, 0.34, decay=3.5) + tone(1046.5, 260, 0.34, decay=3.0)

    critical: list[float] = []
    for _ in range(3):
        critical += tone(987.8, 110, 0.55, decay=6.0) + silence(55)

    write(assets / "warn.wav", warn)
    write(assets / "critical.wav", critical)


if __name__ == "__main__":
    main()
