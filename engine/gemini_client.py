"""
gemini_client.py — The Gemini reasoning layer (spec Section 9).
Replaces claude_client.py.

Web search architecture (two-call pattern):
  Gemini's structured-output mode (response_schema) cannot be combined with
  the google_search grounding tool in the same request (as of the current
  Gemini 2.x/3.x generation, this raises a 400 INVALID_ARGUMENT). Since
  live search is used here to widen variety/creativity/methodology, not to
  fetch facts the model lacks, we split it into two calls:
    1. RESEARCH call — google_search enabled, free-form prose output.
       Gathers real structural approaches/methodology relevant to this
       exact request (zone, mode, duration) that a single default
       generation would tend not to surface.
    2. STRUCTURE call — response_schema enabled, no tools. Takes the
       research notes as extra context and returns the validated JSON
       proposal. Python still validates/rebuilds everything deterministically
       regardless of what either call produced.
"""
from __future__ import annotations
from typing import Callable, Optional

from .proposal import PROPOSAL_TOOL_SCHEMA
from .catalog import CatalogEntry
from .llm_config import (MODEL, THINKING_RESEARCH, THINKING_STRUCTURE,
                         thinking_config, parse_json_text)
from . import shapes

Transport = Callable[[str, str, list, bool], dict]

# Model, thinking levels and the no-temperature rule live in llm_config.py.


def build_system_prompt() -> str:
    return (
        "You are the reasoning core of an indoor cycling workout generator, "
        "and you think like an experienced coach. You design the STRUCTURE "
        "of one workout: warmup, main set and cooldown. This applies to "
        "every kind of session the athlete can ask for: recovery, "
        "activation, aerobic endurance, tempo, sweet spot, threshold, VO2max, "
        "anaerobic, neuromuscular, and mixtures of them. You reason from "
        "physiology and methodology, never from a fixed menu.\n\n"
        "THE PURPOSE IS THE REQUESTED ZONE. It is what the session is for "
        "and it must carry the session: at least 70% of the work (judged by "
        "the middle of each step's range) has to sit in the requested zone. "
        "How that work is arranged is your design: steady blocks, "
        "intervals, ramps, builds, over-unders, ladders, pyramids, surges, "
        "rolling intensity, touches of harder work inside an easy day. A "
        "step may reach a little past its zone when the design calls for "
        "it. Other zones are welcome as touches, short builds or surges "
        "that enrich the session; they are not welcome as its bulk. A "
        "ladder that climbs out of the requested zone is a different "
        "session: a Tempo day whose last blocks are sweet spot is a sweet "
        "spot day, and the engine will send it back. Freedom is for "
        "serving the purpose, not for changing it.\n\n"
        "Criteria, not rules:\n"
        "- Variety must serve the purpose of the day. Do not add a touch, a "
        "surge or a cadence change just to be different, and do not "
        "avoid one just to be safe. The harder the session, the more a "
        "touch has to earn its place, because it competes with the quality "
        "of the key work.\n"
        "- A steady session is right when you have a reason (a recovery "
        "day, activation before a key effort, a ride whose steadiness is "
        "the point). Give the reason in the summary.\n"
        "- Cadence is one tool among several, never the only change.\n"
        "- Use the recent-history context to avoid handing back an "
        "effectively identical session and to progress naturally, but "
        "honor every parameter the user fixed.\n"
        "- You may place one level of sub-repeat inside a repeat block "
        "(for example 4 x [5 x (30s on / 30s off), 4 min easy]). The "
        "platform has no nested repeats, so the engine unrolls the inner "
        "one; nothing deeper is possible.\n\n"
        "WARMUP AND COOLDOWN are designed for each session, never a "
        "template, and every element has a reason. Keep them brief in short "
        "sessions (about 5 min warmup, 2-3 min cooldown) so the time goes "
        "to the work, and lengthen them as duration and intensity grow.\n"
        "- The WARMUP proper is ONE build from easy to ready. It starts "
        "easy (never below 45% FTP or 60% LTHR), rises smoothly toward the "
        "intensity where the first work step begins, and never peaks and "
        "falls back before the end. Short openers or cadence spin-ups may "
        "sit inside the build.\n"
        "- After the build comes the PREPARATION: a short interval (30 s to "
        "2 min, flagged is_preparation=true, always the last element of the "
        "warmup, never the whole warmup) at VERY LOW intensity, around 50% "
        "FTP (or 60-70% LTHR). It is a pause: the athlete drinks, adjusts "
        "the bike and breathes before the main set. It is not a harder "
        "opener.\n"
        "- The cooldown only descends: it starts around 60-65% FTP (or "
        "about 75-80% LTHR) and eases down to about 50% in one smooth "
        "descent, never below 45% FTP or 60% LTHR, and never climbing "
        "again.\n"
        "- Power mode may use ramps; in HR mode use steps only (heart rate "
        "lags a changing target), make the warmup climb, and prefer longer "
        "blocks in the main set. Say why in warmup_cooldown_rationale.\n\n"
        "What the engine checks (and will send back to you with the exact "
        "reason): zone names belong to the chosen system and the power and "
        "HR systems are never mixed; numbers are believable; a step "
        "called recovery is easy; the session fits the time available and "
        "the durations the user fixed are met exactly; the requested zone "
        "carries at least 70% of the work; the warmup starts easy, builds "
        "toward the level of the first work step and closes with a very easy "
        "preparation pause; the cooldown only descends and ends easy. "
        "Everything else is yours.\n\n"
        "Do NOT compute TSS/IF and do NOT write intervals.icu syntax: return "
        "structural intent only, matching the required JSON schema; the "
        "engine renders and does the math."
    )


