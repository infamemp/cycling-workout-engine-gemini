"""v0.9.0 — Gemini's freedom has limits: the session stays the one that was
asked for, and the warmup and cooldown are built, not scribbled."""
import pytest

from engine.proposal import (validate_proposal, ProposalRejected,
                             classify_midpoint, work_seconds_by_class)
from engine.sections import validate_section, SectionRejected
from test_flex_v070 import prop, st, step_el, rep, run, warm, cool

REC = dict(is_recovery=True)


def ramp(sec, a, b):
    return {"element": "ramp", "duration_seconds": sec, "from_pct": a, "to_pct": b}


def step(sec, lo, hi, **kw):
    return dict({"element": "step", "duration_seconds": sec, "low_pct": lo,
                 "high_pct": hi}, **kw)


# --- purpose: a Tempo session stays Tempo -----------------------------------------

def test_the_reported_tempo_ladder_is_rejected():
    # What Gemini produced for "tempo de 45 minutos": 76-80, 81-85, 86-90.
    p = prop([step_el(600, 76, 80, "Tempo"), step_el(600, 81, 85, "Tempo"),
              step_el(600, 86, 90, "Tempo")])
    with pytest.raises(ProposalRejected) as e:
        validate_proposal(p, mode="power", dominant_zone="Tempo")
    msg = str(e.value)
    assert "67%" in msg and "SweetSpot 33%" in msg and "stay a Tempo session" in msg


def test_a_tempo_ladder_that_stays_in_tempo_is_fine():
    p = prop([step_el(600, 76, 80, "Tempo"), step_el(600, 79, 83, "Tempo"),
              step_el(600, 82, 86, "Tempo")])
    validate_proposal(p, mode="power", dominant_zone="Tempo")


def test_a_short_touch_of_sweet_spot_is_a_note_not_a_rejection():
    p = prop([step_el(1500, 78, 84, "Tempo"), step_el(300, 90, 94, "SweetSpot")])
    warns = validate_proposal(p, mode="power", dominant_zone="Tempo")
    assert any("outside Tempo" in w for w in warns)


def test_a_sweet_spot_session_is_not_called_tempo():
    p = prop([step_el(1200, 90, 94, "SweetSpot")])
    validate_proposal(p, mode="power", dominant_zone="SweetSpot")
    with pytest.raises(ProposalRejected):
        validate_proposal(p, mode="power", dominant_zone="Tempo")


def test_label_does_not_buy_the_purpose():
    # Labelled "Threshold" but sitting at 80-85: it is Tempo work.
    p = prop([step_el(1200, 80, 85, "Threshold"), step_el(120, 76, 80, "Tempo")])
    warns = validate_proposal(p, mode="power", dominant_zone="Tempo")
    assert isinstance(warns, list)


def test_vo2_session_cannot_become_anaerobic():
    p = prop([rep(4, st(120, 125, 140, "Anaerobic"),
                  st(180, 50, 55, "ActiveRecovery", **REC)),
              step_el(30, 112, 118, "VO2Max")])
    with pytest.raises(ProposalRejected, match="stay a VO2Max session"):
        validate_proposal(p, mode="power", dominant_zone="VO2Max")


def test_classification_uses_midpoints_and_skips_recovery():
    assert classify_midpoint("power", 78, "Tempo") == "Tempo"
    assert classify_midpoint("power", 88, "Tempo") == "SweetSpot"
    assert classify_midpoint("power", 88, "SweetSpot") == "SweetSpot"
    p = prop([rep(2, st(600, 80, 84, "Tempo"),
                  st(300, 50, 55, "ActiveRecovery", **REC))])
    assert work_seconds_by_class(p, "power", "Tempo") == {"Tempo": 1200}


def test_the_guard_reaches_gemini_as_feedback():
    seen = []
    ladder = prop([step_el(600, 76, 80, "Tempo"), step_el(600, 81, 85, "Tempo"),
                   step_el(600, 86, 90, "Tempo")])
    good = prop([step_el(1800, 78, 84, "Tempo")])

    def transport(system, user, tools, web):
        seen.append(user)
        return ladder if len(seen) == 1 else good
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    sess = generate_single_v2(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo"),
        transport=transport)
    assert len(seen) == 2 and "stay a Tempo session" in seen[1]
    assert sess.dominant_zone == "Tempo"


