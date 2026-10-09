"""
llm_config.py — The one place that says which Gemini model the engine uses
and how it is called. Every module that talks to Gemini (gemini_client.py,
request_parser.py) reads its settings from here, so a model change is a
one-line edit (or an environment variable), never a hunt through the code.

Model choice (checked 2026-10-08 against
https://ai.google.dev/gemini-api/docs/models):
  - gemini-3.8-flash is the newest model on the API (stable, Sept 2026)
    and Google's most capable Flash model. It supports structured output,
    Google Search grounding and thinking levels low / medium / high.
  - The Pro tier is still gemini-3.1-pro-preview (older, preview status).
  The default is gemini-3.8-flash: newest, stable (not preview), and run
  with thinking_level "high" for the reasoning calls. Set
  WORKOUT_ENGINE_MODEL to try another model without touching the code.

Temperature: Gemini 3 models are documented to loop or degrade when the
temperature is set below its default of 1.0 ("we strongly recommend keeping
the temperature parameter at its default value of 1.0",
https://ai.google.dev/gemini-api/docs/gemini-3). The engine therefore never
sets a temperature. Variety comes from the research call and the catalog,
determinism from the Python core that validates every answer.

Google retires models quickly. Before trusting any model id here, check
https://ai.google.dev/gemini-api/docs/deprecations.
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.getenv("WORKOUT_ENGINE_MODEL", DEFAULT_MODEL)

# Thinking level per call. gemini-3.8-flash accepts "low", "medium", "high"
# ("minimal" returns an error on this model).
THINKING_RESEARCH = os.getenv("WORKOUT_ENGINE_THINKING_RESEARCH", "medium")
THINKING_STRUCTURE = os.getenv("WORKOUT_ENGINE_THINKING_STRUCTURE", "high")
THINKING_PARSER = os.getenv("WORKOUT_ENGINE_THINKING_PARSER", "low")


def thinking_config(level: str):
    """Build the SDK's ThinkingConfig for a level name. Imported lazily so
    the module loads (and the tests run) without google-genai installed."""
    from google.genai import types
    return types.ThinkingConfig(thinking_level=level.upper())


def parse_json_text(text: str | None) -> dict:
    """Parse a model's JSON answer. Structured output normally returns bare
    JSON; a fenced ```json block is tolerated in case a model wraps it."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
        raw = raw.strip()
    if not raw:
        raise RuntimeError("the model returned an empty answer")
    return json.loads(raw)
