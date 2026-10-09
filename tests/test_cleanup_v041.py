"""
test_cleanup_v041.py — v0.4.1 cleanup.

  - The HR warmup staircase content check (_check_hr_staircase, added in
    v0.4.0). The v0.4.0 CHANGELOG listed 8 tests for it that were never
    committed; these are those cases.
  - Unknown proposal fields are rejected (the API schema cannot say
    additionalProperties: false, so the engine checks it).
  - Model settings: default model, no temperature anywhere, JSON parsing.

No API key or network needed.
"""

from __future__ import annotations
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.proposal import validate_proposal, ProposalRejected  # noqa: E402
from engine import llm_config  # noqa: E402


def _hr_proposal(stair):
    """v0.6.0: the staircase is the warmup itself, as steps. Each test
    triple is [low_pct, high_pct, seconds] and is passed through as given,
    so malformed values reach the validator unchanged."""
    warm = []
    for t in stair:
        if isinstance(t, (list, tuple)) and len(t) == 3:
            warm.append({"element": "step", "low_pct": t[0], "high_pct": t[1],
                         "duration_seconds": t[2]})
        else:
            warm.append({"element": "step", "low_pct": t[0] if t else None})
    return {
        "structural_pattern": "classic_interval",
        "summary": "HR tempo",
        "warmup": warm,
        "cooldown": [{"element": "step", "duration_seconds": 300,
                      "low_pct": 60, "high_pct": 70}],
        "main_set": [
            {"element": "repeat", "repeats": 3, "steps": [
                {"duration_seconds": 360, "low_pct": 90, "high_pct": 93,
                 "zone_name": "Tempo"},
                {"duration_seconds": 180, "low_pct": 70, "high_pct": 80,
                 "zone_name": "Recovery", "is_recovery": True},
            ]},
        ],
    }


def _check(stair):
    validate_proposal(_hr_proposal(stair), mode="hr", dominant_zone="Tempo")


# --- HR staircase content ------------------------------------------------------

def test_staircase_valid_ascending_passes():
    _check([[50, 60, 120], [60, 70, 120], [70, 80, 120]])


def test_staircase_equal_lows_pass():
    # Holding a level is not stepping down.
    _check([[60, 70, 120], [60, 72, 120]])


def test_staircase_descending_rejected():
    with pytest.raises(ProposalRejected, match="climb"):
        _check([[70, 80, 120], [60, 70, 120]])


def test_staircase_wrong_length_rejected():
    with pytest.raises(ProposalRejected, match="non-integer"):
        _check([[50, 60]])


def test_staircase_non_integer_rejected():
    with pytest.raises(ProposalRejected, match="non-integer"):
        _check([[50, 60.5, 120]])


def test_staircase_bool_is_not_an_integer():
    with pytest.raises(ProposalRejected, match="non-integer"):
        _check([[50, 60, True]])


def test_staircase_low_above_high_rejected():
    with pytest.raises(ProposalRejected, match="low_pct 70 >"):
        _check([[70, 60, 120]])


def test_staircase_negative_rejected():
    with pytest.raises(ProposalRejected, match="negative"):
        _check([[-5, 60, 120]])


def test_staircase_zero_seconds_rejected():
    with pytest.raises(ProposalRejected, match="must be positive"):
        _check([[50, 60, 0]])


def test_ramps_are_power_only():
    # v0.6.0: a power warmup may ramp; heart rate cannot follow a ramp.
    p = _hr_proposal([[50, 60, 120]])
    p["warmup"] = [{"element": "ramp", "duration_seconds": 300,
                    "from_pct": 60, "to_pct": 80}]
    with pytest.raises(ProposalRejected, match="power-mode only"):
        validate_proposal(p, mode="hr", dominant_zone="Tempo")
    p["main_set"][0]["steps"][0].update(low_pct=80, high_pct=88)
    p["main_set"][0]["steps"][1].update(low_pct=50, high_pct=55,
                                        zone_name="ActiveRecovery")
    p["warmup"][0].update(from_pct=45, to_pct=70)
    validate_proposal(p, mode="power", dominant_zone="Tempo")


# --- Unknown fields ----------------------------------------------------------

def test_unknown_top_level_field_rejected():
    p = _hr_proposal([[50, 60, 120]])
    p["cooldown_secs"] = 120
    with pytest.raises(ProposalRejected, match="cooldown_secs"):
        validate_proposal(p, mode="hr", dominant_zone="Tempo")


def test_unknown_step_field_rejected():
    p = _hr_proposal([[50, 60, 120]])
    p["main_set"][0]["steps"][0]["cadence"] = 90
    with pytest.raises(ProposalRejected, match="cadence"):
        validate_proposal(p, mode="hr", dominant_zone="Tempo")


def test_nested_repeat_still_reported_as_nested():
    p = _hr_proposal([[50, 60, 120]])
    p["main_set"][0]["steps"].append({"element": "repeat", "repeats": 2,
                                      "duration_seconds": 60, "low_pct": 90,
                                      "high_pct": 93, "zone_name": "Tempo"})
    with pytest.raises(ProposalRejected, match="nested"):
        validate_proposal(p, mode="hr", dominant_zone="Tempo")


# --- Model settings ------------------------------------------------------------

def test_default_model_is_current():
    assert llm_config.DEFAULT_MODEL == "gemini-3.8-flash"


def test_no_temperature_anywhere():
    # Gemini 3 loops or degrades below the default temperature of 1.0.
    pattern = re.compile(r"temperature\s*=")
    offenders = [p.name for p in (ROOT / "engine").glob("*.py")
                 if pattern.search(p.read_text(encoding="utf-8"))]
    offenders += [p.name for p in ROOT.glob("*.py")
                  if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_parse_json_plain_and_fenced():
    assert llm_config.parse_json_text('{"a": 1}') == {"a": 1}
    assert llm_config.parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm_config.parse_json_text('```\n{"a": 2}\n```') == {"a": 2}


def test_parse_json_empty_is_a_clear_error():
    with pytest.raises(RuntimeError, match="empty"):
        llm_config.parse_json_text("")
