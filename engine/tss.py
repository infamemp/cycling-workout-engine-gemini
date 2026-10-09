"""
tss.py — Training load of a planned session, computed the way Intervals.icu
computes it (spec Section 16, v2.6).

POWER — Normalized Power with the 30-second rolling average.
    The session is expanded to a 1 Hz power stream (ramps change linearly
    second by second), smoothed with a 30 s rolling average, raised to the
    4th power, averaged, and the 4th root taken:

        NP  = ( mean( rolling30(p)^4 ) )^(1/4)        (fraction of FTP)
        IF  = NP
        TSS = hours x IF^2 x 100

    Evidence (2026-10-08): 85 real planned power workouts from the head
    coach's Intervals.icu calendars, recomputed here and compared with the
    load Intervals.icu stored for each one: mean absolute error 0.48 TSS,
    largest 1.4. The two methods this replaces were further off on the same
    85 workouts: the simplified 4th-power average without the rolling window
    (engine v0.4.x) was off by up to 58 TSS on short efforts, and a per-step
    sum of hours x IF^2 x 100 under-read interval sessions by up to 11 TSS
    (mean -4%). The 30 s window is what makes 30/30s and sprints count less
    than their raw 4th power would say.

HEART RATE — HRSS (normalised TRIMP), the method the Intervals.icu workout
    builder uses for heart-rate workouts. Each second's heart rate is the
    target %LTHR times the athlete's LTHR (whole bpm), and

        HRr      = (HR - resting HR) / (max HR - resting HR)
        TRIMP/s  = (1/60) x HRr x 0.64 x e^(1.92 x HRr)
        HRSS     = 100 x TRIMP(session) / TRIMP(60 min at LTHR)

    so one hour at LTHR is 100, the same scale as TSS. HRSS needs the
    athlete's LTHR, max HR and resting HR. With all three known this is the
    formula Intervals.icu applies; it keeps the thresholds of the day a
    workout was planned, so a later change there moves its number, not this
    one. The check against real HR workouts is weaker than for power (2 of
    8 reproduced with today's thresholds; see CHANGELOG v0.5.0). Without them the engine uses a
    typical profile (max HR = 1.09 x LTHR, resting HR = 0.37 x LTHR) and
    says the figure is approximate.

Every figure here is a design-time estimate; the platform's own computation
on upload is the authoritative one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

NP_WINDOW_SECONDS = 30

# HRSS constants (Banister TRIMP as Intervals.icu applies it). The 0.64
# factor cancels in the normalisation; it is kept so TRIMP values read the
# same as other software's.
TRIMP_A = 0.64
TRIMP_B = 1.92

# Typical profile used only when the athlete's own values are missing.
TYPICAL_MAX_HR_RATIO = 1.09      # max HR / LTHR
TYPICAL_REST_HR_RATIO = 0.37     # resting HR / LTHR
TYPICAL_LTHR_BPM = 160


@dataclass(frozen=True)
class Segment:
    """A planned segment. `power_frac` is the target as a fraction of the
    threshold (FTP for power, LTHR for heart rate). A ramp sets `end_frac`:
    the target then moves linearly from power_frac to end_frac."""
    duration_seconds: float
    power_frac: float
    end_frac: Optional[float] = None


@dataclass(frozen=True)
class HrProfile:
    lthr_bpm: float
    max_hr_bpm: float
    resting_hr_bpm: float

    def valid(self) -> bool:
        return (self.resting_hr_bpm < self.lthr_bpm < self.max_hr_bpm)


# --- Session-level algebra (exact) -------------------------------------------

def tss_from(duration_seconds: float, intensity_factor: float) -> float:
    hours = duration_seconds / 3600.0
    return hours * (intensity_factor ** 2) * 100.0


def duration_from(tss: float, intensity_factor: float) -> float:
    """Seconds required to reach `tss` at the given IF."""
    if intensity_factor <= 0:
        raise ValueError("IF must be > 0")
    hours = tss / ((intensity_factor ** 2) * 100.0)
    return hours * 3600.0


def if_from(tss: float, duration_seconds: float) -> float:
    """IF required to reach `tss` in the given duration."""
    if duration_seconds <= 0:
        raise ValueError("duration must be > 0")
    hours = duration_seconds / 3600.0
    return (tss / (hours * 100.0)) ** 0.5


# --- The 1 Hz stream ---------------------------------------------------------

def stream(segments: list[Segment]) -> list[float]:
    """Expand segments to one target value per second. Durations are whole
    seconds after rounding (spec 16.4); a ramp moves linearly, sampled at the
    middle of each second."""
    out: list[float] = []
    for s in segments:
        n = int(round(s.duration_seconds))
        if n <= 0:
            continue
        if s.end_frac is None or s.end_frac == s.power_frac:
            out.extend([s.power_frac] * n)
        else:
            a, b = s.power_frac, s.end_frac
            out.extend(a + (b - a) * (i + 0.5) / n for i in range(n))
    return out


def total_seconds(segments: list[Segment]) -> int:
    return sum(int(round(s.duration_seconds)) for s in segments
               if int(round(s.duration_seconds)) > 0)


# --- Power: Normalized Power ---------------------------------------------------

def normalized_power_frac(segments: list[Segment]) -> float:
    """NP as a fraction of FTP: 30 s rolling average (over the seconds
    available at the very start), 4th power, mean, 4th root."""
    p = stream(segments)
    if not p:
        raise ValueError("total duration must be > 0")
    w = NP_WINDOW_SECONDS
    acc = 0.0
    fourth = 0.0
    for i, v in enumerate(p):
        acc += v
        if i >= w:
            acc -= p[i - w]
        avg = acc / min(w, i + 1)
        fourth += avg ** 4
    return (fourth / len(p)) ** 0.25


def intensity_factor(segments: list[Segment]) -> float:
    """IF == NP / FTP; segments are already fractions of FTP."""
    return normalized_power_frac(segments)


def session_tss(segments: list[Segment]) -> float:
    """TSS of a fully specified power session."""
    return tss_from(total_seconds(segments), intensity_factor(segments))


# --- Solving for one unknown intensity ---------------------------------------

class InfeasibleError(ValueError):
    """Raised when a TSS/IF target cannot be met within the given structure.
    Per spec 16.3 the engine reports this rather than forcing a value."""


def solve_scale(build: Callable[[float], list[Segment]],
                np_target_frac: float,
                lo: float = 0.0, hi: float = 3.0,
                tol: float = 1e-7) -> float:
    """Find x such that NP(build(x)) == np_target_frac.

    `build(x)` returns the ordered session with the unknown work intensity
    set to x (and any other work steps at their fixed ratio to x). NP rises
    monotonically with x, so bisection converges; there is no closed form
    once the 30 s rolling average is in the formula. Raises InfeasibleError
    when the target lies outside what any x in [lo, hi] can reach."""
    f_lo = normalized_power_frac(build(lo))
    f_hi = normalized_power_frac(build(hi))
    if np_target_frac < f_lo - 1e-12:
        raise InfeasibleError(
            "target intensity not reachable: the fixed segments alone "
            "already exceed the target NP")
    if np_target_frac > f_hi + 1e-12:
        raise InfeasibleError(
            "target intensity not reachable within any plausible work power")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if normalized_power_frac(build(mid)) < np_target_frac:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


# --- Heart rate: HRSS --------------------------------------------------------

def typical_hr_profile(lthr_bpm: float | None = None) -> HrProfile:
    lt = float(lthr_bpm or TYPICAL_LTHR_BPM)
    return HrProfile(lthr_bpm=lt,
                     max_hr_bpm=round(lt * TYPICAL_MAX_HR_RATIO),
                     resting_hr_bpm=round(lt * TYPICAL_REST_HR_RATIO))


def _trimp_per_minute(hrr: float) -> float:
    return hrr * TRIMP_A * math.exp(TRIMP_B * hrr)


def hrss(segments: list[Segment], profile: HrProfile) -> float:
    """HRSS of a planned heart-rate session (segments in fractions of
    LTHR). Each second's target is converted to whole bpm, as Intervals.icu
    sums HRSS bpm by bpm."""
    if not profile.valid():
        raise ValueError("HR profile needs resting < LTHR < max")
    span = profile.max_hr_bpm - profile.resting_hr_bpm
    hrr_lt = (profile.lthr_bpm - profile.resting_hr_bpm) / span
    ref = 60.0 * _trimp_per_minute(hrr_lt)          # one hour at LTHR
    trimp = 0.0
    for frac in stream(segments):
        bpm = round(frac * profile.lthr_bpm)
        hrr = max(0.0, min(1.0, (bpm - profile.resting_hr_bpm) / span))
        trimp += _trimp_per_minute(hrr) / 60.0
    return 100.0 * trimp / ref


def hr_session_tss(segments: list[Segment],
                   profile: HrProfile | None = None) -> tuple[float, float, bool]:
    """HR-mode design-time load. Returns (hrss, equivalent IF, exact) where
    `exact` is False when the typical profile stood in for the athlete's
    own LTHR / max HR / resting HR. The equivalent IF comes from the session
    algebra: IF = sqrt(HRSS / (hours x 100))."""
    exact = profile is not None and profile.valid()
    prof = profile if exact else typical_hr_profile(
        profile.lthr_bpm if profile else None)
    load = hrss(segments, prof)
    t = total_seconds(segments)
    eq_if = if_from(load, t) if load > 0 and t > 0 else 0.0
    return load, eq_if, exact
