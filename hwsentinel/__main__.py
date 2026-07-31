"""hw-sentinel CLI: doctor | discover | run | test."""

from __future__ import annotations

import argparse
import ctypes
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

from . import APP_NAME, __version__
from .config import Config, ConfigError, ensure_config, load
from .deps import DepSupervisor
from .rules import Alert, Event, EventKind, RuleEngine, expr_aliases
from .sink_card import ACCENT, CardManager
from .sink_log import LogSink
from .sink_rtss import RtssSink
from .sink_sound import SoundSink
from .source_lhm import LhmSource, SourceError, grouped
from .tray import TrayIcon



def say(*args) -> None:
    """print() that survives being run under pythonw, where stdout may be absent.

    Flushed: this process does ctypes work against shared memory, and buffered output
    is lost if that ever faults — which makes the crash far harder to place.
    """
    try:
        print(*args, flush=True)
    except (AttributeError, OSError, ValueError):
        pass


def set_dpi_aware() -> None:
    """Without this the card renders blurry on a scaled display."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def rtss_text(alerts: list[Alert], markup: bool) -> str:
    lines = []
    for a in sorted(alerts, key=lambda x: (x.severity != "critical", x.key)):
        if markup:
            colour = ACCENT.get(a.severity, ACCENT["warn"]).lstrip("#")
            lines.append(f"<C0={colour}><C0>{a.title}<C>  {a.detail}")
        else:
            lines.append(f"{a.title}  {a.detail}")
    if not lines:
        return ""
    # Lead with a newline so the alert starts on its own row rather than the very top
    # of the screen, where other overlays (Steam's FPS counter, RTSS's own stats) draw
    # by default. They are separate renderers that know nothing about each other, so
    # sharing row 0 just means whichever draws last hides the other — in practice it
    # clipped the start of the alert title.
    return "\n" + "\n".join(lines)


class Supervisor:
    """Owns the poll thread and fans events out to the sinks on the tk thread."""

    def __init__(self, cfg: Config, cfg_path: str = "") -> None:
        self.cfg = cfg
        self.cfg_path = cfg_path or str(cfg.data_root / "config.toml")
        self.source = LhmSource(cfg.source.url, cfg.source.timeout)
        self.engine = RuleEngine(cfg)
        self.sound = SoundSink(cfg)
        self.log = LogSink(cfg)
        self.rtss = RtssSink(cfg.rtss)
        self.deps = DepSupervisor(cfg)
        self.tray: TrayIcon | None = None
        self.paused = False
        self.queue: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.source_error = ""
        self._last_source_error = ""

        set_dpi_aware()
        self.root = tk.Tk()
        self.root.withdraw()
        self.cards = CardManager(cfg.card, self.root, on_snooze=self._snooze)

    def _snooze(self, key: str) -> None:
        self.engine.snooze(key, self.cfg.card.snooze_minutes)
        say(f"snoozed {key} for {self.cfg.card.snooze_minutes} min")

    # -- background polling ---------------------------------------------------

    def poll_loop(self) -> None:
        while not self.stop.is_set():
            started = time.time()
            try:
                readings = self.source.poll()
                events = self.engine.update(readings)
                self.queue.put(("ok", events, self.engine.active))
            except SourceError as exc:
                self.queue.put(("error", str(exc), []))
                # A dead sensor source is usually a dead LibreHardwareMonitor, and
                # this is the one place that can put it back on its feet.
                self.deps.heartbeat()
            self.stop.wait(max(0.05, self.cfg.source.poll_interval - (time.time() - started)))

    # -- tk-thread pump -------------------------------------------------------

    def pump(self) -> None:
        if self.stop.is_set():
            self.shutdown()
            return

        alerts: list[Alert] | None = None
        try:
            while True:
                status, payload, active = self.queue.get_nowait()
                if status == "error":
                    self.source_error = payload
                    if payload != self._last_source_error:
                        say(f"[source] {payload}")
                        self._last_source_error = payload
                    alerts = []
                else:
                    self.source_error = ""
                    self._last_source_error = ""
                    for event in payload:
                        self._on_event(event)
                    alerts = active
        except queue.Empty:
            pass

        if alerts is not None:
            # Paused means show nothing, but keep polling and keep logging - the point
            # is to stop being interrupted, not to stop watching.
            self._render([] if self.paused else alerts)
            if self.tray:
                summary = alerts[0].title if alerts else ""
                self.tray.update(len(alerts), self.paused, summary)

        self._drain_tray()
        self.root.after(100, self.pump)

    def _drain_tray(self) -> None:
        if not self.tray:
            return
        try:
            while True:
                cmd = self.tray.commands.get_nowait()
                self._on_tray_command(cmd)
        except queue.Empty:
            pass

    def _on_tray_command(self, cmd: str) -> None:
        if cmd == "toggle-pause":
            self.paused = not self.paused
            say(f"[tray] monitoring {'paused' if self.paused else 'resumed'}")
            if self.paused:
                self.cards.update([])
                self.rtss.clear()
        elif cmd == "snooze-all":
            minutes = self.cfg.tray.snooze_minutes
            for key in self.engine.states:
                self.engine.snooze(key, minutes)
            self.cards.update([])
            self.rtss.clear()
            say(f"[tray] all rules snoozed for {minutes} min")
        elif cmd == "settings":
            self._open(Path(self.cfg_path))
        elif cmd == "log":
            path = self.log.path
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")   # nothing to show yet is still an answer
            self._open(path)
        elif cmd == "doctor":
            launcher = self.cfg.program_root / "hw-sentinel.cmd"
            if launcher.exists():
                subprocess.Popen(["cmd", "/c", "start", "", str(launcher), "doctor"], shell=False)
        elif cmd == "exit":
            say("[tray] quit requested")
            self.stop.set()

    @staticmethod
    def _open(path: Path) -> None:
        try:
            os.startfile(str(path))          # whatever the user has associated
        except OSError:
            subprocess.Popen(["notepad.exe", str(path)])

    def _on_event(self, event: Event) -> None:
        self.log.write(event)
        if event.kind is EventKind.TRIP:
            a = event.alert
            say(f"[TRIP {a.severity}] {a.title} — {a.detail}")
            self.sound.play(a.severity, a.key)
        elif event.kind is EventKind.CLEAR:
            say(f"[clear] {event.alert.key}")

    def _render(self, alerts: list[Alert]) -> None:
        shown_in_game = False
        if self.cfg.rtss.enabled:
            self.rtss.ensure_attached()
            if self.rtss.attached:
                in_game = self.rtss.in_game()
                if alerts and in_game:
                    shown_in_game = self.rtss.show(rtss_text(alerts, self.cfg.rtss.markup))
                else:
                    self.rtss.clear()

        # Suppress the desktop card only when the alert is definitely visible in-game,
        # so a failed RTSS write can never leave the alert invisible everywhere.
        self.cards.update(alerts, suppressed=shown_in_game and self.cfg.card.suppress_in_game)

    def shutdown(self) -> None:
        self.stop.set()
        try:
            self.rtss.close()
        except OSError:
            pass
        self.deps.stop()
        if self.tray:
            self.tray.stop()
        self.cards.destroy_all()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> int:
        def on_signal(_sig, _frm):
            self.stop.set()

        try:
            signal.signal(signal.SIGINT, on_signal)
            signal.signal(signal.SIGTERM, on_signal)
        except ValueError:
            pass

        # Dependencies first, and only then the poll thread. Starting the thread first
        # raced: it polled before LibreHardwareMonitor existed, hit the failure path,
        # and launched LHM — while this thread was launching it too. Two copies.
        if self.cfg.tray.enabled:
            self.tray = TrayIcon(
                self.cfg.resolve_program(self.cfg.tray.idle_icon),
                self.cfg.resolve_program(self.cfg.tray.alert_icon),
            )
            if self.tray.start():
                say("tray icon ready")
            else:
                # Losing the icon must not cost you the monitoring.
                say(f"tray icon unavailable: {self.tray.last_error or 'unknown'}")
                self.tray = None

        say(f"{APP_NAME} {__version__} starting — bringing up dependencies...")
        for st in self.deps.start().values():
            say(f"  {st.name}: {st.describe()}")

        thread = threading.Thread(target=self.poll_loop, name="poll", daemon=True)
        thread.start()

        say(f"{APP_NAME} {__version__} running — {len(self.cfg.enabled_rules)} rules, "
            f"polling every {self.cfg.source.poll_interval:g}s. Ctrl+C to stop.")
        self.root.after(100, self.pump)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()
        return 0


# -- subcommands --------------------------------------------------------------


def cmd_discover(cfg: Config, args) -> int:
    source = LhmSource(cfg.source.url, cfg.source.timeout)
    try:
        readings = source.poll()
    except SourceError as exc:
        say(f"error: {exc}")
        return 1

    needle = (args.filter or "").lower()
    shown = 0
    for hardware, items in grouped(readings):
        rows = [r for r in items if not needle or needle in r.path.lower() or needle in r.name.lower()]
        if not rows:
            continue
        say(f"\n=== {hardware} ===")
        for r in rows:
            say(f"  {r.value:>10.2f} {r.unit:<4}  {r.path}")
            shown += 1
    say(f"\n{shown} sensor(s). Copy a path into the [sensors] table of config.toml;")
    say("a unique suffix or substring is enough, the full path is not required.")
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    ok = True
    say(f"{APP_NAME} {__version__}")
    say(f"config:  {args.config}")
    say(f"program: {cfg.program_root}")
    say(f"data:    {cfg.data_root}\n")

    # Discovery first: when an installed copy misbehaves, "which dependency did it
    # find, and did it start?" is almost always the answer.
    say("[1/6] Dependencies")
    deps = DepSupervisor(cfg)
    say(f"      deps.manage = {str(cfg.deps.manage).lower()}")
    for which, label in (("lhm", "LibreHardwareMonitor"), ("rtss", "RTSS")):
        found = deps.find(which)
        alive = deps.lhm_alive() if which == "lhm" else deps.rtss_alive()
        state = "running" if alive else "not running"
        say(f"      {label:<21} {state:<12} {found or 'NOT FOUND'}")
        if which == "lhm" and not found and not alive:
            ok = False

    say(f"\n[2/6] LibreHardwareMonitor  {cfg.source.url}")
    readings = {}
    try:
        readings = LhmSource(cfg.source.url, cfg.source.timeout).poll()
        say(f"      OK — {len(readings)} sensors")
        zeros = sum(1 for r in readings.values() if r.value == 0.0)
        if zeros > len(readings) * 0.6:
            say(f"      WARNING: {zeros}/{len(readings)} sensors read 0.00 — LHM is probably not elevated")
    except SourceError as exc:
        say(f"      FAIL — {exc}")
        ok = False

    say("\n[3/6] Sensors referenced by rules")
    if readings:
        engine = RuleEngine(cfg)
        for rule in cfg.enabled_rules:
            aliases = expr_aliases(rule.expr) if rule.expr else [rule.sensor]
            try:
                value, unit = engine.measure(rule, readings)
                say(f"      OK   {rule.key:<22} = {value:.2f}{unit}  ({', '.join(aliases)})")
            except SourceError as exc:
                say(f"      FAIL {rule.key:<22} {exc}")
                ok = False
    else:
        say("      skipped (no sensor data)")

    say("\n[4/6] RTSS shared memory")
    rtss = RtssSink(cfg.rtss)
    if not cfg.rtss.enabled:
        say("      disabled in config")
    elif rtss.attach():
        say(f"      OK — shared memory v{rtss.version}, in-game: {rtss.in_game()}")
        rtss.close()
    else:
        say(f"      FAIL — {rtss.last_error}")
        say("      (in-game alerts will not work; desktop card and sound still will)")
        ok = False

    say("\n[5/6] Alert sounds")
    sound = SoundSink(cfg)
    missing = sound.missing()
    if missing:
        say("      FAIL — missing: " + ", ".join(str(p) for p in missing))
        say("      run: py -3 generate_assets.py")
        ok = False
    else:
        say("      OK — playing warn chime")
        sound.play("warn", "doctor")
        time.sleep(1.0)

    say("\n[6/6] Overlay window")
    try:
        set_dpi_aware()
        root = tk.Tk()
        root.withdraw()
        say(f"      OK — screen {root.winfo_screenwidth()}x{root.winfo_screenheight()}")
        root.destroy()
    except tk.TclError as exc:
        say(f"      FAIL — {exc}")
        ok = False

    say("\n" + ("all checks passed" if ok else "some checks failed (see above)"))
    return 0 if ok else 1


def cmd_test(cfg: Config, args) -> int:
    rule = next((r for r in cfg.rules if r.key == args.rule), None)
    if rule is None:
        say(f"unknown rule '{args.rule}'. Available: " + ", ".join(r.key for r in cfg.rules))
        return 1

    sup = Supervisor(cfg, args.config)
    started = time.time()
    # Overshoot proportionally: a fixed offset reads as nonsense on a voltage rule
    # (1.30 V + 2 = 3.3 V), where 5% past the threshold looks like a real reading.
    margin = max(abs(rule.value) * 0.05, 0.02)
    alert = Alert(
        key=rule.key,
        title=rule.title,
        severity=rule.severity,
        detail="",
        value=rule.value + (margin if rule.op == ">" else -margin),
        unit=rule.unit or "",
        since=started,
    )
    sup.sound.play(alert.severity, alert.key)
    say(f"simulating '{rule.key}' ({rule.severity}) for {args.seconds}s — "
        f"RTSS attached: {sup.rtss.ensure_attached()}")

    def tick() -> None:
        held = int(time.time() - started)
        if held >= args.seconds:
            sup.stop.set()
            sup.shutdown()
            return
        arrow = "over" if rule.op == ">" else "under"
        alert.detail = f"{rule.label} {alert.value:.1f}{alert.unit} · {arrow} {rule.value:g}{alert.unit} for {held}s"
        sup._render([alert])
        sup.root.after(250, tick)

    sup.root.after(10, tick)
    try:
        sup.root.mainloop()
    finally:
        sup.shutdown()
    say("done")
    return 0


def cmd_run(cfg: Config, args) -> int:
    return Supervisor(cfg, args.config).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hwsentinel", description=__doc__)
    parser.add_argument(
        "--config",
        help="path to config.toml (default: %ProgramData%\\hw-sentinel, then the "
        "copy beside the program, seeding from config.default.toml if neither exists)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="monitor continuously and alert on abnormal readings")
    sub.add_parser("doctor", help="check every dependency and config sensor")

    p_discover = sub.add_parser("discover", help="list every sensor LHM exposes")
    p_discover.add_argument("--filter", help="only show sensors matching this text")

    p_test = sub.add_parser("test", help="force an alert to verify the sinks")
    p_test.add_argument("--rule", required=True, help="rule key to simulate")
    p_test.add_argument("--seconds", type=int, default=10)

    args = parser.parse_args(argv)

    try:
        config_path = Path(args.config) if args.config else ensure_config()
        cfg = load(config_path)
    except ConfigError as exc:
        say(f"config error: {exc}")
        return 2
    args.config = str(config_path)

    return {"run": cmd_run, "doctor": cmd_doctor, "discover": cmd_discover, "test": cmd_test}[
        args.command
    ](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
