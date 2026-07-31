A hardware monitor that stays invisible until something is actually wrong.

## Install

Download **hw-sentinel-setup-1.1.0.exe** and run it.

> **Windows will warn you.** The installer is unsigned, so SmartScreen shows
> "Windows protected your PC" - click **More info -> Run anyway**. Clearing that
> warning properly needs a paid code-signing certificate. Verify the checksum below
> if you would rather check first.
>
> `SHA-256: A7155AB0FF957810E06EB81C84BAD83F6C4C1A085FAE42D01C56396DD971CFEC`

After installing, run **Check hw-sentinel setup** from the Start menu. Sensor names
differ between machines, and it tells you if any rule needs its sensor corrected.

## What is new in 1.1.0

**A real installer.** A wizard, an entry in Settings > Apps, and an uninstaller that
removes every file, the scheduled task, and - if you want - your settings. Installing
over an existing copy asks first, and offers either to upgrade in place or to install
to a different folder and delete the old one. Whatever folder you choose, it always
installs into a subfolder of its own.

**One autostart entry instead of three.** hw-sentinel now launches
LibreHardwareMonitor and RTSS itself. They inherit its elevated token, so
LibreHardwareMonitor gets the rights it needs to read sensors with no UAC prompt at
boot. An already-running copy is adopted, never duplicated.

**Your settings survive upgrades.** Thresholds live in
`%ProgramData%\hw-sentinel\config.toml`, editable without administrator rights, and
are never overwritten by an update.

**Uninstall offers to clean up RTSS.** If setup installed RTSS and nothing else on the
machine appears to use it, uninstall says so and offers to remove it - rather than
leaving behind a program you never chose. It always defaults to keeping it.

## Fixes

- An alert on a fast-moving sensor could hold for minutes after the value had
  recovered. The recovery timer required an unbroken run below the clear point, which
  a voltage rail crossing that point several times a second could never achieve.
- An alert sitting between the clear point and the trip point described itself as
  "recovered" while staying on screen. There are three states, so there are now three
  messages, and the last one counts down to dismissal.
- Alert text picks its decimals from the unit, so voltages no longer print as
  `1.1V over 1.1V`.
- Upgrading over a running copy now replaces every file and restarts monitoring, with
  nothing deferred to a reboot.
- RTSS is found wherever it was installed, not only in the default folder.
- Fixed a startup race that could launch two copies of LibreHardwareMonitor, and a
  liveness check that could never report RTSS as stopped.
- A config file saved with a byte-order mark - what Notepad writes - no longer fails
  to load.

## In-game alerts are optional

Drawing inside an exclusive-fullscreen game needs RivaTuner Statistics Server, which
is proprietary freeware we are not permitted to bundle. Setup asks first, naming the
download URL, and runs RTSS's own installer visibly.

Skip it and everything else still works: the desktop card, alerts in windowed games,
and the alert sound - which you hear inside full-screen games too.

## Requirements

Windows 10 or 11, 64-bit. Everything else, Python included, is bundled or fetched by
setup.
