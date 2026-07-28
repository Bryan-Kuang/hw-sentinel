"""Configuration loading and validation.

Two roots matter, and conflating them breaks an installed copy:

* the *program* root holds code, assets and the bundled runtime. Under
  ``C:\\Program Files`` it is read-only for ordinary users.
* the *data* root holds the config the user edits and the event log. It has to be
  writable without administrator rights, and must survive an upgrade untouched.

In a development checkout the two are the same folder, which is why the distinction
went unnoticed until the installer work.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Folder containing the hwsentinel package — i.e. the install directory.
PROGRAM_ROOT = Path(__file__).resolve().parent.parent
APP_DIR_NAME = "hw-sentinel"
CONFIG_NAME = "config.toml"
DEFAULT_CONFIG_NAME = "config.default.toml"


class ConfigError(Exception):
    """Raised when config.toml is missing, malformed, or internally inconsistent."""


def program_data_root() -> Path:
    """%PROGRAMDATA%\\hw-sentinel — where an installed copy keeps user data."""
    base = os.environ.get("ProgramData") or os.environ.get("PROGRAMDATA")
    return Path(base) / APP_DIR_NAME if base else PROGRAM_ROOT


def config_search_path() -> list[Path]:
    """Where to look for config.toml, most specific first.

    The program-root entry is what keeps a development checkout working exactly as
    before: config.toml sits beside the package, so the data root becomes the project
    folder and nothing moves.
    """
    return [program_data_root() / CONFIG_NAME, PROGRAM_ROOT / CONFIG_NAME]


def find_config() -> Path | None:
    return next((p for p in config_search_path() if p.is_file()), None)


def ensure_config() -> Path:
    """Return a usable config path, seeding the user's copy on first run.

    The installer only ever writes config.default.toml, so an upgrade cannot clobber
    edited thresholds: this copies the default across once and then leaves it alone.
    """
    found = find_config()
    if found:
        return found

    template = PROGRAM_ROOT / DEFAULT_CONFIG_NAME
    if not template.is_file():
        raise ConfigError(
            "no config.toml found in any of: "
            + ", ".join(str(p) for p in config_search_path())
            + f"; and no template at {template}"
        )
    target = program_data_root() / CONFIG_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, target)
    except OSError as exc:
        raise ConfigError(f"cannot seed {target}: {exc}") from exc
    return target


@dataclass
class SourceCfg:
    url: str = "http://localhost:8085/data.json"
    poll_interval: float = 1.0
    timeout: float = 2.0


@dataclass
class CardCfg:
    enabled: bool = True
    position: str = "right-center"  # right-top | right-center | right-bottom
    margin_x: int = 24
    margin_y: int = 24
    width: int = 360
    height: int = 96
    gap: int = 8
    slide_ms: int = 180
    snooze_minutes: int = 15
    suppress_in_game: bool = True


@dataclass
class RtssCfg:
    enabled: bool = True
    owner: str = "hw-sentinel"
    # RTSS colour markup. Set false if your RTSS version renders the tags literally.
    markup: bool = True


@dataclass
class SoundCfg:
    enabled: bool = True
    critical_only: bool = False
    min_interval: float = 30.0
    warn_wav: str = "assets/warn.wav"
    critical_wav: str = "assets/critical.wav"


@dataclass
class LogCfg:
    enabled: bool = True
    path: str = "events.jsonl"


@dataclass
class DepsCfg:
    """Launching LibreHardwareMonitor and RTSS ourselves.

    With this on, hw-sentinel is the only thing Windows needs to start: the children
    inherit its elevated token, so LHM gets the administrator rights it needs to read
    sensors without a second scheduled task or a second UAC prompt.
    """

    manage: bool = True
    lhm_path: str = ""     # blank = search
    rtss_path: str = ""    # blank = search; not finding RTSS is not an error
    start_timeout: float = 25.0


@dataclass
class RuleCfg:
    key: str
    title: str
    op: str
    value: float
    clear_at: float
    enabled: bool = True
    sensor: str | None = None
    expr: str | None = None
    dwell: float = 10.0
    clear_dwell: float = 15.0
    cooldown: float = 60.0
    severity: str = "warn"
    unit: str = ""
    label: str = ""

    @property
    def is_derived(self) -> bool:
        return self.expr is not None


@dataclass
class Config:
    data_root: Path
    program_root: Path = PROGRAM_ROOT
    source: SourceCfg = field(default_factory=SourceCfg)
    card: CardCfg = field(default_factory=CardCfg)
    rtss: RtssCfg = field(default_factory=RtssCfg)
    sound: SoundCfg = field(default_factory=SoundCfg)
    log: LogCfg = field(default_factory=LogCfg)
    deps: DepsCfg = field(default_factory=DepsCfg)
    sensors: dict[str, str] = field(default_factory=dict)
    rules: list[RuleCfg] = field(default_factory=list)

    def resolve_program(self, relative: str) -> Path:
        """For files shipped with the program: sounds, the bundled runtime."""
        p = Path(relative)
        return p if p.is_absolute() else self.program_root / p

    def resolve_data(self, relative: str) -> Path:
        """For files the user owns: the event log. Must be writable unelevated."""
        p = Path(relative)
        return p if p.is_absolute() else self.data_root / p

    @property
    def enabled_rules(self) -> list[RuleCfg]:
        return [r for r in self.rules if r.enabled]


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _build(cls, data: dict, name: str):
    """Instantiate a dataclass from a config table, rejecting unknown keys early.

    Typos in a config file are otherwise silent and produce baffling behaviour, so
    an unknown key is a hard error rather than something to shrug off.
    """
    known = {f.name for f in cls.__dataclass_fields__.values()}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[{name}] has unknown key(s): {', '.join(sorted(unknown))}")
    return cls(**data)


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    cfg = Config(
        data_root=path.parent.resolve(),
        source=_build(SourceCfg, _section(raw, "source"), "source"),
        card=_build(CardCfg, _section(raw, "card"), "card"),
        rtss=_build(RtssCfg, _section(raw, "rtss"), "rtss"),
        sound=_build(SoundCfg, _section(raw, "sound"), "sound"),
        log=_build(LogCfg, _section(raw, "log"), "log"),
        deps=_build(DepsCfg, _section(raw, "deps"), "deps"),
        sensors=dict(_section(raw, "sensors")),
    )

    for key, body in _section(raw, "rules").items():
        if not isinstance(body, dict):
            raise ConfigError(f"[rules.{key}] must be a table")
        body = dict(body)
        body.setdefault("title", key.replace("_", " ").capitalize())
        body.setdefault("label", key)
        missing = {"op", "value", "clear_at"} - set(body)
        if missing:
            raise ConfigError(f"[rules.{key}] missing required key(s): {', '.join(sorted(missing))}")
        cfg.rules.append(_build(RuleCfg, {"key": key, **body}, f"rules.{key}"))

    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.source.poll_interval <= 0:
        raise ConfigError("source.poll_interval must be > 0")
    if cfg.card.position not in ("right-top", "right-center", "right-bottom"):
        raise ConfigError("card.position must be right-top, right-center, or right-bottom")

    seen: set[str] = set()
    for rule in cfg.rules:
        where = f"[rules.{rule.key}]"
        if rule.key in seen:
            raise ConfigError(f"{where} duplicate rule key")
        seen.add(rule.key)

        if rule.op not in (">", "<"):
            raise ConfigError(f"{where} op must be '>' or '<'")
        if rule.severity not in ("warn", "critical"):
            raise ConfigError(f"{where} severity must be 'warn' or 'critical'")
        if (rule.sensor is None) == (rule.expr is None):
            raise ConfigError(f"{where} needs exactly one of 'sensor' or 'expr'")

        # Hysteresis only works if the clear point sits on the safe side of the trip
        # point. Getting this backwards makes a rule that can never clear.
        if rule.op == ">" and rule.clear_at > rule.value:
            raise ConfigError(f"{where} clear_at ({rule.clear_at}) must be <= value ({rule.value}) for op '>'")
        if rule.op == "<" and rule.clear_at < rule.value:
            raise ConfigError(f"{where} clear_at ({rule.clear_at}) must be >= value ({rule.value}) for op '<'")

        for name in ("dwell", "clear_dwell", "cooldown"):
            if getattr(rule, name) < 0:
                raise ConfigError(f"{where} {name} must be >= 0")

        if rule.sensor and rule.sensor not in cfg.sensors:
            raise ConfigError(f"{where} sensor '{rule.sensor}' is not defined in [sensors]")
