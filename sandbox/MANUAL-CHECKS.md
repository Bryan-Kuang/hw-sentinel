# Wizard checks (manual)

The silent suite (`hw-sentinel-tests.wsb`) covers installer *mechanics* — files, the
scheduled task, registry, cleanup. It cannot cover the wizard *pages*, because a silent
install skips every one of them.

Driving those pages with UI Automation was tried and abandoned: it stalled on the licence
page's accept radio and then fired keystrokes at a disabled **Next** button for the rest
of the run. Worse, several assertions *passed* while stuck, because a check whose
precondition never happened returned true. A test that reports green while blind is worse
than no test.

So the pages are checked by hand, in a throwaway sandbox, using this list.

## Setup

Open `sandbox\manual.wsb` — a clean Windows with the installer mapped in read-only and
nothing automated running. Inside, run `C:\sandbox\dist\hw-sentinel-setup-*.exe`.

Close the window when finished; everything inside is destroyed.

**Only run one thing at a time.** Do not leave an automated sandbox running while
clicking through another — they compete for the same wizard.

## Run 1 — first install

| Check | Expected | Verified |
|---|---|---|
| Folder page appears | It is shown on a first install | 2026-07-29 |
| **Dedicated subfolder rule** | Type a bare `C:\Apps`, press Next then Back: it now reads `C:\Apps\hw-sentinel` | 2026-07-29 |
| RTSS consent page | Explains what RTSS is, names the download URL, says what is lost by skipping, box unticked by default | **not yet** |

## Run 2 — run setup again

| Check | Expected | Verified |
|---|---|---|
| Mode page appears | Names the installed version and folder; offers keep-in-place or install-elsewhere; says Cancel leaves it alone | 2026-07-29 |
| Folder page skipped | When keeping it in place, the folder page does not appear | **not yet** |
| Relocate | Choosing a different folder installs there and **deletes the old folder** | 2026-07-29 |
| Cancel | Pressing Cancel on the mode page leaves the existing install untouched | **not yet** |

## Optional — RTSS download

Tick the RTSS box. Setup should download the archive, extract it, and open RTSS's own
installer. Getting that far proves `install-rtss.ps1` works; cancelling the vendor
installer afterwards is fine, and also exercises our failure path.

Needs the Guru3D mirror to be up. If it fails, check whether the mirror is reachable
before assuming the bug is ours.
