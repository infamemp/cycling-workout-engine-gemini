"""
resolve_intensity.py — Deterministic work-segment intensity resolution
(spec Section 16.2/16.3/16.4). POWER MODE ONLY (NP/IF/TSS are power math).

Strict order (spec 16.2): the STRUCTURE is fixed first (by the reasoning
layer — reps, durations, recoveries, warmup/cooldown shape), WITHOUT
reference to TSS/IF. Only then is the one remaining free variable — the
dominant work-segment intensity — solved.

One unknown: the proposal's internal intensity RATIOS between dominant
work steps are preserved (over/under, pyramids where all steps are the
dominant zone), so step_i power = r_i * x with r_i = proposed_mid_i /
proposed_mid_first, and only x is solved.

v0.5.0: NP is the real Normalized Power with the 30 s rolling average (see
tss.py), the definition Intervals.icu applies to planned workouts. The
rolling window makes NP depend on the ORDER of the segments, so the solve
runs on the session exactly as it will be assembled (warmup, prep, main set
in order with repeats expanded, cooldown), and by bisection: there is no
closed form once the window is in the formula.

Known segments (never touched): warmup, prep, cooldown, every recovery step,
and every complementary (non-dominant) step — their proposed values stand.

Infeasibility (spec 16.3): if the solved intensity falls outside the dominant
zone's bounds, this is a HARD infeasibility reported with concrete numbers
(including the closest achievable TSS at the zone edge) — never clamped,
never silently forced.

Rounding (spec 16.4): the solved center is rounded to an integer percent; the
output range keeps the proposal's width, shrunk symmetrically only if needed
to stay inside the zone (the solved center — the physiological target — is
preserved; the width is presentation). The reported TSS downstream is the
real TSS of the rounded, built session.
"""

from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Optional

from .zones import zone_by_name
from . import tss as tssmod


class IntensityInfeasible(ValueError):
    """Raised when the TSS/IF target cannot be met within the dominant zone
    for the fixed structure (spec 16.3: report with numbers, never force)."""


@dataclass(frozen=True)
class _TimelineItem:
    """One segment of the ordered session. A work item's power is
    ratio * x (x = the unknown); a known item carries its own segment."""
    seconds: float
    known: Optional[tssmod.Segment] = None
    ratio: Optional[float] = None
    half_width_pct: float = 0.0
    mid_frac: float = 0.0


def _iter_main_steps(proposal: dict):
    """Yield (step_dict, occurrences) for every step in main_set, flattening
    repeat blocks (repeats -> occurrences)."""
    for el in proposal["main_set"]:
        if el.get("element") == "step":
            yield el, 1
        else:
            for st in el.get("steps", []):
                yield st, el.get("repeats", 1)


def _is_dominant_work(st: dict, dominant_zone: str) -> bool:
    return (not st.get("is_recovery")) and \
        st.get("zone_name", dominant_zone) == dominant_zone


def _main_timeline(proposal: dict, dominant_zone: str) -> list[_TimelineItem]:
    """The main set in execution order, repeats expanded. Dominant work
    steps become unknown items (ratio to the first one); everything else is
    a known segment at its proposed midpoint."""
    items: list[_TimelineItem] = []
    ref: Optional[float] = None

    def add(st: dict) -> None:
        nonlocal ref
        secs = float(st["duration_seconds"])
        mid = (st["low_pct"] + st["high_pct"]) / 2.0 / 100.0
        if _is_dominant_work(st, dominant_zone):
            if ref is None:
                ref = mid
            items.append(_TimelineItem(
                seconds=secs, ratio=(mid / ref) if ref > 0 else 0.0,
                half_width_pct=(st["high_pct"] - st["low_pct"]) / 2.0,
                mid_frac=mid))
        else:
            items.append(_TimelineItem(seconds=secs,
                                       known=tssmod.Segment(secs, mid)))

    for el in proposal["main_set"]:
        if el.get("element") == "step":
            add(el)
        else:
            for _ in range(el.get("repeats", 1)):
                for st in el.get("steps", []):
                    add(st)
    return items


