"""
sections.py — Warmup and cooldown, designed per session (spec Section 11,
v2.7).

Until v0.5 the warmup was always a 45-75% ramp plus a fixed 1-2 min block at
45-55%, and the cooldown always a 75-45% ramp: the same shape for a 30-min
recovery spin and a 2-hour VO2max session. Now the reasoning layer designs
both for the session in hand and says why, the same way it designs the main
set, and Python validates and renders them:

  - Short sessions: brief warmup (~5 min) and cooldown (2-3 min) so the
    training time goes to the work; longer and more intense sessions get
    longer warmups, and may carry short openers before hard work.
  - A duration the user asked for ("calentamiento de 15 minutos") is
    adopted exactly: the section must add up to it.
  - Power mode may use ramps; heart-rate mode uses steps only (heart rate
    lags a changing target), climbing in the warmup.

Hard checks here are physiological sanity and arithmetic only, never a
template: a warmup starts easy; a cooldown stays easy and ends easy; both
stay within a sanity length unless the user asked for more.

A warmup always ENDS with a PREPARATION interval (v0.7.0, placed last and made
easy in v0.9.0): a short step (30 s to 2 min) flagged "is_preparation": true
at VERY LOW intensity. It is the pause before the main set: time to drink,
adjust the bike, breathe. The warmup proper is everything BEFORE it, a
single build that arrives ready (its last level is close to where the main
set begins, check_handover). A warmup of two minutes or more cannot be only
the preparation.

v0.9.0 also fixed what the first designed sections got wrong: no target goes
under 45% FTP / 60% LTHR, the build does not dip, and a cooldown only comes
down.

A section is a list of elements, the same shape as the main set plus a ramp:
    {"element": "step",  "duration_seconds", "low_pct", "high_pct",
                         ["cadence_low", "cadence_high", "is_preparation"]}
    {"element": "ramp",  "duration_seconds", "from_pct", "to_pct",
                         ["cadence_low", "cadence_high", "is_preparation"]}
                                                                  (power only)
    {"element": "repeat", "repeats", "steps": [step, ...]}       (no nesting)
"""

from __future__ import annotations

from typing import Optional

from . import tss as tssmod
from .models import Step, RepeatBlock
from .render import render_step_line
from .rpe import rpe_for_flat, rpe_for_ramp

# Sanity limits (seconds) — far above any usual choice; a user request wins.
WARMUP_MAX_SECONDS = 25 * 60
COOLDOWN_MAX_SECONDS = 15 * 60

# Where a warmup may start, and how hard a cooldown may be, per mode (% of
# FTP for power, % of LTHR for heart rate). Endurance tops: Friel power Z2
# 75%, Friel HR Z2 89% LTHR.
EASY_START = {"power": 65, "hr": 80}
COOLDOWN_CEILING = {"power": 75, "hr": 89}
EASY_END = {"power": 65, "hr": 80}
# The preparation is a pause: very low intensity (midpoint, % of FTP / LTHR).
PREP_CEILING = {"power": 60, "hr": 75}

# Lowest target worth writing in a warmup or cooldown (% of FTP / of LTHR).
LEVEL_FLOOR = {"power": 45, "hr": 60}
# The preparation hands over to the main set: its level sits between
# (first work low - BELOW) and (first work high + ABOVE).
HANDOVER_BELOW = 15
HANDOVER_ABOVE = 5
# Slack, in percentage points, for "never dips" and "only comes down".
WARMUP_DIP_TOLERANCE = 10
COOLDOWN_RISE_TOLERANCE = 3

# Preparation interval (warmup only), seconds.
PREP_MIN_SECONDS = 30
PREP_MAX_SECONDS = 120
PREP_NOT_WHOLE_FROM = 120   # from this warmup length the prep is not all of it

_STEP_KEYS = {"element", "duration_seconds", "low_pct", "high_pct",
              "cadence_low", "cadence_high", "is_preparation"}
_RAMP_KEYS = {"element", "duration_seconds", "from_pct", "to_pct",
              "cadence_low", "cadence_high", "is_preparation"}
_REPEAT_KEYS = {"element", "repeats", "steps"}
_INNER_KEYS = {"duration_seconds", "low_pct", "high_pct", "cadence_low",
               "cadence_high"}

