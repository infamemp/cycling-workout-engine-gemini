"""
generator_v2.py — Phase-2 orchestration (Gemini reasoning + deterministic core).

Flow (spec Section 9):
  request -> conflict checks -> ask Gemini for a structural proposal (tool-use)
  -> VALIDATE proposal against hard rules -> rebuild with the core ->
  assemble mandatory structure + main set -> compute real TSS -> catalog.

If a proposal is rejected, it is DISCARDED and re-requested (up to a small
retry budget). Python never silently "fixes" a bad proposal and never accepts
one blind. The math, rendering, and output gate remain 100% deterministic.
"""

from __future__ import annotations
import uuid
import random
from typing import Optional

from .models import GenerationRequest, GeneratedSession, Feasibility
from .zones import zone_by_name
from . import structure as struct
from . import assembler
from . import tss as tssmod
from .catalog import Catalog, CatalogEntry
from .gemini_client import Transport, request_proposal
from .proposal import (validate_proposal, verify_tss_target, verify_if_target,
                       ProposalRejected, flatten_nested_repeats,
                       derive_complementary_zones)
from .build_from_proposal import build_main_set
from .sections import build_section, section_segments, section_seconds
from .resolve_intensity import (resolve_proposal_intensity, IntensityInfeasible)


_MAX_RETRIES = 3


