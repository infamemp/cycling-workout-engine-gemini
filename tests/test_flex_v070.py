"""
test_flex_v070.py — v0.7.0: flexibility and creativity in session design.

The validator now blocks errors, not designs: a step may reach past its
zone, complementary work may outweigh the requested zone (a warning), one
level of sub-repeat is allowed (unrolled before the platform sees it), the
engine derives the complementary zones itself, and the shape library is
offered to the reasoning layer as ideas. Every warmup carries a preparation
interval. Applies to every kind of session: recovery, activation, aerobic,
tempo, sweet spot, threshold, VO2max...

No API key or network needed.
"""

from __future__ import annotations
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import _fit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import shapes, assembler  # noqa: E402
from engine.models import GenerationRequest  # noqa: E402
from engine.generator_v2 import generate_single_v2  # noqa: E402
from engine.proposal import (validate_proposal, ProposalRejected,  # noqa: E402
                             flatten_nested_repeats,
                             derive_complementary_zones)
from engine.gemini_client import build_system_prompt, build_user_prompt  # noqa: E402
from engine.resolve_intensity import resolve_proposal_intensity  # noqa: E402
from engine import tss as tssmod  # noqa: E402


# --- helpers ------------------------------------------------------------------

def warm(total=300):
    """A ramp that builds, then the very easy closing pause."""
    return [{"element": "ramp", "duration_seconds": total - 60,
             "from_pct": 45, "to_pct": 65},
            {"element": "step", "duration_seconds": 60, "low_pct": 50,
             "high_pct": 55, "is_preparation": True}]


def warm_hr(total=300):
    """A climbing staircase, then the very easy closing pause."""
    rest = total - 60
    return [{"element": "step", "duration_seconds": rest // 2,
             "low_pct": 60, "high_pct": 68},
            {"element": "step", "duration_seconds": rest - rest // 2,
             "low_pct": 76, "high_pct": 84},
            {"element": "step", "duration_seconds": 60, "low_pct": 62,
             "high_pct": 70, "is_preparation": True}]


def cool(total=180):
    return [{"element": "ramp", "duration_seconds": total,
             "from_pct": 65, "to_pct": 45}]


def cool_hr(total=180):
    return [{"element": "step", "duration_seconds": total, "low_pct": 60,
             "high_pct": 70}]


def st(sec, lo, hi, zone, **kw):
    return dict({"duration_seconds": sec, "low_pct": lo, "high_pct": hi,
                 "zone_name": zone}, **kw)


def step_el(*a, **kw):
    return dict(st(*a, **kw), element="step")


def rep(n, *steps):
    return {"element": "repeat", "repeats": n, "steps": list(steps)}


def sub(n, *steps):
    return {"element": "repeat", "repeats": n, "steps": list(steps)}


def prop(main, *, mode="power", summary="x", w=300, c=180):
    return _fit({"structural_pattern": "continuous", "summary": summary,
                 "warmup": warm(w) if mode == "power" else warm_hr(w),
                 "cooldown": cool(c) if mode == "power" else cool_hr(c),
                 "main_set": main}, mode)


def run(proposal, zone, mode="power", **req_kw):
    req = GenerationRequest(kind="single_session", mode=mode,
                            requested_zone=zone, **req_kw)
    return generate_single_v2(req, transport=lambda *a: proposal)


def total_seconds(sess):
    return (assembler.elements_seconds(sess.warmup)
            + assembler.elements_seconds(sess.main_set)
            + assembler.elements_seconds(sess.cooldown))


# --- the shape library -----------------------------------------------------------

def test_library_loads_and_every_shape_is_complete():
    lib = shapes.load_library()
    names = [s["name"] for s in lib["shapes"]]
    assert len(names) == len(set(names)) >= 18
    for s in lib["shapes"]:
        assert s["idea"].strip() and s["suits"] and s["levers"]
        assert s["disciplines"]
    assert {"steady_aerobic", "aerobic_touches", "over_unders",
            "activation_openers"} <= set(names)


def test_library_carries_no_intensities():
    text = shapes.DATA_FILE.read_text(encoding="utf-8")
    assert not re.search(r"\d\s*%|% ?FTP|watts", text)