SECTION_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["element"],
        "properties": {
            "element": {"type": "string", "enum": ["step", "ramp", "repeat"]},
            "duration_seconds": {"type": "integer", "minimum": 1},
            "low_pct": {"type": "integer", "minimum": 0},
            "high_pct": {"type": "integer", "minimum": 0},
            "from_pct": {"type": "integer", "minimum": 0,
                         "description": "ramp only: start of the ramp"},
            "to_pct": {"type": "integer", "minimum": 0,
                       "description": "ramp only: end of the ramp"},
            "cadence_low": {"type": "integer"},
            "cadence_high": {"type": "integer"},
            "is_preparation": {
                "type": "boolean",
                "description": "WARMUP ONLY. Mark the short (30 s - 2 min) "
                               "VERY EASY step that closes the warmup: a "
                               "pause to drink and adjust before the main "
                               "block. Every warmup has one, last."},
            "repeats": {"type": "integer", "minimum": 1},
            "steps": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["duration_seconds", "low_pct", "high_pct"],
                    "properties": {
                        "duration_seconds": {"type": "integer", "minimum": 1},
                        "low_pct": {"type": "integer", "minimum": 0},
                        "high_pct": {"type": "integer", "minimum": 0},
                        "cadence_low": {"type": "integer"},
                        "cadence_high": {"type": "integer"},
                    },
                },
            },
        },
    },
}


class SectionRejected(ValueError):
    """A warmup or cooldown broke a hard rule. Raised as ProposalRejected
    by the caller so the reason goes back to the reasoning layer."""


def _num(el: dict, key: str, where: str) -> int:
    v = el.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise SectionRejected(f"{where}: missing or non-integer {key!r}")
    if v < 0:
        raise SectionRejected(f"{where}: {key} must not be negative")
    return v


def _flat_values(elements: list) -> list[tuple[float, float]]:
    """(start, end) of every element in execution order, repeats expanded
    once (their shape is what matters for the checks)."""
    out = []
    for el in elements:
        kind = el.get("element")
        if kind == "ramp":
            out.append((el["from_pct"], el["to_pct"]))
        elif kind == "step":
            mid = (el["low_pct"] + el["high_pct"]) / 2
            out.append((mid, mid))
        else:
            for st in el.get("steps") or []:
                mid = (st["low_pct"] + st["high_pct"]) / 2
                out.append((mid, mid))
    return out


def section_seconds(elements: list) -> int:
    total = 0
    for el in elements or []:
        if el.get("element") == "repeat":
            total += el.get("repeats", 1) * sum(
                s["duration_seconds"] for s in el.get("steps") or [])
        else:
            total += el["duration_seconds"]
    return total


def _level_span(el: dict) -> tuple[float, float]:
    """(start, end) level of an element; a repeat block gives its first and
    last step."""
    k = el.get("element")
    if k == "ramp":
        return float(el["from_pct"]), float(el["to_pct"])
    if k == "step":
        m = (el["low_pct"] + el["high_pct"]) / 2.0
        return m, m
    steps = el["steps"]
    f, l = steps[0], steps[-1]
    return ((f["low_pct"] + f["high_pct"]) / 2.0,
            (l["low_pct"] + l["high_pct"]) / 2.0)


def _check_preparation(elements: list, total: int, mode: str) -> None:
    flagged = []
    for i, el in enumerate(elements):
        v = el.get("is_preparation")
        if v is None or v is False:
            continue
        if v is not True:
            raise SectionRejected(
                f"warmup element {i}: is_preparation must be true or false")
        if el.get("element") not in ("step", "ramp"):
            raise SectionRejected(
                f"warmup element {i}: the preparation is a step or a ramp, "
                f"not a repeat block")
        flagged.append(i)
    if not flagged:
        raise SectionRejected(
            "the warmup has no preparation interval — end it with one step "
            f"or ramp of {PREP_MIN_SECONDS} s to {PREP_MAX_SECONDS // 60} "
            "min marked is_preparation: true; it readies the body for the "
            "main block")
    if flagged != [len(elements) - 1]:
        raise SectionRejected(
            "the preparation interval must be the LAST part of the warmup "
            "(and the only one): the athlete rolls straight from it into the "
            "main set, with nothing easier in between")
    el = elements[-1]
    d = el["duration_seconds"]
    if not PREP_MIN_SECONDS <= d <= PREP_MAX_SECONDS:
        raise SectionRejected(
            f"the preparation interval lasts {d}s — keep it short, "
            f"between {PREP_MIN_SECONDS}s and {PREP_MAX_SECONDS}s")
    mid = (el["low_pct"] + el["high_pct"]) / 2 if el.get("element") == "step" \
        else max(el["from_pct"], el["to_pct"])
    if el.get("element") != "step" or mid > PREP_CEILING[mode]:
        raise SectionRejected(
            f"the preparation is a pause before the main set: one easy step "
            f"at {PREP_CEILING[mode]}% or below (time to drink and adjust), "
            f"not {mid:g}%. The warmup itself is what comes before it")
    if total >= PREP_NOT_WHOLE_FROM and d >= total:
        raise SectionRejected(
            "the preparation cannot be the whole warmup — build up to it")


