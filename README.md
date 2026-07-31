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
| GPU core voltage | warn | > 1.25 V | 1.20 V | 5 s |

Every number lives in `config.toml`.

## Setup

Download `hw-sentinel-setup-<version>.exe` from
[Releases](https://github.com/Bryan-Kuang/hw-sentinel/releases) and run it. It installs
to `C:\Program Files\hw-sentinel`, brings its own Python, and starts monitoring at every
logon. Nothing else on your machine is touched — see
[INSTALL-MANIFEST.md](INSTALL-MANIFEST.md) for the exact accounting.

> **SmartScreen will warn you.** The installer is unsigned, so Windows shows
> "Windows protected your PC". Click **More info → Run anyway**. Clearing that warning
> properly requires a paid code-signing certificate. Verify the SHA-256 on the release
> page if you want to check the download first.

After installing, run **Check hw-sentinel setup** from the Start menu. Sensor names differ
between machines, so it will tell you if any rule needs its sensor corrected — see
[Pin the sensor names](#3-pin-the-sensor-names).

## Building from source

Only needed if you want to develop or build the installer yourself.

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

Sensor naming varies by vendor, model and LHM version, so the patterns in
`config.default.toml` cannot be right everywhere. `doctor` marks each rule OK or FAIL.
To list what your machine actually exposes:

```bash
hw-sentinel.cmd discover
```

Correct any wrong patterns in the `[sensors]` table of your config
(`%ProgramData%\hw-sentinel\config.toml` when installed). A unique suffix or substring is
enough — `temperatures/gpu-core` matches
`amd-radeon-rx-9070-xt/temperatures/gpu-core`.

**Ambiguous patterns are a hard error, not a silent wrong guess.** On most AMD desktops
the CPU's integrated graphics exposes sensors with the same names as the discrete card, so
`voltages/gpu-core` matches two things and is rejected. Qualify it with the hardware name:

```toml
gpu_core_volts = "amd-radeon-rx-9070-xt/voltages/gpu-core"
```

If a sensor genuinely isn't exposed (SoC voltage depends on motherboard support), set
that rule's `enabled = false` rather than aiming it at something approximate. A safety
alarm watching the wrong rail is worse than no alarm.

### 4. Check everything resolves

```bash
hw-sentinel.cmd doctor
```

### 5. Run it

```bash
hw-sentinel.cmd run
```

To start automatically at logon, from an **elevated** PowerShell:

```bash
powershell -ExecutionPolicy Bypass -File install.ps1
```

That registers **one** scheduled task. It runs with administrator rights, and hw-sentinel
launches LibreHardwareMonitor and RTSS itself as child processes — they inherit that
elevated token, which is how LHM gets the rights it needs to read sensors without a UAC
prompt at every boot. `install.ps1 -Uninstall` removes it.

### 6. Build the installer

```bash
winget install JRSoftware.InnoSetup
```

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Produces `dist\hw-sentinel-setup-<version>.exe`. The build stages an allow-listed payload
and **fails** if any RTSS file reaches it, since RTSS may not be redistributed.

## Uninstalling

If you used the installer: **Settings → Apps → hw-sentinel → Uninstall**, or Add/Remove
Programs. It stops the monitor, removes the scheduled task and every installed file, and
asks whether to keep your thresholds and alert history.

RTSS is deliberately left alone — it is a separate product with its own uninstaller, and
you may be using it for other things.

For a source checkout, `uninstall.ps1` does the equivalent. Full accounting in
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

## The tray icon

hw-sentinel puts an icon in the notification area, so it is something you can see and
control rather than an invisible background process. Right-click it for:

- **Pause / resume monitoring** — stops alerts appearing without stopping the watching;
  readings are still polled and events still logged
- **Snooze all alerts for 15 minutes**
- **Edit alert thresholds** — opens your `config.toml`
- **Open event log**, **Check setup**, **Quit**

The icon turns from grey to clay while an alert is active, and its tooltip names it.

> **Windows 11 hides new tray icons by default.** After installing, click the `^` chevron
> in the notification area and drag the hw-sentinel icon out onto the taskbar — otherwise
> it stays in the overflow. Nothing we can set from code changes that; it is the user's
> choice by design.

LibreHardwareMonitor and RTSS have tray icons of their own and there is no supported way
to suppress another program's icon. You can hide them individually under **Settings →
Personalisation → Taskbar → Other system tray icons**.

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
config.default.toml  shipped template; copied to your data folder on first run
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
