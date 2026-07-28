# hw-sentinel

An overlay that stays invisible until something is actually wrong.

AMD Adrenalin's metrics overlay can only be *always on* or *on in games* — it has no
rule engine. hw-sentinel watches the same sensors and shows nothing at all until a
metric crosses an abnormal threshold, then slides a card in at the right edge of the
screen and plays an alert sound.

Built for a **Ryzen 7 9800X3D + Radeon RX 9070 XT**, but the rules are just config.

## What it watches

| Rule | Severity | Trips at | Clears at | Dwell |
|---|---|---|---|---|
| CPU Tctl/Tdie | warn | > 88 °C | 83 °C | 10 s |
| CPU SoC voltage | **critical** | > 1.30 V | 1.25 V | 5 s |
| CPU core voltage | warn | > 1.40 V | 1.35 V | 5 s |
| GPU hot spot (junction) | **critical** | > 100 °C | 92 °C | 10 s |
| GPU core (edge) | warn | > 90 °C | 84 °C | 10 s |
| GPU hot spot − edge delta | warn | > 25 °C | 20 °C | 30 s |
| GPU core voltage | warn | > 1.15 V | 1.10 V | 5 s |

Every number lives in `config.toml`.

## Setup

> **Already set up on this machine** and running at logon. Skip to
> [Verifying it works](#verifying-it-works-without-cooking-anything).

Everything hw-sentinel needs — Python included — lives in this folder. There is no system
Python, no winget package, nothing in Program Files, and nothing on your PATH. See
[INSTALL-MANIFEST.md](INSTALL-MANIFEST.md) for the full accounting.

### 1. Build the private runtime

```bash
powershell -ExecutionPolicy Bypass -File bootstrap.ps1
```

Downloads a private CPython, adds tkinter, and unpacks LibreHardwareMonitor into
`runtime\`, verifying every artifact against a pinned SHA-256. RTSS has no portable
build, so bootstrap copies an installed tree: install RTSS once, run bootstrap, then
uninstall the system copy — `runtime\rtss\` keeps working on its own.

### 2. Generate the alert sounds

```bash
runtime\python\python.exe generate_assets.py
```

### 3. Pin the sensor names

Sensor naming on Zen 5 / RDNA 4 varies by LHM version, so the patterns shipped in
`config.toml` are starting guesses. List what your machine actually exposes:

```bash
hw-sentinel.cmd discover
```

Correct any wrong patterns in the `[sensors]` table. A unique suffix or substring is
enough — `temperatures/gpu-core` matches
`amd-radeon-rx-9070-xt/temperatures/gpu-core`. Ambiguous patterns are a hard error
rather than a silent wrong guess.

If a sensor genuinely isn't exposed (SoC voltage depends on motherboard support), set
that rule's `enabled = false`.

### 4. Check everything resolves

```bash
hw-sentinel.cmd doctor
```

### 5. Run it

```bash
hw-sentinel.cmd run
```

To start it — and LHM and RTSS — automatically at logon, from an **elevated** PowerShell:

```bash
powershell -ExecutionPolicy Bypass -File install.ps1
```

That registers three scheduled tasks pointing at `runtime\`. They run with administrator
rights, which is what LibreHardwareMonitor needs to read CPU temperature and voltage, and
what avoids a UAC prompt on every boot. `install.ps1 -Uninstall` removes them.

## Uninstalling

hw-sentinel writes nothing outside its own folder — no registry keys, no services, no
Python packages — so removing it is deleting the folder, plus the scheduled tasks if you
registered them. `uninstall.ps1` does the whole job:

```bash
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIf
```

| Command | Effect |
|---|---|
| `uninstall.ps1` | hw-sentinel only; leaves LHM and RTSS installed |
| `uninstall.ps1 -All` | also uninstalls LHM and RTSS via winget |
| `uninstall.ps1 -All -RemoveProject` | also deletes this folder |

Note that LHM and RTSS are **runtime** dependencies, not build tools — removing them stops
alerts working (LHM entirely, RTSS for in-game only). Full details in
[INSTALL-MANIFEST.md](INSTALL-MANIFEST.md).

## Verifying it works without cooking anything

```bash
hw-sentinel.cmd test --rule gpu_hotspot --seconds 10
```

Forces a trip through every sink. Run it once on the desktop (expect the card sliding
in from the right, plus the chime), then again with a fullscreen game running (expect
the RTSS OSD line and the chime, and no card).

To validate the real path including hysteresis, temporarily lower a threshold to just
above idle, confirm it fires after `dwell`, then raise it back and confirm it clears
after `clear_dwell`.

## How "abnormal" is decided

A bare `value > threshold` check would flash the overlay on every transient spike.
Each rule is a state machine with four knobs:

- **`dwell`** — seconds over the line before tripping. Kills momentary spikes.
- **`clear_at`** — a separate, lower value to clear at. This is hysteresis: trip at
  88, clear at 83, so a sensor sitting on the threshold cannot strobe.
- **`clear_dwell`** — seconds back under `clear_at` before the card hides.
- **`cooldown`** — minimum gap between a clear and the next trip. Stops nagging.

Click any card to snooze that one rule for `card.snooze_minutes`.

## Where alerts appear

| Situation | What you get |
|---|---|
| Desktop, or windowed/borderless game | The card at the right edge + sound |
| Exclusive-fullscreen game | RTSS OSD line + sound |
| RTSS not running | Card + sound (in-game alerts unavailable) |

**The card cannot be drawn inside an exclusive-fullscreen game.** Nothing can, short
of writing a D3D/Vulkan hook — RTSS renders text into the game's frame, so in-game the
alert degrades to a styled OSD line in the same colours. The **sound is identical
either way**, which is what makes it reliable.

The in-game OSD's screen position, font, and size are RTSS's own settings, not
hw-sentinel's — adjust them in RTSS.

## Files

```
hwsentinel/
  __main__.py     CLI: doctor | discover | run | test
  config.py       config loading + validation
  source_lhm.py   LHM /data.json -> flat sensor paths
  rules.py        the state machine, plus a sandboxed expression evaluator
  sink_card.py    the slide-in card
  sink_rtss.py    RTSS shared-memory OSD writer
  sink_sound.py   winsound alerts, rate-limited
  sink_log.py     JSONL event log
config.toml       thresholds and sensor aliases
config.toml       thresholds and sensor aliases
generate_assets.py  writes assets/warn.wav and assets/critical.wav
runtime/          private Python + LHM + RTSS (built by bootstrap.ps1)
state/            events.jsonl
hw-sentinel.cmd   launcher — always uses runtime\python
bootstrap.ps1     builds runtime/ from verified downloads
install.ps1       logon autostart (3 scheduled tasks)
uninstall.ps1     removes everything, inside and out
```

No third-party Python packages — `urllib`, `tkinter`, `ctypes`, `winsound` and
`tomllib` are all stdlib in 3.12. Nothing is installed into any `site-packages`.

## Third-party components

None of these are redistributed here — `runtime/` is git-ignored, and `bootstrap.ps1`
fetches each from its official source at install time.

| Component | Licence |
|---|---|
| CPython (embeddable) | PSF License |
| Tcl/Tk (via Python's `tcltk` component) | BSD-style |
| LibreHardwareMonitor | MPL-2.0 |
| RivaTuner Statistics Server | Proprietary freeware — **not redistributable**; bootstrap copies a local install |

hw-sentinel's own code is MIT (see [LICENSE](LICENSE)).

## Troubleshooting

**Everything reads 0.00** — LHM isn't elevated.

**`doctor` says RTSS shared memory not found** — RTSS isn't running. Desktop alerts
still work.

**RTSS shows literal `<C0=...>` tags** — set `markup = false` under `[rtss]`.

**Card corners look jagged** — they aren't antialiased; the `-transparentcolor` trick
has hard edges. Lower `RADIUS` in `sink_card.py`, or set it to 0 for square corners.

**Alerts fire too often** — raise `value`, or raise `dwell` so brief spikes are
ignored. A quiet `state\events.jsonl` after a normal gaming session means the
thresholds are right.

**Nothing ever fires** — check `doctor` resolves every sensor, then run `test`.

**Nothing starts after a reboot** — the three scheduled tasks aren't registered. Run
`install.ps1` from an elevated PowerShell.
