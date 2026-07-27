"""Offline checks for the parsing and state-machine logic (no LHM/RTSS needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hwsentinel.config import Config, ConfigError, RuleCfg, load
from hwsentinel.rules import EventKind, RuleEngine, eval_expr, expr_aliases
from hwsentinel.source_lhm import Reading, SensorResolver, SourceError, flatten, parse_value

fails = []


def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(extra) if extra and not cond else ''}")
    if not cond:
        fails.append(name)


# --- value parsing (locale variants) -----------------------------------------
check("parse plain", parse_value("62.5 Â°C") == (62.5, "Â°C"))
check("parse comma decimal", parse_value("62,5 Â°C") == (62.5, "Â°C"))
check("parse grouped", parse_value("1,234.5 MHz") == (1234.5, "MHz"))
check("parse volts", parse_value("1.234 V") == (1.234, "V"))
check("parse blank", parse_value("") is None)
check("parse dash", parse_value("-") is None)

# --- tree flattening ----------------------------------------------------------
TREE = {
    "Text": "Sensor",
    "Children": [
        {"Text": "AMD Ryzen 7 9800X3D", "Children": [
            {"Text": "Temperatures", "Children": [
                {"Text": "Core (Tctl/Tdie)", "Value": "45.2 Â°C", "Children": []},
            ]},
            {"Text": "Voltages", "Children": [
                {"Text": "Core (SVI2 TFN)", "Value": "1.108 V", "Children": []},
                {"Text": "SoC (SVI2 TFN)", "Value": "1.205 V", "Children": []},
            ]},
        ]},
        {"Text": "AMD Radeon RX 9070 XT", "Children": [
            {"Text": "Temperatures", "Children": [
                {"Text": "GPU Core", "Value": "48.0 Â°C", "Children": []},
                {"Text": "GPU Hot Spot", "Value": "61.0 Â°C", "Children": []},
            ]},
            {"Text": "Voltages", "Children": [
                {"Text": "GPU Core", "Value": "0.812 V", "Children": []},
            ]},
        ]},
    ],
}
R = flatten(TREE)
check("flatten count", len(R) == 6, len(R))
check("flatten slug", "amd-ryzen-7-9800x3d/temperatures/core-tctl-tdie" in R, sorted(R))
check("flatten value", R["amd-radeon-rx-9070-xt/temperatures/gpu-hot-spot"].value == 61.0)

# --- resolver ------------------------------------------------------------------
res = SensorResolver({"hot": "temperatures/gpu-hot-spot", "gpuv": "voltages/gpu-core"})
check("resolve suffix", res.resolve("hot", R).value == 61.0)
check("resolve disambiguates group", res.resolve("gpuv", R).value == 0.812)
try:
    SensorResolver({"amb": "gpu-core"}).resolve("amb", R)
    check("ambiguous pattern rejected", False)
except SourceError as e:
    check("ambiguous pattern rejected", "ambiguous" in str(e))
try:
    SensorResolver({"nope": "does-not-exist"}).resolve("nope", R)
    check("missing pattern rejected", False)
except SourceError:
    check("missing pattern rejected", True)

# --- expression evaluator -------------------------------------------------------
check("eval arithmetic", eval_expr("a - b", {"a": 61.0, "b": 48.0}) == 13.0)
check("eval aliases", expr_aliases("gpu_hotspot - gpu_core_temp") == ["gpu_core_temp", "gpu_hotspot"])
for bad in ("__import__('os').system('x')", "open('f')", "a.b"):
    try:
        eval_expr(bad, {"a": 1})
        check(f"reject {bad[:20]}", False)
    except SourceError:
        check(f"reject {bad[:20]}", True)

# --- rule engine ----------------------------------------------------------------
def mk_cfg(**over):
    base = dict(key="t", title="T", label="Tctl", sensor="cpu", unit="C",
                op=">", value=88.0, clear_at=83.0, dwell=10.0, clear_dwell=15.0, cooldown=60.0)
    base.update(over)
    return Config(root=Path("."), sensors={"cpu": "core-tctl-tdie"}, rules=[RuleCfg(**base)])


def reading(v):
    return {"amd-ryzen-7-9800x3d/temperatures/core-tctl-tdie":
            Reading("amd-ryzen-7-9800x3d/temperatures/core-tctl-tdie", "Core (Tctl/Tdie)",
                    "AMD Ryzen 7 9800X3D", "Temperatures", v, "Â°C")}


def kinds(events):
    return [e.kind for e in events]


eng = RuleEngine(mk_cfg())
t = 1000.0
check("spike below dwell does not trip",
      not any(kinds(eng.update(reading(95.0), t + i)) for i in range(0, 9)))
check("trips after dwell", kinds(eng.update(reading(95.0), t + 11)) == [EventKind.TRIP])
check("holds while hot", kinds(eng.update(reading(95.0), t + 12)) == [EventKind.UPDATE])

# Hysteresis: below trip point but above clear point must NOT clear.
check("no clear between clear_at and value",
      kinds(eng.update(reading(85.0), t + 13)) == [EventKind.UPDATE])
check("still tripped at 84", kinds(eng.update(reading(84.0), t + 14)) == [EventKind.UPDATE])
eng.update(reading(80.0), t + 15)                      # enters CLEARING
check("clear needs clear_dwell", kinds(eng.update(reading(80.0), t + 20)) == [EventKind.UPDATE])
check("clears after clear_dwell", kinds(eng.update(reading(80.0), t + 31)) == [EventKind.CLEAR])

# Cooldown blocks an immediate re-trip.
for i in range(40, 55):
    eng.update(reading(95.0), t + i)
check("cooldown blocks re-trip", eng.active == [])
for i in range(95, 120):
    ev = kinds(eng.update(reading(95.0), t + i))
    if EventKind.TRIP in ev:
        break
check("re-trips after cooldown", len(eng.active) == 1)

# Snooze clears an active alert.
eng.snooze("t", 5)
check("snooze clears", any(k is EventKind.CLEAR for k in kinds(eng.update(reading(95.0), t + 130))))

# Derived expression rule.
eng2 = RuleEngine(Config(
    root=Path("."),
    sensors={"hot": "temperatures/gpu-hot-spot", "core": "temperatures/gpu-core"},
    rules=[RuleCfg(key="d", title="D", label="Delta", expr="hot - core", unit="Â°C",
                   op=">", value=25.0, clear_at=20.0, dwell=0.0, clear_dwell=0.0, cooldown=0.0)],
))
check("expr rule reads both sensors", kinds(eng2.update(R, 2000.0)) == [])
HOT = dict(R)
HOT["amd-radeon-rx-9070-xt/temperatures/gpu-hot-spot"] = Reading(
    "amd-radeon-rx-9070-xt/temperatures/gpu-hot-spot", "GPU Hot Spot",
    "AMD Radeon RX 9070 XT", "Temperatures", 80.0, "Â°C")
check("expr rule trips on delta", kinds(eng2.update(HOT, 2001.0)) == [EventKind.TRIP])

# A missing sensor must be recorded, not crash or read as OK.
eng3 = RuleEngine(mk_cfg(sensor="cpu"))
eng3.resolver.aliases["cpu"] = "not-a-real-sensor"
check("missing sensor recorded", eng3.update(R, 3000.0) == [] and "t" in eng3.errors)

# --- config validation ----------------------------------------------------------
check("real config.toml loads", bool(load(Path(__file__).resolve().parent / "config.toml").enabled_rules))
for bad, why in [
    ({"clear_at": 95.0}, "backwards hysteresis"),
    ({"op": "!="}, "bad op"),
    ({"severity": "meh"}, "bad severity"),
    ({"sensor": None, "expr": None}, "neither sensor nor expr"),
    ({"sensor": "ghost"}, "undeclared sensor alias"),
]:
    try:
        from hwsentinel.config import validate
        validate(mk_cfg(**bad))
        check(f"reject {why}", False)
    except ConfigError:
        check(f"reject {why}", True)

print("\n" + (f"{len(fails)} FAILED: {fails}" if fails else "all checks passed"))
sys.exit(1 if fails else 0)