def generate_single_v2(req: GenerationRequest, *,
                       transport: Transport,
                       catalog: Optional[Catalog] = None,
                       use_web_search: bool = False,
                       progression_id: Optional[str] = None) -> GeneratedSession:
    if req.mode not in ("power", "hr"):
        raise ValueError("mode must be 'power' or 'hr'")
    if not req.requested_zone:
        raise ValueError("requested_zone is required")
    # Fail fast: validate the zone name locally before spending any API calls
    # (previously an invalid zone from e.g. the natural-language parser would
    # burn all 3 retries against the API before failing).
    zone_by_name(req.mode, req.requested_zone)

    # Hard-constraint conflict detection (spec 16.3) before spending an API call.
    struct.check_duration_vs_tss(
        req.target_tss, req.target_if, req.max_available_seconds
    )

    recent = []
    if catalog is not None:
        recent = catalog.recent(mode=req.mode, dominant_zone=req.requested_zone)

    # --- Ask Gemini, validate, build, and verify TSS target; retry as needed ---
    last_error: Optional[str] = None
    proposal: Optional[dict] = None
    warmup = cooldown = main_set = None
    markdown = None
    warnings: list[str] = []
    est_tss = est_if = None
    tss_method = "np_30s"

    # --- Session-level algebra (spec 16.1, pure math, engine's territory) ---
    # TSS + IF given without a duration -> the duration is implied; derive it.
    # All three given -> they must be mutually consistent; report if not.
    target_duration = req.target_duration_seconds
    if req.target_tss is not None and req.target_if is not None:
        implied = tssmod.duration_from(req.target_tss, req.target_if)
        if target_duration is None:
            target_duration = int(round(implied))
        elif abs(implied - target_duration) / target_duration > 0.05:
            raise struct.ConstraintConflict(
                f"over-determined request is inconsistent: TSS "
                f"{req.target_tss:g} at IF {req.target_if:g} implies "
                f"{implied/60:.1f} min, but the requested duration is "
                f"{target_duration/60:.1f} min. Adjust one of the three."
            )

    # Budget: the strictest of the given caps. The floor only applies when the
    # user gave (or the algebra implied) a TARGET duration; max_available is a
    # ceiling, never a target to fill (A3).
    _caps = [x for x in (target_duration, req.max_available_seconds) if x]
    budget = min(_caps) if _caps else None
    floor_applies = target_duration is not None

    # M4: zone-bounded feasibility (no user IF needed) — hard conflict with
    # numbers BEFORE spending any API call.
    struct.check_zone_feasibility(req.mode, req.requested_zone,
                                  req.target_tss, req.target_if, budget)
    for _attempt in range(_MAX_RETRIES):
        candidate = request_proposal(
            transport=transport, mode=req.mode, zone=req.requested_zone,
            target_duration_seconds=target_duration,
            target_tss=req.target_tss, target_if=req.target_if,
            recent=recent, use_web_search=use_web_search,
            rejection_feedback=last_error,  # A4: correct, don't guess blind
            warmup_seconds=req.warmup_seconds,
            cooldown_seconds=req.cooldown_seconds,
        )
        try:
            # One level of sub-repeat is allowed; the platform has no nested
            # repeats, so it is unrolled into its block first.
            candidate = flatten_nested_repeats(candidate)
            # Warmup and cooldown are designed per session by the reasoning
            # layer (spec 11, v2.7) and validated with the rest; a length the
            # user asked for must be met exactly.
            warnings = validate_proposal(candidate, mode=req.mode,
                              dominant_zone=req.requested_zone,
                              total_budget_seconds=budget,
                              enforce_floor=floor_applies,
                              requested_warmup_seconds=req.warmup_seconds,
                              requested_cooldown_seconds=req.cooldown_seconds)

            # --- Deterministic intensity resolution (C3, spec 16.2) ---
            # Power mode with a TSS/IF target: Gemini fixed the STRUCTURE
            # (warmup and cooldown included); the engine now solves the one
            # free variable — the dominant work intensity. Never guessed.
            if req.mode == "power" and (req.target_tss is not None
                                        or req.target_if is not None):
                before_segments = section_segments(candidate["warmup"])
                after_segments = section_segments(candidate["cooldown"])
                if req.target_if is not None:
                    np_target = req.target_if
                else:
                    total_s = section_seconds(candidate["warmup"]) + \
                        section_seconds(candidate["cooldown"]) + \
                        _proposal_main_seconds(candidate)
                    np_target = tssmod.if_from(req.target_tss, total_s)
                try:
                    candidate = resolve_proposal_intensity(
                        candidate, mode=req.mode,
                        dominant_zone=req.requested_zone,
                        np_target_frac=np_target,
                        before_segments=before_segments,
                        after_segments=after_segments,
                    )
                except IntensityInfeasible as e:
                    raise ProposalRejected(str(e))

            w = build_section(req.mode, candidate["warmup"], "warmup")
            c = build_section(req.mode, candidate["cooldown"], "cooldown")
            m = build_main_set(req.mode, candidate)
            md = assembler.build_markdown(w, m, c)
            load = assembler.compute_load(w, m, c, mode=req.mode,
                                          hr_profile=req.athlete.hr_profile())
            t_tss, t_if = load.tss, load.intensity_factor

            # Target verification (spec 16.3): only meaningful once the FULL
            # session (incl. warmup/cooldown) is built, since those contribute
            # to the real TSS/IF too. With the deterministic resolution above,
            # these now pass by construction (rounding-level deviations only);
            # they remain as the final honesty gate.
            if req.target_tss is not None:
                verify_tss_target(t_tss, req.target_tss)
            if req.mode == "power" and req.target_if is not None:
                verify_if_target(t_if, req.target_if)

            proposal, warmup, cooldown, main_set = candidate, w, c, m
            markdown, est_tss, est_if = md, t_tss, t_if
            tss_method = load.method
            break
        except ProposalRejected as e:
            last_error = str(e)
            continue
    if proposal is None:
        raise ProposalRejected(
            f"no valid proposal after {_MAX_RETRIES} attempts; last: {last_error}"
        )

    sid = str(uuid.uuid4())[:8]
    summary = proposal.get("summary", f"{req.requested_zone} session")
    complementary = derive_complementary_zones(proposal, req.requested_zone)

    session = GeneratedSession(
        id=sid, generated_at=CatalogEntry.now_iso(), mode=req.mode,
        dominant_zone=req.requested_zone,
        structural_pattern=proposal.get("structural_pattern"),
        complementary_zones=complementary,
        warmup=warmup, main_set=main_set, cooldown=cooldown,
        estimated_tss=round(est_tss, 1), estimated_if=round(est_if, 3),
        feasibility=Feasibility(satisfied=True),
        summary=summary, markdown_output=markdown,
        progression_id=progression_id,
        tss_method=tss_method,
        warnings=list(warnings),
    )

    if catalog is not None:
        total_dur = _total_duration(warmup, main_set, cooldown)
        catalog.add(CatalogEntry(
            id=sid, generated_at=session.generated_at, mode=req.mode,
            dominant_zone=req.requested_zone,
            structural_pattern=session.structural_pattern,
            complementary=complementary, duration_seconds=total_dur,
            estimated_tss=session.estimated_tss, estimated_if=session.estimated_if,
            progression_id=progression_id, summary=summary, markdown=markdown,
        ))

    return session


def _elements_duration(elements: list) -> int:
    total = 0
    for el in elements:
        if hasattr(el, "repeats"):
            total += el.repeats * sum(s.duration_seconds for s in el.steps)
        else:
            total += el.duration_seconds
    return total


def _proposal_main_seconds(proposal: dict) -> int:
    """Total main-set seconds of a raw proposal dict (repeats expanded)."""
    total = 0
    for el in proposal["main_set"]:
        if el.get("element") == "step":
            total += el["duration_seconds"]
        else:
            total += el.get("repeats", 1) * sum(
                s["duration_seconds"] for s in el.get("steps", []))
    return total


def _total_duration(warmup, main_set, cooldown) -> int:
    return (_elements_duration(warmup) + _elements_duration(main_set)
            + _elements_duration(cooldown))