def _check_floor(kind: str, elements: list, mode: str) -> None:
    floor = LEVEL_FLOOR[mode]
    for i, el in enumerate(elements):
        vals = []
        if el.get("element") == "ramp":
            vals = [el["from_pct"], el["to_pct"]]
        elif el.get("element") == "step":
            vals = [el["low_pct"]]
        else:
            vals = [s["low_pct"] for s in el["steps"]]
        low = min(vals)
        if low < floor:
            raise SectionRejected(
                f"{kind} element {i} goes down to {low:g}% — nothing is "
                f"written below {floor}% in {mode} mode; keep every target "
                f"at {floor}% or above")


def _build_of(elements: list) -> list:
    """The warmup proper: everything before the closing preparation."""
    return elements[:-1] if elements and elements[-1].get("is_preparation") is True \
        else elements


def _check_warmup_shape(elements: list, mode: str) -> None:
    """The build rises; it does not peak and fall back before the pause."""
    spans = [_level_span(el) for el in _build_of(elements)
             if el.get("element") != "repeat"]
    if len(spans) < 2:
        return
    end = spans[-1][1]
    peak = max(max(s) for s in spans[:-1])
    if end < peak - WARMUP_DIP_TOLERANCE:
        raise SectionRejected(
            f"the warmup builds to {peak:g}% and then falls back to {end:g}% "
            f"before its closing pause: order the build from easy to hard so "
            f"it ends at its highest level")


def _check_cooldown_shape(elements: list) -> None:
    """A cooldown only comes down: no element starts above where the one
    before it ended."""
    prev_end = None
    for i, el in enumerate(elements):
        start, end = _level_span(el)
        if prev_end is not None and start > prev_end + COOLDOWN_RISE_TOLERANCE:
            raise SectionRejected(
                f"cooldown element {i} starts at {start:g}% after the one "
                f"before it ended at {prev_end:g}%: a cooldown only comes "
                f"down, in one smooth descent")
        prev_end = end


HANDOVER_CAP = {"power": 100, "hr": 100}


def check_handover(warmup: list, first_work: tuple[float, float] | None,
                   mode: str) -> None:
    """The warmup's build arrives where the main set begins: its last level is
    close to the first work step's range, not far below it (a cold start)
    and not above it (spending the legs before the work). The closing pause
    is not part of the build."""
    if not first_work or not warmup:
        return
    cap = HANDOVER_CAP[mode]            # openers, not the full effort, before hard work
    build = _build_of(warmup)
    if not build:
        return
    lo, hi = min(first_work[0], cap), min(first_work[1], cap)
    level = _level_span(build[-1])[1]
    if level < lo - HANDOVER_BELOW or level > hi + HANDOVER_ABOVE:
        raise SectionRejected(
            f"the warmup builds up to {level:g}% but the main set begins at "
            f"{lo:g}-{hi:g}%: the build should arrive between "
            f"{lo - HANDOVER_BELOW:g}% and {hi + HANDOVER_ABOVE:g}% so the "
            f"athlete rolls into the work already ready")