def test_every_zone_of_both_systems_maps_to_a_purpose():
    from engine.zones import POWER_ZONES, HR_ZONES, POWER_SWEETSPOT
    for z in POWER_ZONES + (POWER_SWEETSPOT,):
        assert shapes.purpose_class("power", z.name), z.name
        assert shapes.shapes_for("power", z.name), z.name
    for z in HR_ZONES:
        assert shapes.purpose_class("hr", z.name), z.name
        assert shapes.shapes_for("hr", z.name), z.name


def test_hr_prompt_leaves_out_ramp_shapes():
    assert "single_ramp" in shapes.prompt_block("power", "Tempo")
    assert "single_ramp" not in shapes.prompt_block("hr", "Tempo")


def test_missing_library_never_stops_the_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(shapes, "_cache", None)
    monkeypatch.setattr(shapes, "DATA_FILE", tmp_path / "nope.yaml")
    assert shapes.load_library(tmp_path / "nope.yaml") == {
        "shapes": [], "combinations": []}


def test_library_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("WORKOUT_ENGINE_SHAPES", "off")
    assert shapes.prompt_block("power", "Tempo") == ""
    p = build_user_prompt(mode="power", zone="Tempo",
                          target_duration_seconds=3600, target_tss=None,
                          target_if=None, recent=[])
    assert "NOT a menu" not in p
    monkeypatch.setenv("WORKOUT_ENGINE_SHAPES", "on")
    assert "NOT a menu" in shapes.prompt_block("power", "Tempo")


def test_user_prompt_offers_the_library_as_ideas_not_a_menu():
    p = build_user_prompt(mode="power", zone="Threshold",
                          target_duration_seconds=3600, target_tss=None,
                          target_if=None, recent=[])
    assert "NOT a menu" in p and "over_unders" in p
    assert "no quota" in p


def test_system_prompt_is_criteria_not_cage():
    s = build_system_prompt()
    assert "hard rules" not in s and "DOMINANT" not in s
    assert "never nested" not in s.lower()
    assert "PREPARATION" in s and "sub-repeat" in s
    for kind in ("recovery", "activation", "tempo", "sweet spot", "VO2max"):
        assert kind in s


# --- what is no longer blocked -----------------------------------------------------

def test_step_may_reach_past_its_zone():
    p = prop([step_el(1200, 76, 92, "Tempo")])
    warns = validate_proposal(p, mode="power", dominant_zone="Tempo")
    assert any("past the zone" in w for w in warns)


def test_complementary_work_may_outweigh_the_requested_zone():
    p = prop([step_el(900, 80, 88, "Tempo"),
              step_el(300, 108, 115, "VO2Max")])
    warns = validate_proposal(p, mode="power", dominant_zone="Tempo")
    assert any("outside Tempo" in w and "VO2Max" in w for w in warns)
    assert derive_complementary_zones(p, "Tempo") == ["VO2Max"]


def test_engine_derives_complementary_zones_even_when_declared_wrong():
    p = prop([rep(3, st(540, 80, 88, "Tempo"), st(30, 108, 115, "VO2Max"))])
    p["complementary_stimuli"] = [{"zone": "Anaerobic"}]
    assert derive_complementary_zones(p, "Tempo") == ["Anaerobic", "VO2Max"]


# --- what is still blocked -----------------------------------------------------------

def test_requested_zone_must_appear():
    p = prop([step_el(1200, 94, 99, "Threshold")])
    with pytest.raises(ProposalRejected, match="does not appear"):
        validate_proposal(p, mode="power", dominant_zone="Tempo")


def test_unbelievable_numbers_are_still_rejected():
    p = prop([step_el(600, 80, 900, "Tempo")])
    with pytest.raises(ProposalRejected, match="believable"):
        validate_proposal(p, mode="power", dominant_zone="Tempo")
    p = prop([step_el(600, 90, 130, "Tempo")], mode="hr")
    with pytest.raises(ProposalRejected, match="believable"):
        validate_proposal(p, mode="hr", dominant_zone="Tempo")


def test_recovery_must_still_be_easy_and_the_budget_still_holds():
    p = prop([rep(2, st(300, 80, 88, "Tempo"),
                  st(120, 80, 92, "Tempo", is_recovery=True))])
    with pytest.raises(ProposalRejected, match="too hard"):
        validate_proposal(p, mode="power", dominant_zone="Tempo")
    p = prop([step_el(3600, 80, 88, "Tempo")])
    with pytest.raises(ProposalRejected, match="exceeds budget"):
        validate_proposal(p, mode="power", dominant_zone="Tempo",
                          total_budget_seconds=2400)