# --- warmup ---------------------------------------------------------------------------

def test_a_hard_block_flagged_as_preparation_is_rejected():
    # 4m 50-60 / 3m ramp 60-75 / 1m30 80-84 flagged as the preparation
    w = [step(240, 50, 60), ramp(180, 60, 75),
         step(90, 80, 84, is_preparation=True), step(90, 50, 55)]
    with pytest.raises(SectionRejected):
        validate_section("warmup", w, mode="power")


def test_preparation_must_be_last():
    w = [ramp(300, 45, 70), step(90, 50, 55, is_preparation=True),
         step(60, 65, 70)]
    with pytest.raises(SectionRejected, match="preparation"):
        validate_section("warmup", w, mode="power")


def test_the_build_does_not_peak_and_fall_back():
    w = [ramp(300, 45, 78), step(120, 55, 60),
         step(60, 50, 55, is_preparation=True)]
    with pytest.raises(SectionRejected, match="falls back"):
        validate_section("warmup", w, mode="power")


def test_closing_pause_after_the_build_is_welcome_not_a_dip():
    # the build reaches 75%, then a 1-minute very easy pause: valid.
    w = [ramp(300, 45, 75), step(60, 50, 55, is_preparation=True)]
    assert validate_section("warmup", w, mode="power") == 360


def test_the_preparation_is_a_very_easy_pause():
    for lvl in ((70, 75), (60, 66)):
        with pytest.raises(SectionRejected, match="pause"):
            validate_section("warmup", [ramp(300, 45, 70),
                                        step(60, *lvl, is_preparation=True)],
                             mode="power")
    with pytest.raises(SectionRejected, match="pause"):
        validate_section("warmup", [step(240, 60, 70),
                                    step(60, 80, 88, is_preparation=True)],
                         mode="hr")


def test_warmup_floor_power_and_hr():
    with pytest.raises(SectionRejected, match="below 45%"):
        validate_section("warmup", [ramp(300, 40, 70),
                                    step(60, 70, 75, is_preparation=True)],
                         mode="power")
    with pytest.raises(SectionRejected, match="below 60%"):
        validate_section("warmup", [step(240, 55, 65),
                                    step(60, 70, 78, is_preparation=True)],
                         mode="hr")


def test_preparation_length_is_30s_to_2min():
    for sec in (20, 150):
        with pytest.raises(SectionRejected):
            validate_section("warmup", [ramp(300, 45, 70),
                                        step(sec, 50, 55, is_preparation=True)],
                             mode="power")


def test_warmup_must_arrive_at_the_first_work_level():
    p = prop([step_el(1800, 78, 84, "Tempo")])
    p["warmup"] = [ramp(300, 45, 55), step(60, 50, 55, is_preparation=True)]
    with pytest.raises(ProposalRejected, match="build should arrive"):
        validate_proposal(p, mode="power", dominant_zone="Tempo")


def test_hard_sessions_need_openers_not_the_full_effort():
    # first work at 150%: the preparation is judged against 100%
    p = prop([rep(6, st(10, 150, 200, "Neuromuscular"),
                  st(180, 50, 55, "ActiveRecovery", **REC))])
    validate_proposal(p, mode="power", dominant_zone="Neuromuscular")


# --- cooldown ---------------------------------------------------------------------------

def test_reported_cooldown_is_rejected():
    # 3m ramp 55->45 then 2m at 40-45
    c = [ramp(180, 55, 45), step(120, 40, 45)]
    with pytest.raises(SectionRejected, match="below 45%"):
        validate_section("cooldown", c, mode="power")


def test_cooldown_only_comes_down():
    c = [ramp(180, 65, 50), step(120, 62, 66)]
    with pytest.raises(SectionRejected, match="only comes down"):
        validate_section("cooldown", c, mode="power")


def test_a_single_smooth_descent_passes():
    assert validate_section("cooldown", [ramp(300, 65, 48)], mode="power") == 300
    assert validate_section("cooldown", [step(120, 65, 70), step(180, 60, 65)],
                            mode="hr") == 300
