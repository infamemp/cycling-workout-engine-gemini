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
import copy
from .zones import zones_for_mode, zone_by_name
from .sections import SECTION_SCHEMA, validate_section, SectionRejected

# v0.7.0 — flexibility. The validator splits what it finds in two:
#   - REJECTIONS protect against errors: unknown zone systems, impossible
#     numbers, a session longer than its budget, a user-fixed duration not
#     met, a warmup without its preparation interval, "recovery" that is not
#     easy, and a requested zone that does not appear at all.
#   - WARNINGS describe design choices and never block them: a step that
#     reaches past its zone, most work time sitting outside the requested
#     zone. They are returned (and shown to the athlete) so the coach can
#     see them, as Infame does with its purpose check.


_LEAF_PROPS = {
    "duration_seconds": {"type": "integer", "minimum": 1},
    "low_pct": {"type": "integer", "minimum": 0},
    "high_pct": {"type": "integer", "minimum": 0},
    "zone_name": {"type": "string"},
    "is_recovery": {"type": "boolean"},
    "cadence_low": {"type": "integer"},
    "cadence_high": {"type": "integer"},
}

# --- The tool schema Claude must fill (passed to the API as a tool) ----------
# Claude returns ONLY structural intent; Python turns it into validated output.

PROPOSAL_TOOL_SCHEMA = {
    "name": "propose_workout",
    "description": (
        "Propose the STRUCTURE of one indoor cycling workout: its warmup, "
        "main set and cooldown. "
        "Return structural intent only — do NOT compute TSS/IF and do NOT "
        "write intervals.icu syntax; the engine does that. The requested "
        "zone is the session's purpose and must appear in the main set; how "
        "the work is shaped around it (steady, intervals, touches, builds, "
        "surges, ladders) is your design. All intensities are integer "
        "percent ranges in the mode's zone system; a step may reach past its "
        "zone when the design calls for it."
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
                               "repeat block (Nx). A block may hold one "
                               "level of sub-repeat.",
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
                            "description": "Steps of the block. An item with "
                            "element=repeat is a sub-repeat (one level): "
                            "the engine unrolls it into the block, because "
                            "the platform has no nested repeats.",
                            "items": {
                                "type": "object",
                                "required": ["element"],
                                "properties": {
                                    "element": {"type": "string",
                                                "enum": ["step", "repeat"]},
                                    **_LEAF_PROPS,
                                    "repeats": {"type": "integer",
                                                "minimum": 1},
                                    "steps": {
                                        "type": "array", "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "required": ["duration_seconds",
                                                         "low_pct", "high_pct",
                                                         "zone_name"],
                                            "properties": dict(_LEAF_PROPS),
                                        },
                                    },
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
                "longer as duration and intensity grow. It ALWAYS includes "
                "a short preparation interval (30 s - 2 min, "
                "is_preparation=true) that readies the body for the main "
                "block. Power mode may use ramps; HR mode uses climbing "
                "steps only.")),
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
    """A Claude proposal broke a rule that protects against errors. Discard
    and re-request, passing the reason back."""


# Outer limits of a believable target, % of FTP (power) or % of LTHR (HR).
# Far beyond any real session; they catch typos (900%), not designs.
SANITY_MAX_PCT = {"power": 400, "hr": 120}
RECOVERY_CEILING_PCT = 85       # a step called recovery must be easy
MAX_UNROLLED_STEPS = 80         # a block longer than this is not a workout


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


def _check_step(mode: str, step: dict, valid_zones: set[str], dominant: str,
                warnings: list[str]) -> None:
    """Errors raise; design observations go to `warnings`."""
    _require_step_fields(step)
    lo, hi = step["low_pct"], step["high_pct"]
    if lo > hi:
        raise ProposalRejected(f"step low_pct {lo} > high_pct {hi}")
    if lo < 0 or hi < 0:
        raise ProposalRejected("percent values must be non-negative")
    if hi > SANITY_MAX_PCT[mode]:
        raise ProposalRejected(
            f"intensity {lo}-{hi}% is beyond any believable target "
            f"(limit {SANITY_MAX_PCT[mode]}% in {mode} mode)")

    zname = step.get("zone_name", dominant)
    if zname not in valid_zones:
        raise ProposalRejected(
            f"zone {zname!r} not valid in {mode} system (cross-mode mixing "
            f"forbidden)")

    # A step called recovery has to be easy (the whole range).
    if step.get("is_recovery"):
        if hi > RECOVERY_CEILING_PCT:
            raise ProposalRejected(
                f"recovery intensity {lo}-{hi}% too hard "
                f"(upper end exceeds {RECOVERY_CEILING_PCT}%)")
        return

    # A work step may reach past its zone: a progressive effort, a surge, a
    # step that builds from Tempo into Threshold. Not an error — noted.
    z = zone_by_name(mode, zname)
    if lo < z.low_pct or (z.high_pct is not None and hi > z.high_pct):
        top = z.high_pct if z.high_pct is not None else "open"
        warnings.append(
            f"a {zname} step runs {lo}-{hi}%, past the zone's "
            f"{z.low_pct}-{top}% (a design choice, noted)")


