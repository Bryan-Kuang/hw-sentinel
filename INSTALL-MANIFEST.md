# Install manifest

Exactly what this project puts on the machine, and how to undo it.

Program files and user data are deliberately separate, because an installed copy lives in
a read-only location while your thresholds must stay editable and survive upgrades.

| | Path | Notes |
|---|---|---|
| Program | `C:\Program Files\hw-sentinel` | Read-only. Removed entirely on uninstall. |
| User data | `C:\ProgramData\hw-sentinel` | `config.toml`, `events.jsonl`. Writable without admin. Uninstall asks before removing. |
| Autostart | Scheduled task `hw-sentinel` | The only thing outside those two folders. |

## What is inside the install folder

```
C:\Program Files\hw-sentinel\
  runtime\python\   private CPython 3.12 + tkinter (no registry, no PATH)
  runtime\lhm\      LibreHardwareMonitor, web server pre-enabled on :8085
  hwsentinel\       the application
  assets\           alert sounds
  config.default.toml   template; copied to ProgramData on first run
```

There is **no system Python, no package-manager entry, nothing on PATH, nothing in
site-packages, no service and no driver**.

RTSS is not here: it cannot be redistributed. See [RTSS](#rtss) below.

## What is outside the install folder

Three things, all handled by the uninstaller.

### 1. One scheduled task

`hw-sentinel`, at logon, "run with highest privileges". LibreHardwareMonitor needs
administrator rights to read CPU temperature and voltage, and that flag is what avoids a
UAC prompt on every boot. hw-sentinel launches LHM and RTSS itself as child processes,
which inherit the elevated token — so one task covers all three.

Earlier versions registered three tasks. `install.ps1` removes those on upgrade.

### 2. `%ProgramData%\hw-sentinel`

Your `config.toml` and `events.jsonl`. Granted modify permission at install time so you
can edit thresholds without elevation. The uninstaller asks before deleting it; the
default is to keep it.

### 3. `HKCU\Software\Unwinder\RTSS`

Written by RTSS itself whenever it runs. The one thing that cannot be contained.

## RTSS

RivaTuner Statistics Server is proprietary freeware. **It is not bundled**, and
`packaging\build.ps1` fails the build if any RTSS file reaches the payload.

Setup asks, on a page that names the exact download URL, whether to fetch it from the
official Guru3D mirror. If you agree, RTSS's own installer runs visibly so you can see
what is being installed and cancel it. Declining costs only the on-screen text inside
exclusive-fullscreen games — the desktop card, windowed games, and the alert sound all
work regardless.

The uninstaller never removes RTSS.

## Bundled third-party components

Fetched from official sources by `bootstrap.ps1`, each verified against a pinned SHA-256.

| Component | Licence | Notes |
|---|---|---|
| CPython (embeddable) + Tcl/Tk | PSF | `LICENSE.txt` ships alongside |
| LibreHardwareMonitor | MPL-2.0 | Licence text fetched from the project and shipped; unmodified |
| RivaTuner Statistics Server | Proprietary | **Not bundled** — downloaded on consent |

The embeddable Python build omits tkinter, so the card could not render. Its files come
from the official `tcltk` component, unpacked with `msiexec /a` — an administrative
install, which extracts files without registering the product anywhere.

## Removing everything

**Settings → Apps → hw-sentinel → Uninstall.** That stops the monitor, removes the task
and every installed file, and asks about your data.

From a source checkout instead:

```bash
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIf
```

## Notes on removing a system-wide RTSS

If you installed RTSS separately and later want it gone:

- Its uninstaller is NSIS. Run it with `/S` for a genuinely silent removal — without that
  flag it opens a language-selection dialog that looks exactly like an installer.
- It cannot delete `RTSSHooks64.dll` while that DLL is still injected into running
  processes, so it leaves a `_RebootPending_` marker and asks for a restart. After the
  restart the files are gone and the empty folder can be deleted.

Neither RTSS nor LibreHardwareMonitor leaves a service, a driver, or a `Run` key behind.
