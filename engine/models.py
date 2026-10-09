"""
models.py — Data structures for requests and generated sessions.
Mirrors the validated JSON schema (docs/workout_engine_schema.json).

These are plain dataclasses for the deterministic core. The Phase-2 Claude
layer will populate the creative fields; Phase-1 fills them with a provisional
placeholder strategy (see structure.py) so the end-to-end flow runs today.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal

Mode = Literal["power", "hr"]


# --- Request ----------------------------------------------------------------

@dataclass
class RecoveryWeekReduction:
    reduce_duration_pct: Optional[float] = None
    reduce_session_count_to: Optional[int] = None
    reduce_intensity_note: Optional[str] = None


@dataclass
class ProgressionSpec:
    total_weeks: int
    sessions_per_week: int
    load_to_recovery_ratio: str            # e.g. "3:1"
    recovery_week_reduction: Optional[RecoveryWeekReduction] = None
    load_week_ramp: Optional[str] = None   # absent => engine does NOT ramp


@dataclass
class Athlete:
    # All optional, internal-only, never rendered as absolute watts/bpm.
    cp_watts: Optional[float] = None        # = FTP display label
    w_prime_joules: Optional[float] = None
    lthr_bpm: Optional[float] = None
    # HR-mode load (HRSS, spec 16.6) needs LTHR and max HR; a missing
    # resting HR takes Intervals.icu's own default of 60 bpm. Without LTHR
    # or max HR the engine uses a typical profile and says so.
    max_hr_bpm: Optional[float] = None
    resting_hr_bpm: Optional[float] = None

    def hr_profile(self):
        """The athlete's HrProfile, or None when any value is missing."""
        from .tss import HrProfile, DEFAULT_RESTING_HR_BPM
        if self.lthr_bpm and self.max_hr_bpm:
            rest = self.resting_hr_bpm or DEFAULT_RESTING_HR_BPM
            prof = HrProfile(float(self.lthr_bpm), float(self.max_hr_bpm),
                             float(rest))
            return prof if prof.valid() else None
        return None


@dataclass
class GenerationRequest:
    kind: Literal["single_session", "progression"]
    mode: Mode
    requested_zone: Optional[str] = None    # zone name in the chosen system
    target_duration_seconds: Optional[int] = None
    max_available_seconds: Optional[int] = None
    target_tss: Optional[float] = None
    target_if: Optional[float] = None
    # A warmup / cooldown length the user asked for; adopted exactly.
    warmup_seconds: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    # Optional level of the person who will ride it: basic | intermediate |
    # advanced. A design criterion for the reasoning layer only (how the work
    # is cut into blocks); the engine validates nothing about it.
    level: Optional[str] = None
    athlete: Athlete = field(default_factory=Athlete)
    progression: Optional[ProgressionSpec] = None


# --- Generated session ------------------------------------------------------

@dataclass
class Step:
    role: str                  # warmup | work | recovery | cooldown
    duration_seconds: int
    is_ramp: bool = False
    flat_low: Optional[int] = None
    flat_high: Optional[int] = None
    ramp_start: Optional[int] = None
    ramp_end: Optional[int] = None
    cadence_low: Optional[int] = None
    cadence_high: Optional[int] = None
    rpe_low: Optional[int] = None
    rpe_high: Optional[int] = None
    rendering: str = ""


@dataclass
class RepeatBlock:
    repeats: int
    steps: list[Step]


# A section element is either a Step or a RepeatBlock.
SectionElement = object  # documented union; kept loose for the core


@dataclass
class Feasibility:
    satisfied: bool = True
    conflict_report: Optional[str] = None


@dataclass
class GeneratedSession:
    id: str
    generated_at: str
    mode: Mode
    dominant_zone: str
    structural_pattern: Optional[str]
    complementary_zones: list[str]
    warmup: list                  # list[Step | RepeatBlock]
    main_set: list                # list[Step | RepeatBlock]
    cooldown: list                # list[Step | RepeatBlock]
    estimated_tss: float
    estimated_if: float
    feasibility: Feasibility
    summary: str
    markdown_output: str
    progression_id: Optional[str] = None
    generation_seed: Optional[int] = None
    # How estimated_tss was computed: "np_30s" (power), "hrss" (HR with the
    # athlete's own values) or "hrss_typical" (HR, typical profile: approximate)
    tss_method: str = "np_30s"
    # Design observations from validation (a step reaching past its zone,
    # most work outside the requested zone): shown to the athlete, never
    # blocking.
    warnings: list = field(default_factory=list)