# Nested repeats. The platform has no nested repeats, so the schema lets a
# block carry ONE level of sub-repeat and the engine unrolls it: a block
# 4 x [5 x (30s on / 30s off), 4 min easy] is written as 4 x [10 short steps,
# 4 min easy]. Nothing is lost; the athlete sees a flat block.
_LEAF_KEYS = set(_LEAF_PROPS)


def _unroll_sub_repeat(st: dict, where: str) -> list[dict]:
    reps = st.get("repeats")
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
        raise ProposalRejected(f"{where}: sub-repeat has invalid 'repeats' "
                               f"{reps!r}")
    inner = st.get("steps")
    if not isinstance(inner, list) or not inner:
        raise ProposalRejected(f"{where}: sub-repeat needs 'steps'")
    leaves = []
    for k, leaf in enumerate(inner):
        if not isinstance(leaf, dict):
            raise ProposalRejected(f"{where}: sub-repeat step {k} is not an "
                                   f"object")
        if (leaf.get("element") == "repeat" or "repeats" in leaf
                or "steps" in leaf):
            raise ProposalRejected(
                f"{where}: nested more than one level — a sub-repeat cannot "
                f"hold another repeat")
        bad = set(leaf) - _LEAF_KEYS - {"element"}
        if bad:
            raise ProposalRejected(
                f"{where}: unknown field(s) {sorted(bad)} in sub-repeat "
                f"step {k}")
        leaf = {k2: v for k2, v in leaf.items() if k2 != "element"}
        leaves.append(leaf)
    return [copy.deepcopy(l) for _ in range(reps) for l in leaves]


def flatten_nested_repeats(proposal: dict) -> dict:
    """Return a copy of the proposal with every sub-repeat unrolled into its
    block (one level of nesting allowed; deeper is rejected). A proposal
    without sub-repeats comes back unchanged apart from the copy."""
    out = copy.deepcopy(proposal)
    for i, el in enumerate(out.get("main_set") or []):
        if not isinstance(el, dict) or el.get("element") != "repeat":
            continue
        flat: list[dict] = []
        for j, st in enumerate(el.get("steps") or []):
            where = f"main_set element {i} step {j}"
            if not isinstance(st, dict):
                raise ProposalRejected(f"{where} is not an object")
            kind = st.get("element", "step")
            if kind == "repeat":
                flat.extend(_unroll_sub_repeat(st, where))
            elif kind == "step":
                if "repeats" in st or "steps" in st:
                    raise ProposalRejected(
                        f"{where}: a step must not carry repeat fields — "
                        f"use element=repeat for a sub-repeat")
                flat.append({k: v for k, v in st.items() if k != "element"})
            else:
                raise ProposalRejected(f"{where}: unknown element {kind!r}")
        if len(flat) > MAX_UNROLLED_STEPS:
            raise ProposalRejected(
                f"main_set element {i} unrolls to {len(flat)} steps — too "
                f"long for one block (limit {MAX_UNROLLED_STEPS})")
        el["steps"] = flat
    return out


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
            if isinstance(st, dict):
                extra = set(st) - _INNER_STEP_KEYS
                if extra:
                    raise ProposalRejected(
                        f"unknown field(s) {sorted(extra)} in step {j} of "
                        f"main_set element {i}")


def main_zone_seconds(proposal: dict, dominant_zone: str) -> dict[str, int]:
    """Work seconds per zone name in the main set (recovery steps left out,
    repeats expanded). Works on a flat (unrolled) proposal."""
    out: dict[str, int] = {}
    for el in proposal.get("main_set") or []:
        if el.get("element") == "repeat":
            reps = el.get("repeats", 1)
            steps = [(st, reps) for st in el.get("steps") or []]
        else:
            steps = [(el, 1)]
        for st, n in steps:
            if st.get("is_recovery"):
                continue
            z = st.get("zone_name", dominant_zone)
            out[z] = out.get(z, 0) + int(st.get("duration_seconds", 0)) * n
    return out


