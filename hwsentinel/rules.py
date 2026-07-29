"""The part that decides whether something is actually wrong.

A bare `value > threshold` check would flash the overlay on every transient spike, so
each rule runs a small state machine:

    OK --(over threshold for `dwell`)--> TRIPPED --(under `clear_at` for
    `clear_dwell`)--> OK, and cannot re-trip until `cooldown` has elapsed.

The separate clear point is hysteresis: a rule that trips at 88 °C clears at 83 °C, so
a sensor hovering at the threshold does not strobe.
"""

from __future__ import annotations

import ast
import operator
import time
from dataclasses import dataclass, field
from enum import Enum

from .config import Config, RuleCfg
from .source_lhm import Reading, SensorResolver, SourceError


# Sensible decimal places per unit. One decimal suits temperatures but destroys
# voltages: 1.11 V and a 1.10 V threshold both render as "1.1", so the alert reads
# "1.1V over 1.1V" and looks like a bug.
_UNIT_DECIMALS = {"V": 3, "A": 2, "W": 1, "%": 0, "RPM": 0, "MHz": 0}


def decimals_for(unit: str) -> int:
    return _UNIT_DECIMALS.get(unit.strip(), 1)


class State(Enum):
    OK = "ok"
    PENDING = "pending"      # over the line, waiting out `dwell`
    TRIPPED = "tripped"
    CLEARING = "clearing"    # back under `clear_at`, waiting out `clear_dwell`


class EventKind(Enum):
    TRIP = "trip"
    UPDATE = "update"
    CLEAR = "clear"


@dataclass
class Alert:
    key: str
    title: str
    severity: str
    detail: str
    value: float
    unit: str
    since: float

    @property
    def elapsed(self) -> float:
        return max(0.0, time.time() - self.since)


