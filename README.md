# cycling-workout-engine-gemini

An intelligent, local Python engine that generates indoor cycling workouts —
single sessions and multi-session progressions — as ready-to-import
[intervals.icu](https://intervals.icu) workout files (`.md`).

**Version:** 0.4.1
**Status:** Core engine functional — no web/app frontend yet (CLI only)
**License:** Private / All rights reserved (no open-source license applied)

This is an independent fork of the original Claude-based
`cycling-workout-engine`, migrated to Google's Gemini API (`google-genai`
SDK). It is standalone: no shared code, no shared runtime dependency on the
original repo. See `CHANGELOG.md` for the full migration history and audit.

Unlike template-based workout generators, this engine has **no fixed menu of
prescribed sessions**. It reasons from exercise physiology and methodology
(via a Gemini-powered reasoning layer with live web search), grounded and
validated by a deterministic mechanical core that owns all math, syntax
rendering, and rule enforcement. The result: creative, varied, physiologically
sound workouts — never copy-pasted from a lookup table, never mechanically
repetitive.

Request a workout in plain language:

```bash
python pedir.py "resistencia aerobica de 1 hora"
python pedir.py "una progresion de tempo empezando en 30 minutos"
python pedir.py "vo2 max 45 min por frecuencia cardiaca"
```

Works in **Spanish or English** — the language is auto-detected from your
request. See [`QUICKSTART.md`](QUICKSTART.md) for a fast, practical usage
guide with copy-paste examples in both languages.

## Why this exists

Most workout generators either (a) pick from a static library of named
sessions ("4x8min VO2max intervals") or (b) apply a fixed formula. Both get
repetitive fast and can't reason about *why* a structure fits a specific
athlete, time budget, or point in a progression. This project inverts that:
the creative decisions (structure, intensity distribution, progression shape,
complementary stimuli) are reasoned live by an LLM constrained by a strict,
tested, deterministic validator — so the output is simultaneously **creative**
and **physiologically/mechanically correct**.

## Core design principles

- **The engine reasons; it never picks from a menu.** No hardcoded "recipe"
  tables. No pre-loaded knowledge base of any kind — reasoning is free
  reasoning + live web search only (a static KB was deliberately rejected: it
  degrades into a disguised template and makes the engine lazy).
- **The engine obeys; it is not a coach.** It generates what's asked and never
  decides *when/whether* training should happen — that's a separate human/coach
  decision, out of scope.
- **Gemini proposes, Python validates.** The reasoning layer (Gemini API +
  `response_schema` structured output + live web search) proposes workout
  *structure*. The deterministic core validates every proposal against hard
  rules (zone bounds, no cross-mode mixing, no nested repeats,
  dominant-stimulus rule, time-budget conservation, TSS-target verification,
  HR-staircase content sanity) before accepting it. A rejected proposal is
  discarded and re-requested — never silently "fixed," never accepted blind.
- **Web search is for variety, not fact-grounding.** The engine already knows
  exercise physiology; live search exists to surface structural approaches
  and methodological perspectives a default generation would tend to
  overlook, widening creativity and effectiveness rather than fetching facts
  the model lacks. See "Gemini web search architecture" below.
- **Power and heart-rate zones are independent systems**, never
  cross-correlated, even though some zone names overlap between them
  (Friel preset zones).