def build_user_prompt(*, mode: str, zone: str,
                      target_duration_seconds: Optional[int],
                      target_tss: Optional[float],
                      target_if: Optional[float],
                      recent: list[CatalogEntry],
                      rejection_feedback: Optional[str] = None,
                      warmup_seconds: Optional[int] = None,
                      cooldown_seconds: Optional[int] = None) -> str:
    lines = [
        f"Mode: {mode}",
        f"Requested zone (the purpose of the session): {zone}",
    ]
    if target_duration_seconds:
        lines.append(f"Target total duration: {target_duration_seconds//60} min")
    if target_tss is not None:
        lines.append(f"Target TSS: {target_tss:g}")
    if target_if is not None:
        lines.append(f"Target IF: {target_if:g}")
    if target_tss is not None or target_if is not None:
        lines.append("A TSS/IF target was given: focus on the STRUCTURE "
                     "(reps, durations, recoveries, pattern) with plausible "
                     "in-zone intensities; the engine will deterministically "
                     "resolve the exact dominant work intensity to hit the "
                     "target. Your proposed work percentages set the range "
                     "width and the internal ratios between work steps, not "
                     "the final absolute level.")
    lines += _fixed_sections_lines(warmup_seconds, cooldown_seconds)
    if mode == "hr":
        lines.append("HR mode: write the warmup as climbing steps (no ramps), "
                     "and the cooldown as steps. Heart rate lags a changing "
                     "target: favor longer blocks.")
    block = shapes.prompt_block(mode, zone)
    if block:
        lines += ["", block]
    if recent:
        lines.append("\nRecent sessions you have generated (context — reason "
                     "over these to add variety / progress naturally; do not "
                     "mechanically avoid, reason):")
        for e in recent[:10]:
            lines.append(f"  - {e.generated_at[:10]} {e.mode}/{e.dominant_zone}: "
                         f"{e.summary}")
    if rejection_feedback:
        lines.append(
            "\nIMPORTANT — your previous proposal was REJECTED by the "
            "engine's validation for this exact reason:\n"
            f"  {rejection_feedback}\n"
            "Produce a corrected proposal that fixes this specific issue. "
            "Every parameter the user fixed still applies unchanged."
        )
    lines.append("\nReturn your structural design (warmup, main set, cooldown) "
                 "strictly matching the JSON schema.")
    return "\n".join(lines)


def _fixed_sections_lines(warmup_seconds: Optional[int],
                          cooldown_seconds: Optional[int]) -> list[str]:
    """The user's own warmup / cooldown lengths, which must be met exactly."""
    out = []
    if warmup_seconds:
        out.append(f"The user fixed the WARMUP at exactly {warmup_seconds // 60} "
                   f"min ({warmup_seconds}s): its elements must add up to that.")
    if cooldown_seconds:
        out.append(f"The user fixed the COOLDOWN at exactly "
                   f"{cooldown_seconds // 60} min ({cooldown_seconds}s): its "
                   f"elements must add up to that.")
    return out


_RESEARCH_INSTRUCTION = (
    "\n\nBefore anything else: research live, via search, a range of real "
    "structural approaches, session patterns, and methodological perspectives "
    "relevant to this exact request (this zone, this mode, this duration). "
    "The goal is variety and creative grounding — surface options a default "
    "generation would tend to overlook, not just the most obvious textbook "
    "session. Return ONLY free-form prose research notes. Do NOT propose a "
    "final structure yet and do NOT write JSON — that happens in a separate "
    "step."
)


