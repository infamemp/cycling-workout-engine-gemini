"""
assembler.py — Assemble structure components into the final .md output
(literal intervals.icu syntax with # headers, spec 12.1) and compute the
real (rounded) TSS estimate (spec 16.4).
"""

from __future__ import annotations
from dataclasses import dataclass
from .models import Step, RepeatBlock
from .render import validate_output
from . import tss as tssmod


def _segments_from_step(s: Step) -> list[tssmod.Segment]:
    """Convert a step to load segments. A ramp keeps both ends: its target
    moves linearly second by second, as the platform executes it."""
    if s.is_ramp:
        return [tssmod.Segment(float(s.duration_seconds), s.ramp_start / 100.0,
                               s.ramp_end / 100.0)]
    frac = ((s.flat_low + s.flat_high) / 2.0) / 100.0
    return [tssmod.Segment(float(s.duration_seconds), frac)]


def _collect_segments(elements: list) -> list[tssmod.Segment]:
    segs: list[tssmod.Segment] = []
    for el in elements:
        if isinstance(el, RepeatBlock):
            for _ in range(el.repeats):
                for st in el.steps:
                    segs += _segments_from_step(st)
        else:  # Step
            segs += _segments_from_step(el)
    return segs


@dataclass(frozen=True)
class LoadEstimate:
    """Design-time load of a built session (spec 16.4/16.6).
    method: "np_30s" (power) | "hrss" (HR, athlete's own LTHR/max/resting)
    | "hrss_typical" (HR, typical profile stood in: approximate)."""
    tss: float
    intensity_factor: float
    method: str

    @property
    def approximate(self) -> bool:
        return self.method == "hrss_typical"


def session_segments(warmup: list, main_set: list,
                     cooldown: list) -> list[tssmod.Segment]:
    """The whole session as ordered load segments."""
    return (_collect_segments(warmup) + _collect_segments(main_set)
            + _collect_segments(cooldown))


def compute_load(warmup: list, main_set: list, cooldown: list,
                 mode: str = "power",
                 hr_profile: tssmod.HrProfile | None = None) -> LoadEstimate:
    """Real load of the fully-built (rounded) session — spec 16.4: report
    the number of what was built, labeled as a design-time estimate.
    Power: NP with the 30 s rolling average. HR: HRSS (spec 16.6)."""
    segs = session_segments(warmup, main_set, cooldown)
    if mode == "hr":
        load, eq_if, exact = tssmod.hr_session_tss(segs, hr_profile)
        return LoadEstimate(load, eq_if, "hrss" if exact else "hrss_typical")
    return LoadEstimate(tssmod.session_tss(segs),
                        tssmod.intensity_factor(segs), "np_30s")


def compute_tss_if(warmup: list, main_set: list, cooldown: list,
                   mode: str = "power",
                   hr_profile: tssmod.HrProfile | None = None
                   ) -> tuple[float, float]:
    """(TSS, IF) of the built session; see compute_load."""
    est = compute_load(warmup, main_set, cooldown, mode, hr_profile)
    return est.tss, est.intensity_factor


def _render_elements(elements: list) -> list[str]:
    """Render a list of Steps/RepeatBlocks to markdown lines, with the blank
    lines required around repeat blocks (spec 12.2)."""
    lines: list[str] = []
    for el in elements:
        if isinstance(el, RepeatBlock):
            lines.append("")                       # blank line before block
            lines.append(f"{el.repeats}x")
            for st in el.steps:
                lines.append(st.rendering)
            lines.append("")                       # blank line after block
        else:
            lines.append(el.rendering)
    return lines


def elements_seconds(elements: list) -> int:
    """Total seconds of a list of Steps / RepeatBlocks."""
    total = 0
    for el in elements:
        if isinstance(el, RepeatBlock):
            total += el.repeats * sum(s.duration_seconds for s in el.steps)
        else:
            total += el.duration_seconds
    return total


def build_markdown(warmup: list, main_set: list, cooldown: list) -> str:
    """Assemble the complete .md (headers + lines), then run the output gate."""
    out: list[str] = []
    for header, elements in (("# Warmup", warmup), ("# Main Set", main_set),
                             ("# Cooldown", cooldown)):
        if out and out[-1] != "":
            out.append("")
        out.append(header)
        out.append("")
        out += _render_elements(elements)

    # Collapse accidental multiple blank lines to at most one.
    cleaned: list[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip() + "\n"

    # Mandatory output-validation gate (spec 12.3) before returning.
    validate_output(text)
    return text
