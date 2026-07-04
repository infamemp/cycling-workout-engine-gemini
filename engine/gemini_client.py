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
import json
import os
from typing import Callable, Optional

from .proposal import PROPOSAL_TOOL_SCHEMA
from .catalog import CatalogEntry

Transport = Callable[[str, str, list, bool], dict]

# Both the research call and the structure call use the same model (chosen
# 2026-07: gemini-3.1-pro-preview — flagship reasoning tier, no announced
# shutdown date at time of writing). NOTE: despite the "3.1 Pro" marketing
# name, the Developer API's generateContent still exposes it under the
# "-preview" model ID — this is Google's current naming, not a typo. Preview
# models can change or have tighter rate limits than GA ones; if that
# matters for your usage, re-check https://ai.google.dev/gemini-api/docs/models
# for a GA equivalent before relying on this in unattended/production use.
# Also check https://ai.google.dev/gemini-api/docs/deprecations before
# assuming any hardcoded model string still works — Google's retirement
# cadence has been fast (whole 1.0/1.5 generations and the 2.0 Flash line
# are already gone as of mid-2026).
MODEL = os.getenv("WORKOUT_ENGINE_MODEL", "gemini-3.1-pro-preview")


def build_system_prompt() -> str:
    return (
        "You are the reasoning core of an indoor cycling workout generator. "
        "You design the STRUCTURE of one workout's main set (and, in HR mode, "
        "the warmup staircase). You are an expert who reasons from exercise "
        "physiology and methodology — never from a fixed menu. Your decisions "
        "must respect these hard rules:\n"
        "- The requested zone is the DOMINANT stimulus (most work time-in-zone). "
        "Any complementary stimuli are SUBORDINATE and must not displace it.\n"
        "- All intensities are integer percent ranges that sit within their "
        "named zone's bounds. Never mix the power and HR zone systems.\n"
        "- Repeat blocks are never nested.\n"
        "- Do NOT compute TSS/IF and do NOT write intervals.icu syntax — return "
        "structural intent only matching the required JSON schema; the engine renders "
        "and does the math.\n"
        "- Vary structure to avoid monotony, but honor every parameter the user "
        "fixed. Use the provided recent-history context to avoid handing back an "
        "effectively identical session, and to progress naturally when relevant."
    )


def build_user_prompt(*, mode: str, zone: str,
                      target_duration_seconds: Optional[int],
                      target_tss: Optional[float],
                      target_if: Optional[float],
                      recent: list[CatalogEntry],
                      rejection_feedback: Optional[str] = None) -> str:
    lines = [
        f"Mode: {mode}",
        f"Requested dominant zone: {zone}",
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
    if mode == "hr":
        lines.append("HR mode: warmup must be ASCENDING STEPS (a staircase), "
                     "not a ramp. Provide hr_warmup_staircase as ascending "
                     "[low%,high%,seconds] steps totaling <=10 min.")
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
    lines.append("\nReturn your structural design for the main set strictly matching the JSON schema.")
    return "\n".join(lines)


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
            temperature=0.5,
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
            temperature=0.4,
        )

        response = client.models.generate_content(
            model=MODEL,
            contents=final_user_prompt,
            config=config,
        )

        raw_text = (response.text or "").strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()

        return json.loads(raw_text)

    return _transport


def request_proposal(*, transport: Transport, mode: str, zone: str,
                     target_duration_seconds: Optional[int] = None,
                     target_tss: Optional[float] = None,
                     target_if: Optional[float] = None,
                     recent: Optional[list[CatalogEntry]] = None,
                     use_web_search: bool = False,
                     rejection_feedback: Optional[str] = None) -> dict:

    system = build_system_prompt()
    user = build_user_prompt(
        mode=mode, zone=zone,
        target_duration_seconds=target_duration_seconds,
        target_tss=target_tss, target_if=target_if,
        recent=recent or [],
        rejection_feedback=rejection_feedback,
    )
    return transport(system, user, [PROPOSAL_TOOL_SCHEMA], use_web_search)


def request_progression(*, transport: Transport, mode: str, zone: str,
                        initial_session_seconds: Optional[int] = None,
                        max_session_seconds: Optional[int] = None,
                        recent: Optional[list[CatalogEntry]] = None,
                        use_web_search: bool = False,
                        rejection_feedback: Optional[str] = None) -> dict:

    from .progression import PROGRESSION_TOOL_SCHEMA

    system = build_system_prompt()
    lines = [
        f"Mode: {mode}",
        f"Requested progression for dominant stimulus: {zone}",
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
    if mode == "hr":
        lines.append("HR mode: each session's warmup is an ascending STAIRCASE "
                     "(hr_warmup_staircase), never a ramp.")
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