def _builder(before: list[tssmod.Segment], main: list[_TimelineItem],
             after: list[tssmod.Segment]):
    def build(x: float) -> list[tssmod.Segment]:
        segs = list(before)
        for it in main:
            segs.append(it.known if it.known is not None
                        else tssmod.Segment(it.seconds, it.ratio * x))
        segs += after
        return segs
    return build


def resolve_proposal_intensity(proposal: dict, *, mode: str,
                               dominant_zone: str,
                               np_target_frac: float,
                               before_segments: list[tssmod.Segment],
                               after_segments: list[tssmod.Segment]) -> dict:
    """Return a COPY of the proposal with the dominant work steps' percent
    ranges replaced by the deterministically solved intensity (spec 16.2).

    `before_segments` (warmup ramp/staircase + prep) and `after_segments`
    (cooldown) are the effective segments the builder will actually use, so
    the solve sees the full session in its real order.

    Power mode only. Raises IntensityInfeasible per spec 16.3.
    """
    if mode != "power":
        raise ValueError("intensity resolution is power-mode only")

    main = _main_timeline(proposal, dominant_zone)
    work = [it for it in main if it.known is None]
    if not work:
        raise IntensityInfeasible("no dominant work steps to resolve")

    build = _builder(before_segments, main, after_segments)
    try:
        x = tssmod.solve_scale(build, np_target_frac)
    except tssmod.InfeasibleError as e:
        raise IntensityInfeasible(str(e))

    zone = zone_by_name(mode, dominant_zone)

    # Infeasibility check (spec 16.3): EVERY resolved dominant midpoint must
    # sit inside the dominant zone. Report with the closest achievable TSS.
    for it in work:
        mid_pct = it.ratio * x * 100.0
        if not zone.contains(mid_pct):
            ratios = [w.ratio for w in work]
            if zone.high_pct is not None and mid_pct >= zone.high_pct:
                x_edge = (zone.high_pct / 100.0) / max(ratios)
            else:
                x_edge = (zone.low_pct / 100.0) / min(ratios) \
                    if min(ratios) > 0 else 0.0
            achievable = tssmod.session_tss(build(x_edge)) if x_edge > 0 else 0.0
            raise IntensityInfeasible(
                f"resolved work intensity {mid_pct:.1f}% falls outside the "
                f"{dominant_zone} zone bounds [{zone.low_pct}"
                f"-{zone.high_pct if zone.high_pct is not None else 'open'}%] "
                f"for this structure; the closest achievable session TSS at "
                f"the zone edge is ~{achievable:.0f}. Adjust the TSS/IF "
                f"target, the duration, or the structure."
            )

    # Rounding (spec 16.4): integer center; keep the proposed width, shrunk
    # symmetrically only as needed to stay inside the zone. Every occurrence
    # of a step inside a repeat shares one dict, so each dict is set once.
    adjusted = copy.deepcopy(proposal)
    ref_mid: Optional[float] = None
    for st, _occ in _iter_main_steps(adjusted):
        if not _is_dominant_work(st, dominant_zone):
            continue
        mid = (st["low_pct"] + st["high_pct"]) / 2.0 / 100.0
        if ref_mid is None:
            ref_mid = mid
        ratio = mid / ref_mid if ref_mid > 0 else 0.0
        center = int(round(ratio * x * 100.0))
        proposed_hw = (st["high_pct"] - st["low_pct"]) / 2.0
        max_hw = float(center - zone.low_pct)
        if zone.high_pct is not None:
            max_hw = min(max_hw, float(zone.high_pct - center))
        hw = int(max(0.0, min(proposed_hw, max_hw)))
        st["low_pct"] = center - hw
        st["high_pct"] = center + hw
    return adjusted
