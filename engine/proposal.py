"""
proposal.py — The contract between the Claude reasoning layer and the
deterministic core (spec Section 9).

Claude proposes a workout STRUCTURE via tool-use, returning JSON that matches
PROPOSAL_TOOL_SCHEMA. Python then VALIDATES every proposal against the hard
rules before accepting it. A rejected proposal is discarded and re-requested —
never silently "fixed", never accepted blind.

Division of responsibility (confirmed):
  - Claude decides: main-set structure (reps, durations, recoveries, pattern),
    intensity %s within the requested zone, optional subordinate complementary
    stimuli, the warmup and cooldown of each session, progression shape.
  - Python owns: validation, TSS/IF math, rendering, output gate. Claude never
    does the math and never produces the final syntax directly.
"""

from __future__ import annotations
from .zones import zones_for_mode, zone_by_name
from .sections import SECTION_SCHEMA, validate_section, SectionRejected


# --- The tool schema Claude must fill (passed to the API as a tool) ----------
# Claude returns ONLY structural intent; Python turns it into validated output.

PROPOSAL_TOOL_SCHEMA = {
    "name": "propose_workout",
    "description": (
        "Propose the STRUCTURE of one indoor cycling workout: its warmup, "
        "main set and cooldown. "
        "Return structural intent only — do NOT compute TSS/IF and do NOT "
        "write intervals.icu syntax; the engine does that. Respect the "
        "requested zone as the dominant stimulus; any complementary stimuli "
        "must be subordinate (less time-in-zone). All intensities are integer "
        "percent ranges within the mode's zone system."
    ),
    "input_schema": {
        "type": "object",
        "required": ["structural_pattern", "warmup", "main_set", "cooldown",
                     "summary"],
        "properties": {
            "structural_pattern": {
                "type": "string",
                "enum": ["continuous", "classic_interval", "pyramidal",
                         "ladder", "over_under", "progressive", "divided_split"],
            },
            "main_set": {
                "type": "array",
                "minItems": 1,
                "description": "Ordered elements: each is a single step or a "
                               "repeat block (Nx). Repeat blocks are NOT nested.",
                "items": {
                    "type": "object",
                    
                    "required": ["element"],
                    "properties": {
                        "element": {"type": "string", "enum": ["step", "repeat"]},
                        # for element=step
                        "duration_seconds": {"type": "integer", "minimum": 1},
                        "low_pct": {"type": "integer", "minimum": 0},
                        "high_pct": {"type": "integer", "minimum": 0},
                        "zone_name": {"type": "string",
                                      "description": "Which zone this segment "
                                      "belongs to (dominant or a complementary)."},
                        "is_recovery": {"type": "boolean"},
                        "cadence_low": {"type": "integer"},
                        "cadence_high": {"type": "integer"},
                        # for element=repeat
                        "repeats": {"type": "integer", "minimum": 1},
                        "steps": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                
                                "required": ["duration_seconds", "low_pct", "high_pct", "zone_name"],
                                "properties": {
                                    "duration_seconds": {"type": "integer", "minimum": 1},
                                    "low_pct": {"type": "integer", "minimum": 0},
                                    "high_pct": {"type": "integer", "minimum": 0},
                                    "zone_name": {"type": "string"},
                                    "is_recovery": {"type": "boolean"},
                                    "cadence_low": {"type": "integer"},
                                    "cadence_high": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
            "complementary_stimuli": {
                "type": "array",
                "items": {
                    "type": "object",
                    
                    "required": ["zone"],
                    "properties": {
                        "zone": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
            "warmup": dict(SECTION_SCHEMA, description=(
                "The warmup, designed for THIS session (not a template): "
                "start easy and build; brief (~5 min) in short sessions, "
                "longer as duration and intensity grow; short openers "
                "before hard work are fine. Power mode may use ramps; "
                "HR mode uses climbing steps only.")),
            "cooldown": dict(SECTION_SCHEMA, description=(
                "The cooldown, designed for THIS session: easy all the way "
                "and ending easy; brief (2-3 min) in short sessions, longer "
                "after long or hard ones.")),
            "warmup_cooldown_rationale": {
                "type": "string",
                "description": "One sentence: why this warmup and cooldown "
                               "for this session.",
            },
        },
    },
}


# --- Validation of a returned proposal (spec 9: validate before accept) ------

class ProposalRejected(ValueError):
    """A Claude proposal violated a hard rule. Discard and re-request."""


def _zone_names(mode: str) -> set[str]:
    return {z.name for z in zones_for_mode(mode)}


def _require_step_fields(step: dict) -> None:
    """M3: a step missing its numeric fields must produce a clean
    ProposalRejected, never a leaked KeyError/TypeError."""
    for f in ("duration_seconds", "low_pct", "high_pct"):
        v = step.get(f)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ProposalRejected(
                f"step is missing or has a non-numeric {f!r}: {step!r}")
    if step["duration_seconds"] <= 0:
        raise ProposalRejected(
            f"step duration_seconds must be positive: {step!r}")


def _check_step(mode: str, step: dict, valid_zones: set[str], dominant: str) -> None:
    _require_step_fields(step)
    lo, hi = step["low_pct"], step["high_pct"]
    if lo > hi:
        raise ProposalRejected(f"step low_pct {lo} > high_pct {hi}")
    if lo < 0 or hi < 0:
        raise ProposalRejected("percent values must be non-negative")

    # Recovery segments are "whatever is easy enough" — they are NOT required to
    # sit exactly within a named zone's bounds (a recovery may straddle the
    # Recovery/Aerobic boundary, etc.). Only sanity-check they are genuinely
    # easy, not accidentally hard. m3: the WHOLE range must be easy — checking
    # only the low end let an "easy" 80-90% slip through.
    if step.get("is_recovery"):
        # An easy recovery should not exceed roughly endurance/aerobic intensity.
        ceiling = 85
        if hi > ceiling:
            raise ProposalRejected(
                f"recovery intensity {lo}-{hi}% too hard "
                f"(upper end exceeds {ceiling}%)"
            )
        return

    # Work segments (A1): zone name must be valid and the intensity range must
    # be CONTAINED within that zone's bounds (boundary-inclusive: 75-90% IS a
    # valid Tempo range, exactly as Friel writes the zone). Mere overlap is
    # not enough — a 75-105% "Tempo" interval spans three zones and would
    # falsify the session's declared stimulus.
    zname = step.get("zone_name", dominant)
    if zname not in valid_zones:
        raise ProposalRejected(
            f"zone {zname!r} not valid in {mode} system (cross-mode mixing forbidden)"
        )
    z = zone_by_name(mode, zname)
    hi_repr = z.high_pct if z.high_pct is not None else "open"
    if lo < z.low_pct or (z.high_pct is not None and hi > z.high_pct):
        raise ProposalRejected(
            f"intensity {lo}-{hi}% not contained within zone {zname} bounds "
            f"[{z.low_pct}-{hi_repr}%] — work intensities must sit within "
            f"their named zone"
        )


# Unknown fields (v0.4.1). Gemini's response_schema does not carry
# `additionalProperties: false`, so the API itself would let a field the
# engine does not know through. The engine checks it here instead: a field
# outside the schema means the model misread the contract, and silently
# ignoring it could drop something the model meant (e.g. a misspelled
# "cooldown_secs" would otherwise fall back to the default cooldown).
_TOP_KEYS = set(PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"])
_ELEMENT_KEYS = set(PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"]
                    ["main_set"]["items"]["properties"])
_INNER_STEP_KEYS = set(PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"]
                       ["main_set"]["items"]["properties"]["steps"]["items"]
                       ["properties"])


def _check_unknown_fields(proposal: dict) -> None:
    extra = set(proposal) - _TOP_KEYS
    if extra:
        raise ProposalRejected(
            f"unknown proposal field(s) {sorted(extra)} — use only the "
            f"fields of the schema")
    for i, el in enumerate(proposal.get("main_set") or []):
        if not isinstance(el, dict):
            raise ProposalRejected(f"main_set element {i} is not an object")
        extra = set(el) - _ELEMENT_KEYS
        if extra:
            raise ProposalRejected(
                f"unknown field(s) {sorted(extra)} in main_set element {i}")
        for j, st in enumerate(el.get("steps") or []):
            # An inner item carrying "element" is a nested repeat: leave it
            # to the nested-repeat check, which names the real problem.
            if isinstance(st, dict) and "element" not in st:
                extra = set(st) - _INNER_STEP_KEYS
                if extra:
                    raise ProposalRejected(
                        f"unknown field(s) {sorted(extra)} in step {j} of "
                        f"main_set element {i}")


def _collect_used_zones(main_set: list, dominant_zone: str) -> set[str]:
    """Collect all non-dominant, non-recovery zone names actually used across
    main_set (steps and repeat-block inner steps), for the metadata-honesty
    check in validate_proposal."""
    used: set[str] = set()
    for el in main_set:
        if el.get("element") == "step":
            if not el.get("is_recovery"):
                z = el.get("zone_name", dominant_zone)
                if z != dominant_zone:
                    used.add(z)
        elif el.get("element") == "repeat":
            for st in el.get("steps", []):
                if not st.get("is_recovery"):
                    z = st.get("zone_name", dominant_zone)
                    if z != dominant_zone:
                        used.add(z)
    return used


def validate_proposal(proposal: dict, *, mode: str, dominant_zone: str,
                      total_budget_seconds: int | None = None,
                      enforce_floor: bool = True,
                      requested_warmup_seconds: int | None = None,
                      requested_cooldown_seconds: int | None = None) -> None:
    """Validate a Claude proposal against the hard rules. Raises
    ProposalRejected on the first violation; returns None if acceptable.

    Hard rules enforced here (spec 4, 8, 11, 12, 17):
      - all zone names valid in the chosen mode (no cross-mode mixing)
      - work intensities within their named zone bounds
      - no nested repeats
      - dominant stimulus must actually dominate (most work time-in-zone)
      - warmup and cooldown designed per session but sane (sections.py):
        start easy / end easy, HR steps only, a user-requested length exact
      - if a total budget is given: warmup+main_set+cooldown <= budget
        (pure arithmetic conservation of the total, NOT a training rule)
    """
    valid = _zone_names(mode)
    if dominant_zone not in valid:
        raise ProposalRejected(f"dominant zone {dominant_zone!r} invalid for {mode}")

    _check_unknown_fields(proposal)

    if not proposal.get("main_set"):
        raise ProposalRejected("main_set is empty")

    # --- Warmup and cooldown (spec 11, v2.7: designed per session) ---
    try:
        warm_s = validate_section("warmup", proposal.get("warmup"), mode=mode,
                                  requested_seconds=requested_warmup_seconds)
        cool_s = validate_section("cooldown", proposal.get("cooldown"), mode=mode,
                                  requested_seconds=requested_cooldown_seconds)
    except SectionRejected as e:
        raise ProposalRejected(str(e))

    dominant_work = 0
    other_work = 0
    main_set_seconds = 0

    for el in proposal["main_set"]:
        kind = el.get("element")
        if kind == "step":
            if "steps" in el or "repeats" in el:
                raise ProposalRejected("step element must not carry repeat fields")
            _check_step(mode, el, valid, dominant_zone)
            main_set_seconds += el["duration_seconds"]
            if not el.get("is_recovery"):
                z = el.get("zone_name", dominant_zone)
                t = el["duration_seconds"]
                if z == dominant_zone:
                    dominant_work += t
                else:
                    other_work += t
        elif kind == "repeat":
            inner = el.get("steps")
            if not inner:
                raise ProposalRejected("repeat element missing steps")
            reps = el.get("repeats")
            if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
                raise ProposalRejected(
                    f"repeat element missing or invalid 'repeats': {reps!r}")
            block_seconds = 0
            for st in inner:
                if "element" in st:
                    raise ProposalRejected("nested repeats are forbidden")
                _check_step(mode, st, valid, dominant_zone)
                block_seconds += st["duration_seconds"]
                if not st.get("is_recovery"):
                    z = st.get("zone_name", dominant_zone)
                    t = st["duration_seconds"] * reps
                    if z == dominant_zone:
                        dominant_work += t
                    else:
                        other_work += t
            main_set_seconds += block_seconds * reps
        else:
            raise ProposalRejected(f"unknown element kind {kind!r}")

    # Dominant/subordinate boundary (spec 17): requested zone must dominate.
    if dominant_work <= 0:
        raise ProposalRejected("no work in the dominant (requested) zone")
    if other_work > dominant_work:
        raise ProposalRejected(
            f"complementary work ({other_work}s) exceeds dominant "
            f"({dominant_work}s) — requested stimulus must dominate"
        )

    # Metadata honesty: any non-dominant, non-recovery zone actually used in
    # main_set must be declared in complementary_stimuli, so the reported
    # complementary_zones on the session accurately reflects what was built.
    declared = {c["zone"] for c in proposal.get("complementary_stimuli", [])}
    used_other_zones = _collect_used_zones(proposal["main_set"], dominant_zone)
    undeclared = used_other_zones - declared
    if undeclared:
        raise ProposalRejected(
            f"zones {sorted(undeclared)} are used in main_set but not "
            f"declared in complementary_stimuli — metadata must match what "
            f"was actually built"
        )

    # --- Budget conservation (pure arithmetic, spec 15) ---
    # Decision: the engine gets maximum flexibility to reason the structure
    # (spec 3/9.6) — the ceiling (never exceed the budget) is a hard rule, but
    # the floor is deliberately LOOSE. A minor shortfall (e.g. 58 min of a
    # 60-min request) is fine and left to the athlete to fill manually if they
    # want (a bit more warmup, one extra rep) — forcing an exact minute match
    # would push the engine toward padding structure just to hit a number,
    # which is exactly the rigidity this project avoids. Only a genuinely
    # considerable shortfall is caught.
    #
    # `enforce_floor` distinguishes a TARGET duration (floor + ceiling) from
    # a MAXIMUM (ceiling only). Filling more of the athlete's available time
    # is a coaching decision, never the engine's to force.
    _BUDGET_FLOOR_FRACTION = 0.80  # allow up to 20% under budget with no rejection
    if total_budget_seconds is not None:
        total = warm_s + cool_s + main_set_seconds
        if total > total_budget_seconds:
            raise ProposalRejected(
                f"session total {total}s (warmup {warm_s} + main "
                f"{main_set_seconds} + cooldown {cool_s}) exceeds budget "
                f"{total_budget_seconds}s by {total - total_budget_seconds}s"
            )
        if enforce_floor:
            floor = total_budget_seconds * _BUDGET_FLOOR_FRACTION
            if total < floor:
                raise ProposalRejected(
                    f"session total {total}s is considerably under the "
                    f"{total_budget_seconds}s budget (below the {floor:.0f}s "
                    f"floor) — minor shortfalls are fine, but this gap is too "
                    f"large; use more of the available time"
                )


# --- TSS/IF target verification (spec 16.3 — report, never silently accept) --

_TSS_TOLERANCE_FRACTION = 0.10  # accept within +/-10% of the requested target
_IF_TOLERANCE_FRACTION = 0.05   # IF enters TSS squared; ~5% IF ~= 10% TSS


def verify_tss_target(proposal_segments_tss: float, target_tss: float) -> None:
    """Compare the ACTUAL computed TSS of a built proposal against the user's
    target. Raises ProposalRejected if the deviation exceeds tolerance —
    this closes the gap where a target_tss was requested but never checked
    against what was actually produced (spec 16.3: report, never force)."""
    if target_tss <= 0:
        return
    deviation = abs(proposal_segments_tss - target_tss) / target_tss
    if deviation > _TSS_TOLERANCE_FRACTION:
        raise ProposalRejected(
            f"resulting TSS {proposal_segments_tss:.1f} deviates "
            f"{deviation*100:.0f}% from the requested target {target_tss:g} "
            f"(tolerance is {_TSS_TOLERANCE_FRACTION*100:.0f}%)"
        )


def verify_if_target(built_if: float, target_if: float) -> None:
    """Symmetric check for a requested IF (A2): the built session's real IF
    must sit within tolerance of the target — report, never silently accept."""
    if target_if <= 0:
        return
    deviation = abs(built_if - target_if) / target_if
    if deviation > _IF_TOLERANCE_FRACTION:
        raise ProposalRejected(
            f"resulting IF {built_if:.3f} deviates {deviation*100:.0f}% from "
            f"the requested target {target_if:g} "
            f"(tolerance is {_IF_TOLERANCE_FRACTION*100:.0f}%)"
        )
