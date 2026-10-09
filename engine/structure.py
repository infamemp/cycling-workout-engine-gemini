"""
structure.py — Hard-constraint conflict detection (spec 16.3) and the
provisional Phase-1 main-set logic.

Every session ALWAYS has Warmup + Main Set + Cooldown. Since v0.6.0 the
warmup and cooldown are designed per session and live in sections.py; the
fixed 45-75% ramp and always-present 45-55% prep block are gone.

================================ IMPORTANT ================================
The main-set SHAPE decisions here (how many reps, how long, what complementary
stimuli) are PROVISIONAL PHASE-1 PLACEHOLDERS. They exist only so the
end-to-end flow runs and is testable today. They are intentionally simple and
will be REPLACED WHOLESALE by the Phase-2 Claude reasoning layer, which will
reason from physiology/methodology + the catalog + web search.
Do NOT mistake this placeholder for the engine's real intelligence.
==========================================================================
"""

from __future__ import annotations
from .models import Step, RepeatBlock
from .rpe import rpe_for_flat
from .render import render_step_line
from . import tss as tssmod


# --- Hard-constraint conflict detection (spec 16.3) -------------------------

class ConstraintConflict(Exception):
    """Raised when target TSS/IF and max duration cannot both hold."""
    def __init__(self, report: str):
        super().__init__(report)
        self.report = report


def check_duration_vs_tss(target_tss: float | None, target_if: float | None,
                          max_available_seconds: int | None) -> None:
    """If a target TSS at a given IF needs more time than is available, report
    the conflict with numbers — never silently pick which to sacrifice."""
    if target_tss is None or target_if is None or max_available_seconds is None:
        return
    needed = tssmod.duration_from(target_tss, target_if)
    if needed > max_available_seconds:
        max_tss = tssmod.tss_from(max_available_seconds, target_if)
        raise ConstraintConflict(
            f"TSS {target_tss:g} at IF {target_if:g} needs "
            f"{needed/60:.1f} min, but max available is "
            f"{max_available_seconds/60:.1f} min. "
            f"Highest TSS achievable in that time at this IF is {max_tss:.0f}."
        )


def check_zone_feasibility(mode: str, zone_name: str,
                           target_tss: float | None,
                           target_if: float | None,
                           budget_seconds: int | None) -> None:
    """M4: mathematical conflict detection WITHOUT requiring a user IF.

    The requested zone's top intensity bounds what is achievable: the absolute
    best case is the entire budget ridden at the zone ceiling. If even that
    cannot reach the target TSS — or if the target IF exceeds the zone ceiling
    outright — this is a hard conflict, reported with concrete numbers BEFORE
    any API call (spec 16.3: report, never force; and never die as a generic
    'no valid proposal'). Power mode only (TSS/IF are power math). This is a
    NECESSARY bound, not a sufficient one: structure-level infeasibility is
    still detected exactly by the intensity resolver.
    """
    if mode != "power" or not zone_name:
        return
    from .zones import zone_by_name  # local import; zones has no deps on us
    try:
        z = zone_by_name(mode, zone_name)
    except ValueError:
        return  # invalid zone is reported elsewhere (fail-fast in generators)
    if z.high_pct is None:
        return  # open-ended top zone: no ceiling to bound against
    top_frac = z.high_pct / 100.0

    if target_if is not None and target_if > top_frac:
        raise ConstraintConflict(
            f"target IF {target_if:g} exceeds the maximum possible for the "
            f"{zone_name} zone (top intensity {z.high_pct}% -> IF ceiling "
            f"{top_frac:.2f}). Choose a lower IF or a higher zone."
        )

    if target_tss is not None and budget_seconds is not None:
        max_tss = tssmod.tss_from(budget_seconds, top_frac)
        if target_tss > max_tss:
            needed = tssmod.duration_from(target_tss, top_frac)
            raise ConstraintConflict(
                f"TSS {target_tss:g} in the {zone_name} zone needs at least "
                f"{needed/60:.1f} min even at the zone's top intensity "
                f"({z.high_pct}%); the time budget is "
                f"{budget_seconds/60:.1f} min. Highest TSS achievable in that "
                f"time within this zone is ~{max_tss:.0f}."
            )


# --- PROVISIONAL Phase-1 main-set placeholder -------------------------------

def provisional_main_set(mode: str, zone_low: int, zone_high: int,
                         work_seconds_each: int, reps: int,
                         recovery_low: int, recovery_high: int,
                         recovery_seconds: int) -> RepeatBlock:
    """[PHASE-1 PLACEHOLDER] A plain Nx(work/recovery) block. Dumb on purpose.
    Phase 2 replaces this with reasoned, varied, catalog-aware structure."""
    w_lo, w_hi = rpe_for_flat(mode, zone_low, zone_high)
    rc_lo, rc_hi = rpe_for_flat(mode, recovery_low, recovery_high)
    work = Step(
        role="work", duration_seconds=work_seconds_each,
        flat_low=zone_low, flat_high=zone_high, rpe_low=w_lo, rpe_high=w_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=work_seconds_each,
            flat_low=zone_low, flat_high=zone_high, rpe_low=w_lo, rpe_high=w_hi,
        ),
    )
    recovery = Step(
        role="recovery", duration_seconds=recovery_seconds,
        flat_low=recovery_low, flat_high=recovery_high,
        rpe_low=rc_lo, rpe_high=rc_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=recovery_seconds,
            flat_low=recovery_low, flat_high=recovery_high,
            rpe_low=rc_lo, rpe_high=rc_hi,
        ),
    )
    return RepeatBlock(repeats=reps, steps=[work, recovery])
