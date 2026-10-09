"""
test_sections_v060.py — v0.6.0: warmup and cooldown designed per session.

  - The reasoning layer designs both; Python checks only sanity and
    arithmetic (start easy, cooldown easy and ending easy, HR steps that
    climb, a sanity length) and adopts a user-requested length exactly.
  - The offline generator respects the requested total duration.
  - A missing resting HR takes Intervals.icu's default of 60 bpm.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import sections, assembler  # noqa: E402
from engine.sections import validate_section, SectionRejected  # noqa: E402
from engine.models import GenerationRequest, Athlete  # noqa: E402
from engine.generator import generate_single  # noqa: E402
from engine.generator_v2 import generate_single_v2  # noqa: E402
from engine.proposal import ProposalRejected  # noqa: E402
from engine.gemini_client import build_user_prompt  # noqa: E402
from engine.request_parser import PARSE_TOOL_SCHEMA  # noqa: E402


def ramp(sec, a, b):
    return {"element": "ramp", "duration_seconds": sec, "from_pct": a, "to_pct": b}


def step(sec, lo, hi):
    return {"element": "step", "duration_seconds": sec, "low_pct": lo, "high_pct": hi}


def prep(sec, lo, hi):
    """The preparation interval every warmup carries (v0.7.0)."""
    return dict(step(sec, lo, hi), is_preparation=True)


def warm_of(total, a=45, b=70):
    """A valid warmup of `total` seconds: a ramp, then a 60 s preparation."""
    return [ramp(total - 60, a, b), prep(60, 70, 75)]


# --- section checks ---------------------------------------------------------------

def test_short_session_warmup_and_cooldown_pass():
    assert validate_section("warmup", warm_of(300), mode="power") == 300
    assert validate_section("cooldown", [ramp(150, 65, 45)], mode="power") == 150


def test_warmup_with_openers_passes():
    warm = [ramp(480, 45, 75),
            {"element": "repeat", "repeats": 3,
             "steps": [step(30, 110, 120), step(60, 50, 55)]},
            prep(120, 55, 60)]
    assert validate_section("warmup", warm, mode="power") == 480 + 270 + 120


def test_warmup_must_start_easy():
    with pytest.raises(SectionRejected, match="start easy"):
        validate_section("warmup", [step(300, 85, 90)], mode="power")


def test_cooldown_must_stay_and_end_easy():
    with pytest.raises(SectionRejected, match="keep it easy"):
        validate_section("cooldown", [step(300, 80, 90)], mode="power")
    with pytest.raises(SectionRejected, match="end easy"):
        validate_section("cooldown", [ramp(300, 50, 72)], mode="power")


def test_hr_warmup_must_climb_and_has_no_ramps():
    with pytest.raises(SectionRejected, match="climb"):
        validate_section("warmup", [step(120, 70, 75), step(120, 60, 65)], mode="hr")
    with pytest.raises(SectionRejected, match="power-mode only"):
        validate_section("warmup", [ramp(300, 60, 80)], mode="hr")


def test_requested_length_is_exact():
    assert validate_section("warmup", warm_of(900), mode="power",
                            requested_seconds=900) == 900
    with pytest.raises(SectionRejected, match="exactly 900s"):
        validate_section("warmup", warm_of(600), mode="power",
                         requested_seconds=900)


def test_sanity_limit_unless_requested():
    long = warm_of(30 * 60)
    with pytest.raises(SectionRejected, match="sanity"):
        validate_section("warmup", long, mode="power")
    assert validate_section("warmup", long, mode="power",
                            requested_seconds=30 * 60) == 1800


# --- the preparation interval (v0.7.0) ---------------------------------------------

def test_warmup_without_preparation_is_rejected():
    with pytest.raises(SectionRejected, match="no preparation interval"):
        validate_section("warmup", [ramp(300, 45, 70)], mode="power")


def test_preparation_is_two_minutes_at_most():
    assert validate_section("warmup", [ramp(240, 45, 65), prep(120, 70, 75)],
                            mode="power") == 360
    with pytest.raises(SectionRejected, match="between 30s and 120s"):
        validate_section("warmup", [ramp(240, 45, 65), prep(121, 70, 75)],
                         mode="power")


def test_preparation_is_short():
    with pytest.raises(SectionRejected, match="keep it short"):
        validate_section("warmup", [ramp(300, 45, 65), prep(180, 70, 75)],
                         mode="power")
    with pytest.raises(SectionRejected, match="keep it short"):
        validate_section("warmup", [ramp(300, 45, 65), prep(10, 70, 75)],
                         mode="power")


def test_preparation_cannot_be_the_whole_warmup():
    with pytest.raises(SectionRejected, match="whole warmup"):
        validate_section("warmup", [prep(120, 60, 70)], mode="power")
    # a very short warmup may be only the preparation
    assert validate_section("warmup", [prep(90, 60, 70)], mode="power") == 90


def test_preparation_may_be_a_ramp_and_belongs_to_the_warmup_only():
    warm = [ramp(240, 45, 65), dict(ramp(90, 65, 80), is_preparation=True)]
    assert validate_section("warmup", warm, mode="power") == 330
    with pytest.raises(SectionRejected, match="warmup only"):
        validate_section("cooldown", [dict(ramp(180, 65, 45),
                                           is_preparation=True)], mode="power")


def test_hr_warmup_preparation_is_the_last_step_of_the_staircase():
    warm = [step(180, 60, 68), step(180, 68, 76), prep(90, 76, 84)]
    assert validate_section("warmup", warm, mode="hr") == 450


def test_offline_defaults_carry_a_preparation():
    for mode in ("power", "hr"):
        for total in (1200, 1800, 3600, 7200):
            warm, cool = sections.default_sections(mode, total)
            validate_section("warmup", warm, mode=mode)
            validate_section("cooldown", cool, mode=mode)
        warm, _ = sections.default_sections(mode, 3600, warmup_seconds=75)
        assert validate_section("warmup", warm, mode=mode) == 75


def test_unknown_field_in_section_rejected():
    with pytest.raises(SectionRejected, match="unknown field"):
        validate_section("warmup", [dict(ramp(300, 45, 70), zone_name="x")],
                         mode="power")


# --- through the generator ----------------------------------------------------

def _proposal(warm, cool):
    return {
        "structural_pattern": "classic_interval",
        "summary": "tempo",
        "warmup": warm, "cooldown": cool,
        "warmup_cooldown_rationale": "short session: brief warmup",
        "main_set": [{"element": "repeat", "repeats": 3, "steps": [
            {"duration_seconds": 480, "low_pct": 80, "high_pct": 88,
             "zone_name": "Tempo"},
            {"duration_seconds": 120, "low_pct": 50, "high_pct": 55,
             "zone_name": "ActiveRecovery", "is_recovery": True}]}],
    }


def test_designed_sections_are_rendered_as_proposed():
    prop = _proposal([ramp(240, 45, 65), prep(60, 70, 75)], [step(150, 50, 55)])
    sess = generate_single_v2(
        GenerationRequest(kind="single_session", mode="power", requested_zone="Tempo"),
        transport=lambda *a: prop)
    md = sess.markdown_output
    assert "- 4m ramp 45-65%" in md.split("# Main Set")[0]
    assert "- 1m 70-75%" in md.split("# Main Set")[0]      # the preparation
    assert "- 2m30s 50-55%" in md.split("# Cooldown")[1]
    assert "45-55%" not in md.split("# Main Set")[0]   # no fixed prep block


def test_user_requested_warmup_is_enforced_and_fed_back():
    calls = []

    def transport(system, user, tools, web):
        calls.append(user)
        # First answer ignores the request, second follows it.
        w = 300 if len(calls) == 1 else 900
        return _proposal(warm_of(w, 45, 75), [ramp(180, 65, 45)])

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", warmup_seconds=900)
    sess = generate_single_v2(req, transport=transport)
    assert "exactly 15 min" in calls[0]                 # asked in the prompt
    assert "exactly 900s" in calls[1]                   # rejection fed back
    assert assembler.elements_seconds(sess.warmup) == 900


def test_prompt_mentions_requested_lengths_only_when_given():
    p = build_user_prompt(mode="power", zone="Tempo", target_duration_seconds=3600,
                          target_tss=None, target_if=None, recent=[],
                          warmup_seconds=600, cooldown_seconds=300)
    assert "WARMUP at exactly 10 min" in p and "COOLDOWN at exactly 5 min" in p
    p2 = build_user_prompt(mode="power", zone="Tempo", target_duration_seconds=3600,
                           target_tss=None, target_if=None, recent=[])
    assert "exactly" not in p2


def test_parser_can_carry_warmup_and_cooldown_minutes():
    props = PARSE_TOOL_SCHEMA["input_schema"]["properties"]
    assert "warmup_minutes" in props and "cooldown_minutes" in props


# --- offline generator respects the duration ----------------------------------------

@pytest.mark.parametrize("minutes", [30, 45, 50, 60, 75, 90])
@pytest.mark.parametrize("mode", ["power", "hr"])
def test_offline_session_fits_requested_duration(minutes, mode):
    sess = generate_single(GenerationRequest(
        kind="single_session", mode=mode, requested_zone="Tempo",
        target_duration_seconds=minutes * 60), seed=1)
    total = (assembler.elements_seconds(sess.warmup)
             + assembler.elements_seconds(sess.main_set)
             + assembler.elements_seconds(sess.cooldown))
    assert 0.8 * minutes * 60 <= total <= minutes * 60


def test_offline_uses_requested_warmup_and_cooldown():
    sess = generate_single(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo",
        target_duration_seconds=3600, warmup_seconds=900, cooldown_seconds=420),
        seed=1)
    assert assembler.elements_seconds(sess.warmup) == 900
    assert assembler.elements_seconds(sess.cooldown) == 420


def test_offline_short_session_gets_brief_sections():
    w, c = sections.default_sections("power", 30 * 60)
    assert sections.section_seconds(w) == 300 and sections.section_seconds(c) == 180


# --- resting HR default --------------------------------------------------------

def test_missing_resting_hr_uses_intervals_default():
    prof = Athlete(lthr_bpm=175, max_hr_bpm=216).hr_profile()
    assert prof is not None and prof.resting_hr_bpm == 60
    sess = generate_single(GenerationRequest(
        kind="single_session", mode="hr", requested_zone="Tempo",
        athlete=Athlete(lthr_bpm=175, max_hr_bpm=216)), seed=1)
    assert sess.tss_method == "hrss"