def validate_section(kind: str, elements, *, mode: str,
                     requested_seconds: Optional[int] = None) -> int:
    """Check a warmup or cooldown. Returns its total seconds; raises
    SectionRejected with the exact reason otherwise."""
    name = kind
    if not isinstance(elements, list) or not elements:
        raise SectionRejected(f"{name} is missing or empty — every session has "
                              f"a warmup and a cooldown")
    for i, el in enumerate(elements):
        where = f"{name} element {i}"
        if not isinstance(el, dict):
            raise SectionRejected(f"{where} is not an object")
        k = el.get("element")
        if k == "step":
            extra = set(el) - _STEP_KEYS
            _num(el, "duration_seconds", where)
            lo, hi = _num(el, "low_pct", where), _num(el, "high_pct", where)
            if lo > hi:
                raise SectionRejected(f"{where}: low_pct {lo} > high_pct {hi}")
        elif k == "ramp":
            extra = set(el) - _RAMP_KEYS
            if mode != "power":
                raise SectionRejected(
                    f"{where}: ramps are power-mode only — heart rate lags a "
                    f"changing target, write the progression as steps")
            _num(el, "duration_seconds", where)
            _num(el, "from_pct", where)
            _num(el, "to_pct", where)
        elif k == "repeat":
            extra = set(el) - _REPEAT_KEYS
            reps = el.get("repeats")
            if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
                raise SectionRejected(f"{where}: invalid 'repeats' {reps!r}")
            inner = el.get("steps")
            if not inner:
                raise SectionRejected(f"{where}: repeat without steps")
            for j, st in enumerate(inner):
                w = f"{where} step {j}"
                if (not isinstance(st, dict) or "repeats" in st
                        or st.get("element", "step") != "step"):
                    raise SectionRejected(f"{w}: nested repeats are forbidden")
                bad = set(st) - _INNER_KEYS - {"element"}
                if bad:
                    raise SectionRejected(f"{w}: unknown field(s) {sorted(bad)}")
                _num(st, "duration_seconds", w)
                lo, hi = _num(st, "low_pct", w), _num(st, "high_pct", w)
                if lo > hi:
                    raise SectionRejected(f"{w}: low_pct {lo} > high_pct {hi}")
        else:
            raise SectionRejected(f"{where}: unknown element kind {k!r}")
        if extra:
            raise SectionRejected(f"{where}: unknown field(s) {sorted(extra)}")
        if k != "repeat" and el["duration_seconds"] <= 0:
            raise SectionRejected(f"{where}: duration must be positive")

    values = _flat_values(elements)
    total = section_seconds(elements)
    if kind == "warmup":
        if values[0][0] > EASY_START[mode]:
            raise SectionRejected(
                f"warmup starts at {values[0][0]:g}% — start easy (at or "
                f"below {EASY_START[mode]}%) and build")
        if mode == "hr":
            starts = [a for a, _ in _flat_values(_build_of(elements))]
            if any(b < a for a, b in zip(starts, starts[1:])):
                raise SectionRejected(
                    "HR warmup must climb step by step (a staircase), never "
                    "step down — heart rate needs each level to settle")
        cap = WARMUP_MAX_SECONDS
    else:
        if any(el.get("is_preparation") for el in elements):
            raise SectionRejected(
                "cooldown: 'is_preparation' belongs to the warmup only")
        top = max(max(a, b) for a, b in values)
        if top > COOLDOWN_CEILING[mode]:
            raise SectionRejected(
                f"cooldown reaches {top:g}% — keep it easy (at or below "
                f"{COOLDOWN_CEILING[mode]}%)")
        if values[-1][1] > EASY_END[mode]:
            raise SectionRejected(
                f"cooldown ends at {values[-1][1]:g}% — end easy (at or "
                f"below {EASY_END[mode]}%)")
        cap = COOLDOWN_MAX_SECONDS

    if requested_seconds is not None:
        if total != requested_seconds:
            raise SectionRejected(
                f"the user asked for a {requested_seconds // 60} min {kind} "
                f"({requested_seconds}s); this {kind} adds up to {total}s — "
                f"make it exactly {requested_seconds}s")
    elif total > cap:
        raise SectionRejected(
            f"{kind} of {total // 60} min is over the {cap // 60} min sanity "
            f"limit — size it to the session")
    _check_floor(kind, elements, mode)
    if kind == "warmup":
        _check_warmup_shape(elements, mode)
        _check_preparation(elements, total, mode)
    else:
        _check_cooldown_shape(elements)
    return total


# --- building ----------------------------------------------------------------

def _build_flat(mode: str, st: dict, role: str) -> Step:
    lo, hi = st["low_pct"], st["high_pct"]
    r_lo, r_hi = rpe_for_flat(mode, lo, hi)
    cl, ch = st.get("cadence_low"), st.get("cadence_high")
    return Step(role=role, duration_seconds=st["duration_seconds"],
                flat_low=lo, flat_high=hi, cadence_low=cl, cadence_high=ch,
                rpe_low=r_lo, rpe_high=r_hi,
                rendering=render_step_line(
                    mode=mode, duration_seconds=st["duration_seconds"],
                    flat_low=lo, flat_high=hi, cadence_low=cl, cadence_high=ch,
                    rpe_low=r_lo, rpe_high=r_hi))