def gemini_transport(api_key: Optional[str] = None) -> Transport:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def _research_notes(system_prompt: str, user_prompt: str) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            thinking_config=thinking_config(THINKING_RESEARCH),
        )
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt + _RESEARCH_INSTRUCTION,
            config=config,
        )
        return (response.text or "").strip()

    def _transport(system_prompt: str, user_prompt: str,
                   tools: list, web_search: bool) -> dict:

        tool = tools[0]
        target_schema = tool.get("input_schema", {})
        # A2 fix: the tool's own top-level `description` (e.g. the bilingual
        # zone-mapping table in PARSE_TOOL_SCHEMA, or the dominant/subordinate
        # rule in PROPOSAL_TOOL_SCHEMA) was previously dropped — only
        # input_schema was ever forwarded to Gemini. Fold it into the system
        # instruction so the model actually sees it.
        tool_description = tool.get("description", "")
        full_system = (f"{system_prompt}\n\n{tool_description}"
                       if tool_description else system_prompt)

        final_user_prompt = user_prompt
        if web_search:
            notes = _research_notes(full_system, user_prompt)
            if notes:
                final_user_prompt = (
                    f"{user_prompt}\n\nResearch notes from your own live "
                    f"search (use these to inform variety and methodology — "
                    f"every hard rule and every parameter fixed above still "
                    f"applies unchanged):\n{notes}"
                )

        config = types.GenerateContentConfig(
            system_instruction=full_system,
            response_mime_type="application/json",
            response_schema=target_schema,
            thinking_config=thinking_config(THINKING_STRUCTURE),
        )

        response = client.models.generate_content(
            model=MODEL,
            contents=final_user_prompt,
            config=config,
        )

        return parse_json_text(response.text)

    return _transport


def request_proposal(*, transport: Transport, mode: str, zone: str,
                     target_duration_seconds: Optional[int] = None,
                     target_tss: Optional[float] = None,
                     target_if: Optional[float] = None,
                     recent: Optional[list[CatalogEntry]] = None,
                     use_web_search: bool = False,
                     rejection_feedback: Optional[str] = None,
                     warmup_seconds: Optional[int] = None,
                     cooldown_seconds: Optional[int] = None) -> dict:

    system = build_system_prompt()
    user = build_user_prompt(
        mode=mode, zone=zone,
        target_duration_seconds=target_duration_seconds,
        target_tss=target_tss, target_if=target_if,
        recent=recent or [],
        rejection_feedback=rejection_feedback,
        warmup_seconds=warmup_seconds, cooldown_seconds=cooldown_seconds,
    )
    return transport(system, user, [PROPOSAL_TOOL_SCHEMA], use_web_search)


def request_progression(*, transport: Transport, mode: str, zone: str,
                        initial_session_seconds: Optional[int] = None,
                        max_session_seconds: Optional[int] = None,
                        recent: Optional[list[CatalogEntry]] = None,
                        use_web_search: bool = False,
                        rejection_feedback: Optional[str] = None,
                        warmup_seconds: Optional[int] = None,
                        cooldown_seconds: Optional[int] = None) -> dict:

    from .progression import PROGRESSION_TOOL_SCHEMA

    system = build_system_prompt()
    lines = [
        f"Mode: {mode}",
        f"Requested progression; the purpose of every session is: {zone}",
        "",
        "Design a progression: an ordered sequence of sessions that forms a "
        "COHERENT sequence WITH DIRECTION — each session a sensible step toward "
        "the progression's endpoint, never random disconnected sessions. That "
        "coherent direction is the only fixed requirement. HOW it progresses "
        "(volume, density, structure, recovery, etc.) is yours to reason from "
        "physiology and methodology — investigate live as needed. Do not follow "
        "any single author's recipe; reason your own appropriate progression.",
    ]
    if initial_session_seconds:
        lines.append(
            f"\nDay 1 session budget: {initial_session_seconds//60} min TOTAL "
            f"(including warmup/cooldown). Size warmup/cooldown to the budget — "
            f"do not waste time on a long warmup in a short session.")
    if max_session_seconds:
        lines.append(
            f"Maximum session duration: {max_session_seconds//60} min. Develop "
            f"the ideal load between the starting budget and this maximum.")
    else:
        lines.append(
            "No maximum was given. Grow the progression up to the PHYSIOLOGICAL "
            "CEILING of this stimulus, which you should determine by live "
            "research (e.g. how many minutes in-zone it makes sense to progress "
            "to). When the ceiling is reached, add a graduation_note for the "
            "next stimulus.")
    fixed = _fixed_sections_lines(warmup_seconds, cooldown_seconds)
    if fixed:
        lines.append("In EVERY session of the progression:")
        lines += fixed
    block = shapes.prompt_block(mode, zone)
    if block:
        lines += ["", block]
    if mode == "hr":
        lines.append("HR mode: each session's warmup is climbing steps (no "
                     "ramps), and its cooldown is steps.")
    if recent:
        lines.append("\nYour own catalog of recent sessions (your memory/"
                     "library — reuse/adapt your prior reasoning, don't reinvent "
                     "the wheel; this is your own work, not an external recipe):")
        for e in recent[:10]:
            lines.append(f"  - {e.dominant_zone}: {e.summary}")
    if rejection_feedback:
        lines.append(
            "\nIMPORTANT — your previous progression was REJECTED by the "
            "engine's validation for this exact reason:\n"
            f"  {rejection_feedback}\n"
            "Produce a corrected progression that fixes this specific issue. "
            "Every parameter the user fixed still applies unchanged."
        )
    lines.append("\nReturn your reasoned progression matching the required JSON schema.")
    user = "\n".join(lines)
    return transport(system, user, [PROGRESSION_TOOL_SCHEMA], use_web_search)
