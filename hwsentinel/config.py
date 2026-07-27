"""Configuration loading and validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when config.toml is missing, malformed, or internally inconsistent."""


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
    root: Path
    source: SourceCfg = field(default_factory=SourceCfg)
    card: CardCfg = field(default_factory=CardCfg)
    rtss: RtssCfg = field(default_factory=RtssCfg)
    sound: SoundCfg = field(default_factory=SoundCfg)
    log: LogCfg = field(default_factory=LogCfg)
    sensors: dict[str, str] = field(default_factory=dict)
    rules: list[RuleCfg] = field(default_factory=list)

    def resolve(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

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
        root=path.parent.resolve(),
        source=_build(SourceCfg, _section(raw, "source"), "source"),
        card=_build(CardCfg, _section(raw, "card"), "card"),
        rtss=_build(RtssCfg, _section(raw, "rtss"), "rtss"),
        sound=_build(SoundCfg, _section(raw, "sound"), "sound"),
        log=_build(LogCfg, _section(raw, "log"), "log"),
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
