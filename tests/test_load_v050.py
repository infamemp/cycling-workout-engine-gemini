"""
test_load_v050.py — v0.5.0: training load computed as Intervals.icu does.

  - Power: NP with the 30 s rolling average, ramps linear (tss.py).
  - HR: HRSS with the athlete's LTHR / max HR / resting HR, or a typical
    profile flagged approximate.
  - athlete.yaml: the athlete's own thresholds, all optional.

The formula tests with hand calculations live in test_core.py.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import tss, assembler  # noqa: E402
from engine.models import GenerationRequest, Athlete  # noqa: E402
from engine.generator import generate_single  # noqa: E402
from engine.athlete_settings import load_athlete, SettingsError  # noqa: E402


# --- athlete.yaml -----------------------------------------------------------------

def test_missing_settings_file_is_empty_athlete(tmp_path):
    a = load_athlete(tmp_path / "athlete.yaml")
    assert a.hr_profile() is None and a.cp_watts is None


def test_settings_file_read(tmp_path):
    f = tmp_path / "athlete.yaml"
    f.write_text("ftp_watts: 250\nlthr_bpm: 160\nmax_hr_bpm: 180\n"
                 "resting_hr_bpm: 55\n", encoding="utf-8")
    a = load_athlete(f)
    assert a.cp_watts == 250
    assert a.hr_profile() == tss.HrProfile(160, 180, 55)


def test_settings_partial_hr_gives_no_profile(tmp_path):
    f = tmp_path / "athlete.yaml"
    f.write_text("lthr_bpm: 160\n", encoding="utf-8")
    assert load_athlete(f).hr_profile() is None


def test_settings_unknown_field_rejected(tmp_path):
    f = tmp_path / "athlete.yaml"
    f.write_text("lthr: 160\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="unknown field"):
        load_athlete(f)


def test_settings_wrong_order_rejected(tmp_path):
    f = tmp_path / "athlete.yaml"
    f.write_text("lthr_bpm: 160\nmax_hr_bpm: 150\nresting_hr_bpm: 55\n",
                 encoding="utf-8")
    with pytest.raises(SettingsError, match="resting < LTHR < max"):
        load_athlete(f)


def test_settings_non_number_rejected(tmp_path):
    f = tmp_path / "athlete.yaml"
    f.write_text("ftp_watts: two hundred\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="positive number"):
        load_athlete(f)


def test_example_file_is_valid():
    a = load_athlete(ROOT / "athlete.example.yaml")
    assert a.hr_profile() is not None


# --- load method reported on the session ----------------------------------------

def test_power_session_load_is_np_30s():
    sess = generate_single(GenerationRequest(kind="single_session", mode="power",
                                             requested_zone="Tempo"), seed=2)
    segs = assembler.session_segments(sess.warmup, sess.main_set, sess.cooldown)
    assert sess.tss_method == "np_30s"
    assert abs(sess.estimated_tss - round(tss.session_tss(segs), 1)) < 1e-9


def test_hr_session_with_profile_is_exact_hrss():
    ath = Athlete(lthr_bpm=160, max_hr_bpm=180, resting_hr_bpm=55)
    sess = generate_single(GenerationRequest(kind="single_session", mode="hr",
                                             requested_zone="Tempo",
                                             athlete=ath), seed=2)
    assert sess.tss_method == "hrss"


def test_hr_session_without_profile_is_flagged():
    sess = generate_single(GenerationRequest(kind="single_session", mode="hr",
                                             requested_zone="Tempo"), seed=2)
    assert sess.tss_method == "hrss_typical"


def test_hr_load_depends_on_resting_hr():
    # The same session costs more for an athlete whose resting HR is higher
    # relative to the work (HRr rises less steeply to LTHR): the profile is
    # really used, not ignored.
    segs = [tss.Segment(2400, 0.85)]
    low, _, _ = tss.hr_session_tss(segs, tss.HrProfile(160, 180, 45))
    high, _, _ = tss.hr_session_tss(segs, tss.HrProfile(160, 180, 70))
    assert low != high


def test_ramp_load_uses_both_ends():
    # A 45->75% ramp is not costed as a flat 60%.
    ramp = tss.session_tss([tss.Segment(600, 0.45, 0.75)])
    flat = tss.session_tss([tss.Segment(600, 0.60)])
    assert ramp > flat