- **Output is always percentage-based** (`%FTP` for power, `%LTHR` for heart
  rate) in literal, validated [intervals.icu syntax](https://intervals.icu) —
  never absolute watts/bpm, never narrative prose.
- **Time budget is arithmetic, not creative.** Whether a full session (warmup +
  prep + main set + cooldown) fits the athlete's stated time budget is
  enforced by exact math. *How* that budget is spent (warmup length, main-set
  structure, intensity) is the engine's reasoned creativity.

## Gemini web search architecture (two-call pattern)

Every generation runs two calls:

1. **Research call** — `google_search` enabled, no schema, free-form prose
   output: real structural approaches and methodological perspectives
   relevant to the exact request.
2. **Structure call** — `response_schema` enabled, no tools: the research
   notes are folded into the prompt as context, and the model returns the
   JSON proposal that Python validates.

When this fork was created, Gemini rejected structured output and Google
Search in the same request (`400 INVALID_ARGUMENT`). Gemini 3 models now
allow the combination. The engine keeps the two calls because they work on
any model and are proven; merging them into one call is a possible future
saving, to be done only after testing it against the live API.

## Model configuration

All model settings live in `engine/llm_config.py`.

| Setting | Default | Override (environment variable) |
| --- | --- | --- |
| Model | `gemini-3.8-flash` | `WORKOUT_ENGINE_MODEL` |
| Thinking, research call | `medium` | `WORKOUT_ENGINE_THINKING_RESEARCH` |
| Thinking, structure call | `high` | `WORKOUT_ENGINE_THINKING_STRUCTURE` |
| Thinking, request parser | `low` | `WORKOUT_ENGINE_THINKING_PARSER` |

- `gemini-3.8-flash` is the newest model on the Gemini API (stable,
  September 2026). The Pro tier is still `gemini-3.1-pro-preview`, an older
  preview model; set it through `WORKOUT_ENGINE_MODEL` to compare.
- **No temperature is ever set.** Google documents that Gemini 3 models can
  loop or degrade when the temperature is set below its default of 1.0. A
  test fails if any module sets one.
- Google retires models quickly (1.0, 1.5 and the 2.0 Flash line are gone).
  Before trusting a model id, check
  https://ai.google.dev/gemini-api/docs/deprecations.

## Requirements

- Python 3.10+ (tested on 3.14)
- [`google-genai`](https://pypi.org/project/google-genai/) Python SDK, 2.29 or newer
- A Gemini API key (`GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable)
  from [Google AI Studio](https://aistudio.google.com)
- `pytest`, `jsonschema` (dev/testing only)

```bash
pip install -r requirements.txt
```

## Quick start

```bash
# From the repository root (the folder that contains pedir.py)

# Run the test suite (no API key needed — uses a mock transport)
python -m pytest -q

# Generate a workout in plain language (requires GEMINI_API_KEY)
python pedir.py "tempo de 50 minutos"

# Or use the deterministic offline core (no API calls, simpler output)
python -m engine.cli --mode power --zone Tempo --duration 50
```

See [`docs/SETUP.md`](docs/SETUP.md) for a complete, no-assumptions setup
walkthrough (API key creation, environment variables, Windows-specific steps).

## Architecture

```
Natural-language request ("tempo de 50 minutos")
        │
        ▼
  request_parser.py    ── Gemini interprets plain language into structured
        │                  parameters (zone, mode, duration, TSS/IF, kind)
        ▼
  generator_v2.py /
  generate_progression.py
        │
        ├──► gemini_client.py  ── Gemini proposes workout STRUCTURE
        │                          (response_schema; two-call research +
        │                          structure pattern when web search is on)
        │
        ├──► proposal.py       ── validates every proposal against hard rules:
        │                          zone bounds, no cross-mode mixing, no
        │                          nested repeats, dominant-stimulus rule,
        │                          time-budget conservation, TSS-target check,
        │                          HR-staircase content sanity
        │                          (rejects & retries on any violation)
        │
        ├──► structure.py      ── mandatory session structure (warmup/prep/
        │                          cooldown; ramps for power, staircases for HR)
        │
        ├──► tss.py            ── TSS/IF/NP algebra, feasibility detection
        │
        ├──► render.py         ── compiles to literal intervals.icu syntax +
        │                          output-validation gate
        │
        ├──► assembler.py      ── assembles the final .md, computes real TSS
        │
        └──► catalog.py        ── SQLite memory + reusable library (the
                                   engine's own history, consulted when
                                   reasoning — never an external knowledge base)
```

Full technical specification: [`cycling_workout_generator_specification.md`](cycling_workout_generator_specification.md).
JSON Schema for requests/sessions: [`workout_engine_schema.json`](workout_engine_schema.json).
Project history and every locked design decision: [`CHANGELOG.md`](CHANGELOG.md).

## Project layout

```
cycling-workout-engine-gemini/
├── pedir.py                  # natural-language front-end command
├── engine/
│   ├── zones.py              # Friel power/HR zones (fixed data)
│   ├── rpe.py                # RPE derivation (Borg CR10)
│   ├── render.py             # intervals.icu syntax + output-validation gate
│   ├── tss.py                # TSS/IF/NP math, feasibility
│   ├── catalog.py            # SQLite memory + library
│   ├── models.py             # request/session dataclasses
│   ├── structure.py          # mandatory session structure
│   ├── assembler.py          # final .md assembly + real TSS
│   ├── proposal.py           # Gemini↔Python contract + hard-rule validator
│   ├── llm_config.py         # model, thinking levels, JSON parsing (one place)
│   ├── gemini_client.py      # Gemini API calls (response_schema + web search)
│   ├── build_from_proposal.py
│   ├── resolve_intensity.py  # deterministic work-intensity solver (power mode)
│   ├── progression.py        # multi-session progression contract
│   ├── generate_progression.py
│   ├── request_parser.py     # natural-language → structured parameters
│   ├── generator.py          # Phase-1 deterministic-only generator (offline)
│   ├── generator_v2.py       # Phase-2 single-session orchestration
│   └── cli.py                # command-line interface (--offline mode)
└── tests/
    ├── test_core.py          # deterministic-core tests (incl. hand-verified TSS)
    ├── test_phase2.py        # reasoning-layer integration tests via mock transport
    └── test_cleanup_v041.py  # HR staircase content, unknown fields, model settings
```

## Testing

```bash
python -m pytest -q
```

94 tests, all passing without any API key (a mock transport stands in for
the real Gemini API). GitHub Actions runs them on every push
(`.github/workflows/tests.yml`). Coverage includes hand-calculated TSS/IF
reference cases, RPE derivation, output-syntax validation, end-to-end
generation for both power and heart-rate modes, budget-conservation
enforcement, TSS-target verification, HR-staircase content validation,
unknown-field rejection, and the model settings.

## Status & roadmap

**What works today:**
- Single-session generation (power and heart-rate modes)
- Multi-session, time-budget-driven progressions with a physiologically
  reasoned (live-researched) ceiling
- Natural-language request parsing (no need to know internal zone names)
- Full validation pipeline: zone bounds, budget conservation, TSS-target
  verification, dominant/subordinate stimulus rule, HR-staircase content
  sanity, output-syntax gate

**Not yet built:**
- CP/W′ (Critical Power) calculator — designed in the spec, not yet coded
- Direct intervals.icu upload (currently produces a `.md` file to import manually)
- Any web or desktop UI — CLI only, by design, for this phase

See [`CHANGELOG.md`](CHANGELOG.md) for the complete decision history and
[`cycling_workout_generator_specification.md`](cycling_workout_generator_specification.md)
for the full spec.

## Design philosophy in one sentence

The engine should feel like working with a thoughtful coach who investigates
and reasons every session — never like filling in a spreadsheet template.
