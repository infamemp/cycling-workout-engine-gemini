"""
request_parser.py — Natural-language request interpretation.
Mapped to Gemini via google.genai
"""
from __future__ import annotations
import json
import os
from typing import Callable, Optional

PARSE_TOOL_SCHEMA = {
    "name": "parse_request",
    "description": (
        "Interpret a natural-language cycling-workout request — written in "
        "EITHER Spanish or English — into structured parameters. Map the "
        "user's plain wording, in whichever language they used, to the "
        "correct technical zone name in the correct system. The POWER system "
        "zones are: ActiveRecovery, Endurance, Tempo, SweetSpot, Threshold, "
        "VO2Max, Anaerobic, Neuromuscular. The HR system zones are: Recovery, "
        "Aerobic, Tempo, SubThreshold, SuperThreshold, AerobicCapacity, "
        "Anaerobic. Choose the system from how the user asks (power/watts/FTP "
        "-> power; heart rate/pulse/FC/LTHR/pulso -> hr). Default to power if "
        "unspecified. Never mix systems.\n"
        "Bilingual zone-wording examples (ES / EN):\n"
        "  - 'recuperacion activa' / 'active recovery' -> ActiveRecovery\n"
        "  - 'resistencia aerobica' / 'aerobic endurance', 'base' / 'base "
        "miles' -> Endurance (power) or Aerobic (hr)\n"
        "  - 'tempo' / 'tempo' -> Tempo (same name both systems)\n"
        "  - 'sweet spot', 'sweetspot' / 'sweet spot' -> SweetSpot\n"
        "  - 'umbral' / 'threshold' -> Threshold (power) or SubThreshold (hr)\n"
        "  - 'vo2 max', 'vo2max' / 'vo2 max' -> VO2Max (power) or "
        "SuperThreshold (hr)\n"
        "  - 'anaerobico' / 'anaerobic' -> Anaerobic (power) or "
        "AerobicCapacity (hr)\n"
        "  - 'neuromuscular', 'sprints' / 'neuromuscular', 'sprints' -> "
        "Neuromuscular (power) or Anaerobic (hr)"
    ),
    "input_schema": {
        "type": "object",
        "required": ["kind", "mode", "zone", "language"],
        "properties": {
            "kind": {"type": "string", "enum": ["single_session", "progression"]},
            "mode": {"type": "string", "enum": ["power", "hr"]},
            "zone": {"type": "string",
                     "description": "Technical zone name in the chosen system."},
            "language": {
                "type": "string", "enum": ["es", "en"],
                "description": "The language the user wrote their request in "
                               "(Spanish or English), detected from the text.",
            },
            "duration_minutes": {"type": "integer",
                                 "description": "Session duration if given "
                                 "(single session), or Day-1 duration "
                                 "(progression)."},
            "max_duration_minutes": {"type": "integer",
                                     "description": "Max session duration if "
                                     "the user gave an upper bound."},
            "target_tss": {"type": "number"},
            "target_if": {"type": "number"},
            "interpretation_note": {
                "type": "string",
                "description": "One short line restating what you understood, "
                               "for confirmation. MUST be written in the SAME "
                               "language as the user's request.",
            },
        },
    },
}

# Same model/override policy as gemini_client.py — see that module's comment
# for the note on checking Google's deprecation page before relying on any
# hardcoded model string.
MODEL = os.getenv("WORKOUT_ENGINE_MODEL", "gemini-3.1-pro-preview")

def parse_request(*, transport: Callable, text: str) -> dict:
    system = (
        "You interpret natural-language indoor cycling workout requests — "
        "written in Spanish OR English — into structured parameters via the "
        "parse_request tool. Detect and report which language was used. Be "
        "faithful to what the user asked; do not invent constraints they "
        "didn't state. If they didn't specify power vs heart rate, default to "
        "power. Map plain wording, in whichever language, to the correct "
        "technical zone name in the correct system. Write interpretation_note "
        "in the same language the user wrote in."
    )
    user = f"Interpret this request:\n\n{text}\n\nReturn the structured parameters strictly matching the JSON schema."
    return transport(system, user, [PARSE_TOOL_SCHEMA], False)

def parse_transport_from_gemini(api_key: Optional[str] = None) -> Callable:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def _t(system_prompt: str, user_prompt: str, tools: list, web: bool) -> dict:
        tool = tools[0]
        target_schema = tool.get("input_schema", {})
        # A2 fix: PARSE_TOOL_SCHEMA's top-level `description` carries the
        # entire bilingual zone-name mapping table (the ES/EN examples for
        # every zone). Previously only input_schema was forwarded to Gemini,
        # so that table never reached the model at all. Fold it into the
        # system instruction so zone interpretation actually uses it.
        tool_description = tool.get("description", "")
        full_system = (f"{system_prompt}\n\n{tool_description}"
                       if tool_description else system_prompt)

        config = types.GenerateContentConfig(
            system_instruction=full_system,
            response_mime_type="application/json",
            response_schema=target_schema,
            temperature=0.0,
        )
        
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt,
            config=config,
        )
        
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()
            
        return json.loads(raw_text)

    return _t