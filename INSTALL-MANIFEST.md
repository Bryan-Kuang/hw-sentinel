# Install manifest

Exactly what this project puts on the machine, and how to undo it.

**Design rule: everything lives inside this folder.** There is no system Python, no winget
package, no Program Files directory, no PATH entry, no service, no driver, and nothing in
`site-packages`. Deleting the folder removes the whole runtime.

Three exceptions exist and are listed in [Outside this folder](#outside-this-folder).

## Inside this folder

```
hw-sentinel\
  runtime\
    python\      private CPython 3.12.10 (embeddable) + tkinter
    lhm\         LibreHardwareMonitor 0.9.6, web server pre-enabled on :8085
    rtss\        RivaTuner Statistics Server 7.3.7, run portably
    _cache\      downloaded artifacts, safe to delete after bootstrap
  hwsentinel\    the application
  assets\        generated alert sounds
  state\         event log
  config.toml    thresholds and sensor mappings
```

`bootstrap.ps1` builds `runtime\` from scratch. It downloads over HTTPS from official
upstreams and verifies each artifact against a pinned SHA-256; a mismatch aborts.

| Artifact | Source | SHA-256 |
|---|---|---|
| `python-3.12.10-embed-amd64.zip` | python.org | `4ACBED6D…25A3C3` |
| `tcltk.msi` | python.org | `55C96FFA…276E2A` |
| `LibreHardwareMonitor.zip` | GitHub releases | `086D9F1B…29C001` |

The embeddable Python deliberately omits tkinter, so the card would not render. Its files
come from the official `tcltk` component, unpacked with `msiexec /a` — an administrative
install, which extracts files **without registering the product** anywhere.

RTSS has no portable distribution. `bootstrap.ps1` copies an installed tree into
`runtime\rtss\`; it then runs from there with no system install present.

## Outside this folder

Three things, all removed by `uninstall.ps1`.

### 1. Scheduled tasks (3)

`hw-sentinel`, `hw-sentinel-lhm`, `hw-sentinel-rtss` — created by `install.ps1`, all
pointing at `runtime\`. They run at logon "with highest privileges", which is what lets
LibreHardwareMonitor get the administrator rights it needs for CPU temperature and voltage
without a UAC prompt on every boot.

### 2. `HKCU\Software\Unwinder\RTSS`

RTSS writes its own settings here whenever it runs. This is the one thing that cannot be
contained: RTSS is portable in every other respect, but not in this. `uninstall.ps1`
deletes the key (pass `-KeepRtssSettings` to keep it).

### 3. Transient hooking

While running, RTSS injects `RTSSHooks64.dll` into 3D applications — that is how it draws
inside a game. Nothing persists after it exits.

## What is *not* disposable

**LibreHardwareMonitor and RTSS are runtime dependencies, not build tools.** LHM *is* the
sensor source — without it nothing is read and no alert can fire. RTSS is what draws inside
an exclusive-fullscreen game; without it the card, the sound, and windowed/borderless games
all still work. Neither is scaffolding to clean up after development; they come off when you
stop using hw-sentinel, which `uninstall.ps1` does in one step.

## Removing everything

```bash
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIf
```

| Command | Effect |
|---|---|
| `uninstall.ps1` | Stops everything started from here, removes the three scheduled tasks and the RTSS registry key. Leaves the folder. |
| `uninstall.ps1 -RemoveProject` | The above, plus deletes this folder — which is the entire runtime. |
| `uninstall.ps1 -KeepRtssSettings` | Leaves `HKCU\Software\Unwinder` alone. |

Run it from an elevated PowerShell so it can remove the scheduled tasks.

## Notes on removing a system-wide RTSS

If you installed RTSS normally in order to seed `runtime\rtss\`, removing the system copy
afterwards has two quirks worth knowing:

- Its uninstaller is NSIS. Run it with `/S` for a genuinely silent removal — without that
  flag it opens a language-selection dialog that looks exactly like an installer.
- It cannot delete `RTSSHooks64.dll` while that DLL is still injected into running
  processes, so it leaves a `_RebootPending_` marker and asks for a restart. After the
  restart the files are gone and the empty folder can be deleted.

Neither RTSS nor LibreHardwareMonitor leaves a service, a driver, or a `Run` key behind.
