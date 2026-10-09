"""
generator.py — End-to-end orchestration (Phase 1, deterministic core).

Flow: request -> (conflict checks) -> build mandatory structure ->
provisional main set -> assemble .md -> compute real TSS -> catalog.

================================ IMPORTANT ================================
The structure DECISIONS in this module (simple warmup/cooldown, main-set
reps/durations) are PROVISIONAL PHASE-1 PLACEHOLDERS, present only
so the pipeline runs end-to-end and is testable. The Phase-2 Claude reasoning
layer will REPLACE these decisions with real, varied, catalog-aware,
physiology-grounded reasoning. The plumbing (structure assembly, TSS math,
rendering, validation, catalog) is the durable part.
==========================================================================
"""

from __future__ import annotations
import uuid
import random
from typing import Optional

from .models import GenerationRequest, GeneratedSession, Feasibility
from .zones import zone_by_name
from . import structure as struct
from . import assembler
from .catalog import Catalog, CatalogEntry


from .sections import default_sections, build_section, validate_section

# Main-set shapes the placeholder can pick from (seconds): work, recovery.
_WORK_CHOICES = (300, 480, 600)
_REC_CHOICES = (120, 180)


def _fit_main_set(rng: random.Random, main_budget: Optional[int]):
    """Reps / work / recovery for the placeholder main set. With a budget,
    the largest set that fits it (at least 2 reps; shorter work bouts when
    time is short); without one, a seeded random pick as before."""
    if main_budget is None:
        return rng.choice([3, 4, 5]), rng.choice(_WORK_CHOICES), rng.choice(_REC_CHOICES)
    best = None
    for work in _WORK_CHOICES + (180, 120):
        for rec in _REC_CHOICES + (60,):
            reps = min(main_budget // (work + rec), 8)
            if reps < 2:
                continue
            used = reps * (work + rec)
            if best is None or used > best[0]:
                best = (used, reps, work, rec)
    if best is None:
        raise struct.ConstraintConflict(
            f"no main set of at least 2 repetitions fits the "
            f"{max(main_budget, 0) // 60} min left after warmup and cooldown")
    return best[1], best[2], best[3]


def generate_single(req: GenerationRequest, *,
                    catalog: Optional[Catalog] = None,
                    seed: Optional[int] = None,
                    progression_id: Optional[str] = None) -> GeneratedSession:
    """Generate one session end-to-end. Phase-1 provisional structure."""
    if req.mode not in ("power", "hr"):
        raise ValueError("mode must be 'power' or 'hr'")
    if not req.requested_zone:
        raise ValueError("Phase-1 generator requires an explicit requested_zone")

    rng = random.Random(seed)

    # Hard-constraint conflict detection (spec 16.3) — report, never force.
    struct.check_duration_vs_tss(
        req.target_tss, req.target_if, req.max_available_seconds
    )
    _caps = [x for x in (req.target_duration_seconds,
                         req.max_available_seconds) if x]
    struct.check_zone_feasibility(req.mode, req.requested_zone,
                                  req.target_tss, req.target_if,
                                  min(_caps) if _caps else None)

    zone = zone_by_name(req.mode, req.requested_zone)
    # For the placeholder we need concrete work %s; use the zone's interior.
    z_low = zone.low_pct
    z_high = zone.high_pct if zone.high_pct is not None else zone.low_pct + 10

    # --- Warmup and cooldown (spec 11, v2.7) ---
    # The offline generator has no reasoning layer, so it uses simple
    # sections sized to the session; a length the user asked for is used as
    # given. Validated with the same checks as a reasoned session.
    _caps = [x for x in (req.target_duration_seconds, req.max_available_seconds) if x]
    budget = min(_caps) if _caps else None
    warm_raw, cool_raw = default_sections(req.mode, budget, req.warmup_seconds,
                                          req.cooldown_seconds)
    validate_section("warmup", warm_raw, mode=req.mode,
                     requested_seconds=req.warmup_seconds)
    validate_section("cooldown", cool_raw, mode=req.mode,
                     requested_seconds=req.cooldown_seconds)
    warmup = build_section(req.mode, warm_raw, "warmup")
    cooldown = build_section(req.mode, cool_raw, "cooldown")
    used = assembler.elements_seconds(warmup) + assembler.elements_seconds(cooldown)

    # --- PROVISIONAL main set (Phase-1 placeholder), fitted to the budget ---
    reps, work_each, recovery_each = _fit_main_set(
        rng, None if budget is None else budget - used)
    rec_low, rec_high = (50, 60) if req.mode == "power" else (70, 80)
    main_block = struct.provisional_main_set(
        mode=req.mode, zone_low=z_low, zone_high=z_high,
        work_seconds_each=work_each, reps=reps,
        recovery_low=rec_low, recovery_high=rec_high,
        recovery_seconds=recovery_each,
    )
    main_set = [main_block]

    # --- Assemble + real TSS (durable) ---
    markdown = assembler.build_markdown(warmup, main_set, cooldown)
    load = assembler.compute_load(warmup, main_set, cooldown, mode=req.mode,
                                  hr_profile=req.athlete.hr_profile())
    est_tss, est_if = load.tss, load.intensity_factor

    sid = str(uuid.uuid4())[:8]
    summary = (f"{req.requested_zone} {reps}x{work_each//60}min "
               f"[PHASE-1 placeholder]")

    session = GeneratedSession(
        id=sid,
        generated_at=CatalogEntry.now_iso(),
        mode=req.mode,
        dominant_zone=req.requested_zone,
        structural_pattern="classic_interval",  # placeholder label
        complementary_zones=[],
        warmup=warmup,
        main_set=main_set,
        cooldown=cooldown,
        estimated_tss=round(est_tss, 1),
        estimated_if=round(est_if, 3),
        feasibility=Feasibility(satisfied=True),
        summary=summary,
        markdown_output=markdown,
        progression_id=progression_id,
        generation_seed=seed,
        tss_method=load.method,
    )

    if catalog is not None:
        total_dur = (assembler.elements_seconds(warmup)
                     + assembler.elements_seconds(main_set)
                     + assembler.elements_seconds(cooldown))
        catalog.add(CatalogEntry(
            id=sid, generated_at=session.generated_at, mode=req.mode,
            dominant_zone=req.requested_zone,
            structural_pattern=session.structural_pattern,
            complementary=[], duration_seconds=total_dur,
            estimated_tss=session.estimated_tss,
            estimated_if=session.estimated_if,
            progression_id=progression_id, summary=summary,
            markdown=markdown,
        ))

    return session