def _build_ramp(mode: str, el: dict, role: str) -> Step:
    a, b = el["from_pct"], el["to_pct"]
    r_lo, r_hi = rpe_for_ramp(mode, a, b)
    cl, ch = el.get("cadence_low"), el.get("cadence_high")
    return Step(role=role, duration_seconds=el["duration_seconds"], is_ramp=True,
                ramp_start=a, ramp_end=b, cadence_low=cl, cadence_high=ch,
                rpe_low=r_lo, rpe_high=r_hi,
                rendering=render_step_line(
                    mode=mode, duration_seconds=el["duration_seconds"],
                    is_ramp=True, ramp_start=a, ramp_end=b,
                    cadence_low=cl, cadence_high=ch,
                    rpe_low=r_lo, rpe_high=r_hi))


def build_section(mode: str, elements: list, role: str) -> list:
    """Validated section -> list[Step | RepeatBlock] with RPE and rendering."""
    out: list = []
    for el in elements:
        k = el["element"]
        if k == "step":
            out.append(_build_flat(mode, el, role))
        elif k == "ramp":
            out.append(_build_ramp(mode, el, role))
        else:
            out.append(RepeatBlock(repeats=el["repeats"],
                                   steps=[_build_flat(mode, s, role)
                                          for s in el["steps"]]))
    return out


def section_segments(elements: list) -> list[tssmod.Segment]:
    """Raw section -> ordered load segments (ramps linear)."""
    segs: list[tssmod.Segment] = []
    for el in elements:
        k = el["element"]
        if k == "ramp":
            segs.append(tssmod.Segment(float(el["duration_seconds"]),
                                       el["from_pct"] / 100.0,
                                       el["to_pct"] / 100.0))
        elif k == "step":
            segs.append(tssmod.Segment(float(el["duration_seconds"]),
                                       (el["low_pct"] + el["high_pct"]) / 200.0))
        else:
            for _ in range(el["repeats"]):
                for s in el["steps"]:
                    segs.append(tssmod.Segment(float(s["duration_seconds"]),
                                               (s["low_pct"] + s["high_pct"]) / 200.0))
    return segs


# --- default sections (offline generator only) --------------------------------

def default_sections(mode: str, total_seconds: Optional[int],
                     warmup_seconds: Optional[int] = None,
                     cooldown_seconds: Optional[int] = None) -> tuple[list, list]:
    """Simple sections for the deterministic offline generator, which has no
    reasoning layer: ~5 min warmup and 3 min cooldown up to 45-min sessions,
    10 and 5 beyond. A requested duration is used as given. The warmup ends
    with a short, very easy pause (60 s, 90 s in longer warmups)."""
    short = total_seconds is not None and total_seconds <= 45 * 60
    w = warmup_seconds or (300 if short else 600)
    c = cooldown_seconds or (180 if short else 300)
    prep = 60 if w <= 300 else 90
    rest = w - prep
    if mode == "power":
        if rest <= 0:
            warm = [{"element": "step", "duration_seconds": w,
                     "low_pct": 50, "high_pct": 55, "is_preparation": True}]
        else:
            warm = [{"element": "ramp", "duration_seconds": rest,
                     "from_pct": 45, "to_pct": 65},
                    {"element": "step", "duration_seconds": prep,
                     "low_pct": 50, "high_pct": 55, "is_preparation": True}]
        cool = [{"element": "ramp", "duration_seconds": c,
                 "from_pct": 65, "to_pct": 45}]
    else:
        if rest <= 0:
            warm = [{"element": "step", "duration_seconds": w,
                     "low_pct": 62, "high_pct": 70, "is_preparation": True}]
        else:
            m = 2 if rest >= 240 else 1
            base, extra = divmod(rest, m)
            levels = (60, 68)[:m]
            warm = [{"element": "step",
                     "duration_seconds": base + (extra if i == m - 1 else 0),
                     "low_pct": lo, "high_pct": lo + 8}
                    for i, lo in enumerate(levels)]
            warm.append({"element": "step", "duration_seconds": prep,
                         "low_pct": 62, "high_pct": 70,
                         "is_preparation": True})
        cool = [{"element": "step", "duration_seconds": c,
                 "low_pct": 65, "high_pct": 75}]
    return warm, cool
