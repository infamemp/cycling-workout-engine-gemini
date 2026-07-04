"""
test_hr_staircase_schema.py — standalone, throwaway script.

Purpose: confirm whether Gemini's response_schema accepts an array-of-arrays
shape (each inner array a fixed [low_pct, high_pct, seconds] triple) the way
PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"]["hr_warmup_staircase"]
defines it, or whether it needs to be flattened to an array of objects.

Run locally (needs your Gemini API key as GEMINI_API_KEY or GOOGLE_API_KEY
env var — do NOT paste the key into this file):

    pip install google-genai
    python test_hr_staircase_schema.py

Reads nothing from the real project — fully self-contained.
"""
from google import genai
from google.genai import types

# Exact shape used today in proposal.py's PROPOSAL_TOOL_SCHEMA.
SCHEMA = {
    "type": "object",
    "required": ["hr_warmup_staircase"],
    "properties": {
        "hr_warmup_staircase": {
            "type": "array",
            "description": "Ascending steps; each [low%, high%, seconds].",
            "items": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "integer"},
            },
        },
    },
}

MODEL = "gemini-3.1-pro-preview"


def main() -> None:
    client = genai.Client()
    config = types.GenerateContentConfig(
        system_instruction=(
            "Return a 3-step ascending HR warmup staircase for a 10-minute "
            "warmup, matching the schema exactly."
        ),
        response_mime_type="application/json",
        response_schema=SCHEMA,
        temperature=0.0,
    )
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents="Design the staircase.",
            config=config,
        )
        print("RAW RESPONSE TEXT:")
        print(response.text)
        print("\nRESULT: the array-of-arrays schema was ACCEPTED as-is.")
    except Exception as e:
        print("RESULT: the schema was REJECTED.")
        print(f"Error: {e}")
        print(
            "\nIf this is a 400 INVALID_ARGUMENT mentioning the schema, "
            "hr_warmup_staircase needs to be flattened to an array of "
            "objects, e.g.:\n"
            '  {"type": "array", "items": {"type": "object", '
            '"required": ["low_pct","high_pct","seconds"], "properties": '
            '{"low_pct": {"type":"integer"}, "high_pct": {"type":"integer"}, '
            '"seconds": {"type":"integer"}}}}'
        )


if __name__ == "__main__":
    main()
