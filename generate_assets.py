"""Generate the alert sounds and tray icons procedurally, so the repo carries no
binary blobs.

    py -3 generate_assets.py

warn.wav      soft rising two-tone chime
critical.wav  three urgent beeps, louder and faster
idle.ico      tray icon while everything is fine
alert.ico     tray icon while a rule is tripped
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


# --- tray icons ----------------------------------------------------------------
# Drawn by hand rather than shipped as binaries: an .ico is a trivial container and
# generating it keeps the repo free of blobs, exactly like the sounds.

ICON_SIZE = 32
SUPERSAMPLE = 4  # coverage is averaged over a 4x4 grid, which is what smooths the edges


def _blend(bg: tuple[int, int, int], fg: tuple[int, int, int], a: float) -> tuple[int, int, int]:
    return tuple(int(round(b + (f - b) * a)) for b, f in zip(bg, fg))


def draw_icon(ring: tuple[int, int, int], core: tuple[int, int, int]) -> bytes:
    """A filled disc inside a ring, returned as bottom-up BGRA rows.

    Small and round reads clearly at 16x16 in the notification area, where anything
    with fine detail turns to mush.
    """
    n, s = ICON_SIZE, SUPERSAMPLE
    centre = (n - 1) / 2.0
    r_outer, r_inner = n * 0.46, n * 0.26
    rows: list[bytes] = []

    for y in range(n):
        row = bytearray()
        for x in range(n):
            hits_outer = hits_inner = 0
            for sy in range(s):
                for sx in range(s):
                    px = x + (sx + 0.5) / s - 0.5
                    py = y + (sy + 0.5) / s - 0.5
                    d = math.hypot(px - centre, py - centre)
                    if d <= r_outer:
                        hits_outer += 1
                    if d <= r_inner:
                        hits_inner += 1
            total = s * s
            a_outer = hits_outer / total
            if a_outer == 0:
                row += bytes((0, 0, 0, 0))
                continue
            a_inner = hits_inner / total
            rgb = _blend(ring, core, a_inner)
            # Premultiplied is not required for ICO; straight alpha is correct here.
            row += bytes((rgb[2], rgb[1], rgb[0], int(round(a_outer * 255))))
        rows.append(bytes(row))

    return b"".join(reversed(rows))  # DIBs are stored bottom-up


def write_ico(path: Path, pixels: bytes) -> None:
    n = ICON_SIZE
    and_stride = ((n + 31) // 32) * 4          # 1bpp mask, rows padded to 4 bytes
    and_mask = b"\x00" * (and_stride * n)      # fully opaque; the alpha channel decides
    header = struct.pack(
        "<IiiHHIIiiII",
        40, n, n * 2, 1, 32, 0, len(pixels) + len(and_mask), 0, 0, 0, 0,
    )
    image = header + pixels + and_mask
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(image), 6 + 16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico + image)
    print(f"wrote {path}  ({len(ico + image)} bytes)")


def main() -> None:
    assets = Path(__file__).parent / "assets"

    warn = tone(784.0, 120, 0.34, decay=3.5) + tone(1046.5, 260, 0.34, decay=3.0)

    critical: list[float] = []
    for _ in range(3):
        critical += tone(987.8, 110, 0.55, decay=6.0) + silence(55)

    write(assets / "warn.wav", warn)
    write(assets / "critical.wav", critical)

    # Idle is deliberately muted - a tray icon you notice all day is a nuisance.
    # Alert uses the same clay as the alert card, so the two read as one product.
    write_ico(assets / "idle.ico", draw_icon(ring=(0x6B, 0x6B, 0x68), core=(0xFA, 0xF9, 0xF5)))
    write_ico(assets / "alert.ico", draw_icon(ring=(0xBF, 0x4D, 0x43), core=(0xD9, 0x77, 0x57)))


if __name__ == "__main__":
    main()