def test_warmup_without_preparation_is_rejected_by_the_proposal_check():
    p = prop([step_el(1200, 80, 88, "Tempo")])
    p["warmup"] = [{"element": "ramp", "duration_seconds": 300,
                    "from_pct": 45, "to_pct": 65}]
    with pytest.raises(ProposalRejected, match="no preparation"):
        validate_proposal(p, mode="power", dominant_zone="Tempo")


# --- one level of nesting, unrolled --------------------------------------------------------

def test_nested_block_reaches_the_file_flat_and_with_the_right_time():
    inner = sub(5, st(30, 110, 118, "VO2Max"), st(30, 50, 55, "ActiveRecovery",
                                                  is_recovery=True))
    p = prop([rep(4, inner, st(240, 50, 55, "ActiveRecovery",
                               is_recovery=True))], summary="micro-intervals")
    sess = run(p, "VO2Max")
    md = sess.markdown_output
    assert md.count("4x") == 1                       # one repeat level only
    main = md.split("# Main Set")[1].split("# Cooldown")[0]
    assert len([l for l in main.splitlines() if l.startswith("- ")]) == 11
    expected = 4 * (5 * 60 + 240)
    assert assembler.elements_seconds(sess.main_set) == expected
    assert sess.complementary_zones == ["ActiveRecovery"] or \
        sess.complementary_zones == []


def test_flatten_is_idempotent_and_leaves_flat_proposals_alone():
    p = prop([rep(3, st(300, 80, 88, "Tempo"),
                  st(120, 50, 55, "ActiveRecovery", is_recovery=True))])
    once = flatten_nested_repeats(p)
    assert once == p == flatten_nested_repeats(once)


def test_absurd_unrolling_is_refused():
    p = prop([rep(2, sub(60, st(5, 120, 130, "Anaerobic"),
                         st(5, 50, 55, "ActiveRecovery", is_recovery=True)))])
    with pytest.raises(ProposalRejected, match="too long"):
        flatten_nested_repeats(p)


# --- every kind of session ---------------------------------------------------------------------

REC = dict(is_recovery=True)

