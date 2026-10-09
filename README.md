# cycling-workout-engine-gemini

An intelligent, local Python engine that generates indoor cycling workouts —
single sessions and multi-session progressions — as ready-to-import
[intervals.icu](https://intervals.icu) workout files (`.md`).

**Version:** 0.10.0
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
python pedir.py "tempo de 45 minutos nivel basico"
```

Works in **Spanish or English** — the language is auto-detected from your
request. See [`docs/QUICKSTART.md`](docs/QUICKSTART.md) for a fast, practical usage
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
  *structure*. The deterministic core validates every proposal before
  accepting it. It blocks errors, not designs: no cross-mode mixing,
  believable numbers, easy "recovery", the requested zone present,
  time-budget conservation, TSS-target verification, warmup (with its
  preparation interval) and cooldown sanity. Design choices (a step that
  reaches past its zone, complementary work outweighing the requested zone)
  are reported as notes and never rejected. A rejected proposal is
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
  main set + cooldown) fits the athlete's stated time budget is
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

## Warmup and cooldown

Designed for each session, never a template: brief (~5 min warmup, 2–3 min
cooldown) in short sessions, longer as duration and intensity grow, with
short openers before hard work when they help. Ask for a length in your
request ("con calentamiento de 15 minutos") and the engine uses exactly that.
Heart-rate sessions warm up in climbing steps (heart rate lags a ramp).

The warmup is one build that arrives at the level where the first work step
begins, then closes with a short preparation (30 s to 2 min) at very low
intensity: a pause to drink and adjust before the main set. The cooldown only
descends. Nothing is written below 45% FTP / 60% LTHR.

## Freedom with a purpose

Gemini may arrange the work freely (ladders, builds, surges, over-unders),
but the requested zone must carry at least 70% of the work, judged by the
midpoint of each step. A Tempo session whose last blocks are sweet spot is
sent back. Smaller touches of other zones are allowed and shown as design
notes.

## Rider level

Add a level to the request ("nivel básico", "para principiante",
"intermediate", "advanced") and Gemini cuts the same work differently: shorter
blocks with easy recoveries for a beginner, long continuous blocks for an
advanced rider. The zone, the amount of work and its intensity do not change,
and the engine checks nothing about the level: it is a design criterion, not a
rule. Without a level the session is designed as before.

## Training load (TSS)

The engine reports the load of every session the way Intervals.icu computes
planned workouts, so the number you see is the one your calendar will show:

- **Power:** Normalized Power with the 30-second rolling average (ramps
  followed second by second), `TSS = hours × IF² × 100`. Checked against 85
  real planned workouts in Intervals.icu: 0.5 TSS off on average, 1.4 at
  most.
- **Heart rate:** HRSS (normalised TRIMP), the method the Intervals.icu
  workout builder uses for HR workouts. It needs your LTHR, max HR and
  resting HR (see below); without them the load is shown as approximate.

When you ask for a TSS or IF, the engine fixes the session's structure first
and then solves the one work intensity that lands it (spec Section 16).

## Your thresholds (`athlete.yaml`)

Copy `athlete.example.yaml` to `athlete.yaml` (git-ignored) and fill in your
values — the same ones as in your Intervals.icu settings. Every field is
optional. The workouts stay in % of threshold; the numbers are used only
inside the engine (today: the HR-mode load).

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
        ├──► proposal.py       ── validates every proposal: errors reject
        │                          and retry (cross-mode mixing, impossible
        │                          numbers, requested zone absent, time
        │                          budget, TSS-target check, warmup /
        │                          cooldown sanity in sections.py); design
        │                          choices come back as notes. One level of
        │                          sub-repeat is unrolled into its block.
        │
        ├──► sections.py       ── warmup and cooldown, designed per session;
        │                          a requested length adopted exactly
        │
        ├──► tss.py            ── NP (30 s rolling) / HRSS load, as Intervals.icu
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

Full technical specification: [`docs/specification.md`](docs/specification.md).
JSON Schema for requests/sessions: [`docs/workout_engine_schema.json`](docs/workout_engine_schema.json).
Project history and every locked design decision: [`CHANGELOG.md`](CHANGELOG.md).

## Project layout

```
cycling-workout-engine-gemini/
├── pedir.py                  # natural-language front-end command
├── README.md  CHANGELOG.md  VERSION  requirements.txt
├── athlete.example.yaml      # copy to athlete.yaml (git-ignored) for your thresholds
├── docs/
│   ├── QUICKSTART.md         # fast, practical usage (ES + EN)
│   ├── SETUP.md              # no-assumptions install guide
│   ├── specification.md      # the full technical specification
│   └── workout_engine_schema.json
├── workouts/                 # everything generated, filed by intention
│   ├── README.md             # (the only tracked file in here)
│   └── tempo/ endurance/ threshold/ ...   # created on first use
├── engine/
│   ├── zones.py              # Friel power/HR zones (fixed data)
│   ├── rpe.py                # RPE derivation (Borg CR10)
│   ├── render.py             # intervals.icu syntax + output-validation gate
│   ├── tss.py                # NP (30 s rolling), HRSS, TSS algebra, solver
│   ├── athlete_settings.py   # reads athlete.yaml (your thresholds)
│   ├── storage.py            # where workouts and the catalog are saved
│   ├── intervals_upload.py   # ready, unused: dry-run-first upload to Intervals.icu
│   ├── sections.py           # warmup / cooldown: schema, checks, building
│   ├── shapes.py             # session-shape library loader (ideas for the prompt)
│   ├── data/shapes.yaml      # 20 shapes + ways they chain; no intensities
│   ├── catalog.py            # SQLite memory + library
│   ├── models.py             # request/session dataclasses
│   ├── structure.py          # conflict detection, offline placeholder main set
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
    ├── test_cleanup_v041.py  # HR staircase content, unknown fields, model settings
    ├── test_load_v050.py     # load methods, athlete.yaml
    ├── test_sections_v060.py # designed warmup/cooldown, offline durations
    ├── test_flex_v070.py     # flexibility: every kind of session, shape library
    └── test_storage_v080.py  # workouts filed by intention, tidy repo root
```

## Testing

```bash
python -m pytest -q
```

232 tests, all passing without any API key (a mock transport stands in for
the real Gemini API). GitHub Actions runs them on every push
(`.github/workflows/tests.yml`). Coverage includes hand-calculated TSS/IF
reference cases (NP with the rolling window, HRSS), RPE derivation, output-syntax validation, end-to-end
generation for both power and heart-rate modes, budget-conservation
enforcement, TSS-target verification, warmup/cooldown checks,
unknown-field rejection, the model settings, and every kind of session
(recovery, activation, aerobic with touches, tempo builds, sweet spot with
surges, over-unders, VO2max micro-intervals, anaerobic, heart-rate sessions).

## Status & roadmap

**What works today:**
- Single-session generation (power and heart-rate modes)
- Multi-session, time-budget-driven progressions with a physiologically
  reasoned (live-researched) ceiling
- Natural-language request parsing (no need to know internal zone names)
- Full validation pipeline: zone bounds, budget conservation, TSS-target
  verification, requested-zone-present rule, warmup (with preparation
  interval) and cooldown sanity, output-syntax gate
- Flexible design: steps may cross zones, complementary work is allowed (and
  reported), one level of sub-repeat is unrolled, and a 20-shape library is
  offered to Gemini as ideas, not a menu

**Not yet built:**
- CP/W′ (Critical Power) calculator — designed in the spec, not yet coded
- Using the intervals.icu upload from `pedir.py`: the module (`engine/intervals_upload.py`, dry-run by default, load check) is ready and tested but deliberately not wired in; for now the workout is a `.md` in `workouts/<intention>/` to paste or import
- Any web or desktop UI — CLI only, by design, for this phase

See [`CHANGELOG.md`](CHANGELOG.md) for the complete decision history and
[`docs/specification.md`](docs/specification.md)
for the full spec.

## Design philosophy in one sentence

The engine should feel like working with a thoughtful coach who investigates
and reasons every session — never like filling in a spreadsheet template.