def derive_complementary_zones(proposal: dict, dominant_zone: str) -> list[str]:
    """The other zones the main set really works in, derived from what was
    built (v0.7.0: the engine reports them; the proposal no longer has to
    declare them correctly), plus any zone the proposal declared."""
    declared = {c.get("zone") for c in proposal.get("complementary_stimuli", [])
                if isinstance(c, dict) and c.get("zone")}
    used = set(main_zone_seconds(proposal, dominant_zone)) - {dominant_zone}
    return sorted((declared | used) - {dominant_zone})


def validate_proposal(proposal: dict, *, mode: str, dominant_zone: str,
                      total_budget_seconds: int | None = None,
                      enforce_floor: bool = True,
                      requested_warmup_seconds: int | None = None,
                      requested_cooldown_seconds: int | None = None
                      ) -> list[str]:
    """Validate a proposal. Raises ProposalRejected on the first ERROR and
    returns a list of WARNINGS (design observations, never blocking).

    Errors (they protect against mistakes, not against creativity):
      - zone names valid in the chosen mode (no cross-mode mixing)
      - impossible numbers; a step called recovery that is not easy
      - nesting deeper than one level
      - the requested zone does not appear in the main set at all
      - warmup and cooldown sane (sections.py): start easy / end easy, HR
        steps only, a preparation interval in the warmup, a user-requested
        length exact
      - warmup + main set + cooldown within the budget; a TARGET duration
        not missed by a wide margin

    Warnings: a step reaching past its zone; most work time outside the
    requested zone.
    """
    valid = _zone_names(mode)
    if dominant_zone not in valid:
        raise ProposalRejected(f"dominant zone {dominant_zone!r} invalid for {mode}")

    _check_unknown_fields(proposal)
    proposal = flatten_nested_repeats(proposal)
    warnings: list[str] = []

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

    main_set_seconds = 0
    zones_named: set[str] = set()

    for el in proposal["main_set"]:
        kind = el.get("element")
        if kind == "step":
            if "steps" in el or "repeats" in el:
                raise ProposalRejected("step element must not carry repeat fields")
            _check_step(mode, el, valid, dominant_zone, warnings)
            main_set_seconds += el["duration_seconds"]
            zones_named.add(el.get("zone_name", dominant_zone))
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
                _check_step(mode, st, valid, dominant_zone, warnings)
                block_seconds += st["duration_seconds"]
                zones_named.add(st.get("zone_name", dominant_zone))
            main_set_seconds += block_seconds * reps
        else:
            raise ProposalRejected(f"unknown element kind {kind!r}")

    # --- Purpose (v0.7.0). The requested zone is the session's purpose: it
    # has to be in the session. How much of the work time it takes is the
    # coach's design (touches, surges, progressions, a build through zones),
    # so a different split is a warning, not a rejection.
    if dominant_zone not in zones_named:
        raise ProposalRejected(
            f"the requested zone {dominant_zone} does not appear in the main "
            f"set — the session has to work in the zone that was asked for")
    secs = main_zone_seconds(proposal, dominant_zone)
    dominant_work = secs.get(dominant_zone, 0)
    other_work = sum(v for k, v in secs.items() if k != dominant_zone)
    if other_work > dominant_work:
        biggest = max((k for k in secs if k != dominant_zone),
                      key=lambda k: secs[k])
        warnings.append(
            f"most of the work time ({other_work // 60} min) sits outside "
            f"{dominant_zone}, mainly in {biggest}; the session reads as "
            f"{biggest} work with {dominant_zone} in it — say so in the "
            f"summary")
    warnings = list(dict.fromkeys(warnings))

    # --- Budget conservation (pure arithmetic, spec 15) ---
    # The ceiling (never exceed the budget) is hard. The floor is deliberately
    # LOOSE: a minor shortfall (58 of 60 min) is fine; only a considerable
    # one is caught. `enforce_floor` distinguishes a TARGET duration (floor +
    # ceiling) from a MAXIMUM (ceiling only): filling more of the athlete's
    # available time is a coaching decision, never the engine's to force.
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
    return warnings


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