CASES = {
    # pure recovery: every step flagged recovery, requested zone still named
    "recovery": ("ActiveRecovery", "power", 2400,
        [step_el(1500, 45, 55, "ActiveRecovery", **REC)]),
    # activation: an easy ride with a few brief efforts and full recovery
    "activation": ("Endurance", "power", 2700,
        [step_el(600, 60, 70, "Endurance"),
         rep(4, st(45, 98, 104, "Threshold"),
             st(150, 50, 55, "ActiveRecovery", **REC)),
         step_el(600, 62, 72, "Endurance")]),
    # aerobic day with a real tempo touch in the middle
    "aerobic_touches": ("Endurance", "power", 5400,
        [step_el(1500, 62, 72, "Endurance"),
         step_el(900, 80, 88, "Tempo"),
         step_el(1500, 62, 72, "Endurance")]),
    # tempo built through zones in one effort
    "tempo_build": ("Tempo", "power", 3600,
        [step_el(600, 76, 80, "Tempo"), step_el(600, 79, 83, "Tempo"),
         step_el(600, 82, 86, "Tempo"),
         step_el(240, 86, 92, "Tempo"),
         step_el(300, 55, 60, "Endurance", **REC),
         step_el(600, 78, 82, "Tempo")]),
    # sweet spot with surges that never go back to easy
    "sweet_spot_surges": ("SweetSpot", "power", 4500,
        [rep(3, st(600, 88, 92, "SweetSpot"), st(30, 110, 118, "VO2Max"),
             st(600, 88, 92, "SweetSpot"),
             st(300, 50, 55, "ActiveRecovery", **REC))]),
    # threshold over-unders; the over runs a little into VO2
    "over_unders": ("Threshold", "power", 4500,
        [rep(3, sub(4, st(120, 102, 107, "Threshold"),
                    st(120, 90, 94, "Threshold")),
             st(300, 50, 55, "ActiveRecovery", **REC))]),
    # VO2max micro-intervals (nested)
    "vo2_micro": ("VO2Max", "power", 3600,
        [rep(3, sub(6, st(30, 112, 120, "VO2Max"),
                    st(30, 50, 55, "ActiveRecovery", **REC)),
             st(300, 50, 55, "ActiveRecovery", **REC))]),
    # anaerobic repeats
    "anaerobic": ("Anaerobic", "power", 3000,
        [rep(6, st(60, 125, 140, "Anaerobic"),
             st(180, 50, 55, "ActiveRecovery", **REC))]),
    # heart rate: aerobic with a tempo block
    "hr_aerobic_touch": ("Aerobic", "hr", 3600,
        [step_el(900, 82, 88, "Aerobic"), step_el(600, 90, 93, "Tempo"),
         step_el(900, 82, 88, "Aerobic")]),
    # heart rate: threshold-ish staircase build
    "hr_build": ("SubThreshold", "hr", 3600,
        [step_el(480, 94, 96, "SubThreshold"), step_el(480, 96, 98, "SubThreshold"),
         step_el(300, 98, 101, "SubThreshold"),
         step_el(300, 70, 78, "Aerobic", **REC)]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_kind_of_session_builds_and_fits(name):
    zone, mode, minutes_s, main = CASES[name]
    w, c = 600, 300
    main_s = sum(
        (e["duration_seconds"] if e["element"] == "step" else 0)
        for e in main)
    proposal = prop(main, mode=mode, summary=name, w=w, c=c)
    sess = run(proposal, zone, mode=mode)
    assert sess.dominant_zone == zone
    assert sess.markdown_output.startswith("# Warmup")
    warmup_md = sess.markdown_output.split("# Main Set")[0]
    assert warmup_md.count("- ") >= 2                  # build + preparation
    assert sess.estimated_tss > 0
    assert total_seconds(sess) > 0


def test_warnings_reach_the_session_object():
    zone, mode, _, main = CASES["tempo_build"]
    sess = run(prop(main, summary="build"), zone)
    assert any("past the zone" in w for w in sess.warnings)
    zone, mode, _, main = CASES["over_unders"]
    sess = run(prop(main, summary="ou"), zone)
    assert any("past the zone" in w for w in sess.warnings)
    zone, mode, _, main = CASES["recovery"]
    assert run(prop(main, summary="rec"), zone).warnings == []


def test_aerobic_day_with_a_big_touch_keeps_its_purpose():
    zone, mode, _, main = CASES["aerobic_touches"]
    sess = run(prop(main), zone)
    assert sess.dominant_zone == "Endurance"
    assert sess.complementary_zones == ["Tempo"]
    # a 23% Tempo touch is allowed; it is reported, not rejected
    assert any("outside Endurance" in w for w in sess.warnings)


# --- TSS target with a build through zones -----------------------------------------------------

def test_tss_target_resolves_over_a_build_that_crosses_zones():
    main = [step_el(600, 76, 80, "Tempo"), step_el(600, 79, 83, "Tempo"),
            step_el(600, 82, 86, "Tempo")]
    p = prop(main, w=600, c=300)
    sess = run(p, "Tempo", target_if=0.80)
    # the zone-wide mean must sit in Tempo; each step keeps its place in the build
    assert abs(sess.estimated_if - 0.80) / 0.80 < 0.05
    lows = [s.flat_low for s in sess.main_set]
    assert lows == sorted(lows) and lows[0] < lows[-1]


def test_infeasible_mean_is_still_reported_with_numbers():
    p = prop([step_el(1800, 80, 88, "Tempo")], w=600, c=300)
    from engine.resolve_intensity import IntensityInfeasible
    segs = [tssmod.Segment(300, 0.6)]
    with pytest.raises(IntensityInfeasible, match="outside the Tempo zone"):
        resolve_proposal_intensity(
            flatten_nested_repeats(p), mode="power", dominant_zone="Tempo",
            np_target_frac=1.10, before_segments=segs, after_segments=segs)


# --- warnings shown to the athlete ------------------------------------------------------------------

def test_pedir_shows_design_notes(capsys, tmp_path, monkeypatch):
    import pedir
    from engine.generator import generate_single
    monkeypatch.setenv("WORKOUT_ENGINE_WORKOUTS", str(tmp_path))
    sess = generate_single(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo",
        target_duration_seconds=3000), seed=1)
    sess.warnings = ["a Tempo step runs 75-105%, past the zone"]
    for lang in ("es", "en"):
        pedir._show_session(sess, pedir._STRINGS[lang])
    out = capsys.readouterr().out
    assert "Notas de diseño" in out and "Design notes" in out
    assert "past the zone" in out
