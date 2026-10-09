"""v0.10.0 — the rider's level is a DESIGN CRITERION for the reasoning layer.
It changes how the work is cut into blocks, never the amount of work or its
intensity, and the engine validates nothing about it."""
from engine.gemini_client import (build_user_prompt, level_lines, LEVELS,
                                  build_system_prompt)
from engine.models import GenerationRequest
from engine.generator_v2 import generate_single_v2
from engine.request_parser import PARSE_TOOL_SCHEMA
from test_flex_v070 import prop, step_el, rep, st

REC = dict(is_recovery=True)


def _user(level):
    return build_user_prompt(mode="power", zone="Tempo",
                             target_duration_seconds=2700, target_tss=None,
                             target_if=None, recent=[], level=level)


def test_no_level_leaves_the_prompt_as_before():
    assert "Rider level" not in _user(None)
    assert level_lines(None) == [] and level_lines("expert") == []


def test_each_level_reaches_the_prompt_as_a_criterion_not_a_rule():
    for lv in LEVELS:
        u = _user(lv)
        assert f"Rider level: {lv}" in u
        assert "design criterion, not a rule" in u
        assert "Illustration only, not numbers to follow" in u
        assert "does not change with the level" in u


def test_levels_describe_how_the_work_is_cut():
    assert "shorter blocks" in _user("basic")
    assert "long, continuous blocks" in _user("advanced")
    assert "fewer, longer blocks" in _user("intermediate")


def test_the_system_prompt_stays_free_of_level_rules():
    s = build_system_prompt().lower()
    assert "basic" not in s and "beginner" not in s


def test_parser_schema_knows_the_level_words():
    props = PARSE_TOOL_SCHEMA["input_schema"]["properties"]
    assert props["level"]["enum"] == ["basic", "intermediate", "advanced"]
    d = props["level"]["description"].lower()
    for w in ("principiante", "novato", "avanzado", "intermedio", "beginner"):
        assert w in d
    assert "level" not in PARSE_TOOL_SCHEMA["input_schema"]["required"]


def test_the_level_travels_with_the_request_to_gemini():
    seen = []
    p = prop([rep(4, st(600, 78, 84, "Tempo"),
                  st(180, 50, 55, "ActiveRecovery", **REC))])

    def transport(system, user, tools, web):
        seen.append(user)
        return p
    generate_single_v2(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo",
        level="basic"), transport=transport)
    assert "Rider level: basic" in seen[0]


def test_the_engine_validates_nothing_about_the_level():
    # a basic rider asked for, Gemini answers one continuous block: accepted.
    p = prop([step_el(2400, 78, 84, "Tempo")])
    sess = generate_single_v2(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo",
        level="basic"), transport=lambda *a: p)
    assert sess.dominant_zone == "Tempo"


def test_level_is_optional_on_the_request():
    assert GenerationRequest(kind="single_session", mode="power").level is None