@dataclass
class Event:
    kind: EventKind
    alert: Alert


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def eval_expr(expr: str, values: dict[str, float]) -> float:
    """Evaluate a small arithmetic expression over sensor aliases.

    Deliberately not `eval`: only names, numbers, + - * /, parentheses and abs() are
    permitted, so a config file can never execute arbitrary code.
    """
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise SourceError(f"invalid expression {expr!r}: {exc}") from exc

    def walk(n: ast.AST) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in values:
                raise SourceError(f"expression {expr!r} references unknown sensor '{n.id}'")
            return values[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN_OPS:
            return _BIN_OPS[type(n.op)](walk(n.left), walk(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY_OPS:
            return _UNARY_OPS[type(n.op)](walk(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "abs" and len(n.args) == 1:
            return abs(walk(n.args[0]))
        raise SourceError(f"expression {expr!r} contains an unsupported construct")

    return walk(node)


def expr_aliases(expr: str) -> list[str]:
    """Sensor aliases referenced by an expression."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - {"abs"})


@dataclass
class _RuleState:
    cfg: RuleCfg
    state: State = State.OK
    since: float = 0.0          # when the current state was entered
    over_since: float = 0.0     # when the value first crossed the line (pre-dwell)
    tripped_at: float = 0.0
    last_clear: float = field(default=-1e9)
    snoozed_until: float = 0.0
    unit: str = ""
    last_value: float = 0.0


class RuleEngine:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.resolver = SensorResolver(cfg.sensors)
        self.states: dict[str, _RuleState] = {r.key: _RuleState(cfg=r) for r in cfg.enabled_rules}
        self.errors: dict[str, str] = {}

    # -- reading a rule's current numeric value -------------------------------

    def measure(self, rule: RuleCfg, readings: dict[str, Reading]) -> tuple[float, str]:
        if rule.expr:
            values: dict[str, float] = {}
            unit = ""
            for alias in expr_aliases(rule.expr):
                r = self.resolver.resolve(alias, readings)
                values[alias] = r.value
                unit = unit or r.unit
            return eval_expr(rule.expr, values), rule.unit or unit
        r = self.resolver.resolve(rule.sensor, readings)
        return r.value, rule.unit or r.unit

    # -- the state machine ----------------------------------------------------

    def update(self, readings: dict[str, Reading], now: float | None = None) -> list[Event]:
        now = time.time() if now is None else now
        events: list[Event] = []

        for key, st in self.states.items():
            rule = st.cfg
            try:
                value, unit = self.measure(rule, readings)
            except SourceError as exc:
                # A missing sensor must not take the whole daemon down, but it also
                # must not look like "everything is fine" — record it for `doctor`.
                self.errors[key] = str(exc)
                continue
            self.errors.pop(key, None)
            st.unit, st.last_value = unit, value

            over = value > rule.value if rule.op == ">" else value < rule.value
            under_clear = value <= rule.clear_at if rule.op == ">" else value >= rule.clear_at

            # Two passes so a zero dwell resolves within one poll: entering PENDING and
            # satisfying it are otherwise a poll interval apart. Only *silent*
            # transitions (OK->PENDING, TRIPPED->CLEARING) are followed through; once a
            # pass emits anything, this tick is done, so no rule reports twice.
            for _ in range(2):
                before = st.state
                produced = self._step(st, now, over, under_clear)
                events.extend(produced)
                if produced or st.state is before:
                    break

        return events

    def _step(self, st: _RuleState, now: float, over: bool, under_clear: bool) -> list[Event]:
        """One transition of a single rule. Returns any events it produced."""
        rule = st.cfg
        events: list[Event] = []

        if st.state is State.OK:
            if over and now >= st.snoozed_until and (now - st.last_clear) >= rule.cooldown:
                st.state, st.since, st.over_since = State.PENDING, now, now

        elif st.state is State.PENDING:
            if not over:
                st.state, st.since = State.OK, now
            elif (now - st.since) >= rule.dwell:
                st.state, st.since, st.tripped_at = State.TRIPPED, now, now
                events.append(Event(EventKind.TRIP, self._alert(st, now)))

        elif st.state is State.TRIPPED:
            if now < st.snoozed_until:
                st.state, st.since, st.last_clear = State.OK, now, now
                events.append(Event(EventKind.CLEAR, self._alert(st, now)))
            elif under_clear:
                st.state, st.since = State.CLEARING, now
            else:
                events.append(Event(EventKind.UPDATE, self._alert(st, now)))

        elif st.state is State.CLEARING:
            # Only a genuine re-breach of the trip point restarts the alert. Requiring
            # the value to stay under clear_at *continuously* looks reasonable but is
            # defeated by any sensor that moves faster than clear_dwell: a GPU voltage
            # rail wobbles across the clear point several times a second, so the
            # countdown reset forever and the alert only ever cleared when the card
            # went idle - minutes later. Reaching clear_at still starts the recovery;
            # noise on the way down no longer cancels it.
            if over:
                st.state, st.since = State.TRIPPED, now
                events.append(Event(EventKind.UPDATE, self._alert(st, now)))
            elif (now - st.since) >= rule.clear_dwell:
                st.state, st.since, st.last_clear = State.OK, now, now
                events.append(Event(EventKind.CLEAR, self._alert(st, now)))
            else:
                events.append(Event(EventKind.UPDATE, self._alert(st, now)))

        return events

    def _alert(self, st: _RuleState, now: float) -> Alert:
        rule = st.cfg
        # Measured from the crossing, not the trip, so a rule with a 10s dwell reports
        # "for 10s" the instant it appears rather than "for 0s".
        held = max(0, int(now - st.over_since))
        unit = st.unit
        dp = decimals_for(unit)
        value_s = f"{st.last_value:.{dp}f}{unit}"

        breached = st.last_value > rule.value if rule.op == ">" else st.last_value < rule.value
        under_clear = (
            st.last_value <= rule.clear_at if rule.op == ">" else st.last_value >= rule.clear_at
        )
        clear_s = f"{rule.clear_at:.{dp}f}{unit}"

        if breached:
            arrow = "over" if rule.op == ">" else "under"
            detail = f"{rule.label} {value_s} · {arrow} {rule.value:.{dp}f}{unit} for {held}s"
        elif not under_clear:
            # Between the clear point and the trip point. The alert deliberately stays
            # up here — that gap is what stops a value hovering on the threshold from
            # flashing the card on and off. Say so, and say what will dismiss it:
            # reporting "recovered" while refusing to disappear reads as a bug.
            side = "below" if rule.op == ">" else "above"
            detail = f"{rule.label} {value_s} · settling, clears {side} {clear_s}"
        else:
            detail = f"{rule.label} {value_s} · recovered after {held}s"
        return Alert(
            key=rule.key,
            title=rule.title,
            severity=rule.severity,
            detail=detail,
            value=st.last_value,
            unit=unit,
            since=st.tripped_at,
        )

    # -- external control -----------------------------------------------------

    def snooze(self, key: str, minutes: float) -> None:
        st = self.states.get(key)
        if st:
            st.snoozed_until = time.time() + minutes * 60.0

    @property
    def active(self) -> list[Alert]:
        now = time.time()
        return [
            self._alert(st, now)
            for st in self.states.values()
            if st.state in (State.TRIPPED, State.CLEARING)
        ]
