# Cycling Workout Generator — CHANGELOG & Restore Point
## (Gemini fork: `cycling-workout-engine-gemini`)

**Restore point date:** 2026-10-09 (v0.9.0 purpose guard, warmup/cooldown quality, Intervals.icu upload ready)
**Status:** Specification v2.10 · Engine v0.9.0 · 221 tests passing

This CHANGELOG carries forward the full history of the original
`cycling-workout-engine` (Claude reasoning layer) up to v0.3.0/spec v2.4,
then continues independently from here for this fork. Entries before
**0.0. v0.4.0** below describe the pre-fork project and its Claude-based
architecture accurately as of when they were written — they are historical
record, not a description of this repo's current behavior. See `README.md`
for the current (Gemini) architecture.

---

## v0.9.0 — Freedom with a purpose; warmups and cooldowns that make sense (2026-10-09)

### Why
Two things came out of the first real runs of v0.8.0 ("tempo de 45 minutos"):
1. Gemini designed a ladder of 76-80 / 81-85 / 86-90 % and called it Tempo.
   The last ten minutes were sweet spot: the session had stopped being the
   one that was asked for. v0.7.0 had removed the cage, and with it every
   guard on what the session *is*.
2. The warmup put the preparation in the middle and then dropped to 50-55 %;
   the cooldown went 55→45 % and then sat at 40-45 %.

### What changed
- **Purpose guard.** Each work step is classified by the midpoint of its
  range (recovery steps excluded, repeats expanded; the label does not
  count). At least **70 %** of the work must sit in the requested zone or
  the proposal is rejected with the exact numbers ("only 67 % of the work
  sits in Tempo; the rest is SweetSpot 33 %"). Between 70 and 90 % it is a
  design note. For Tempo the core ends at a midpoint of 86 % FTP; for a
  SweetSpot request the core is 84-97 %.
- **Warmup = build + pause.** The warmup proper is one build: starts easy,
  never below 45 % FTP / 60 % LTHR, rises without peaking and falling back,
  and arrives where the main set begins (within 15 points below to 5 above
  the first work step, judged against at most 100 %, so hard sessions use
  openers, not the full effort). It closes with the **preparation**: a
  30 s to 2 min step at very low intensity (about 50 % FTP, at most 60 %
  FTP / 75 % LTHR) so the athlete can drink and adjust before the main set.
  It is always the last element and never the whole warmup. (The first
  v0.9.0 draft wrongly made the preparation match the first work step.)
- **Cooldown only descends**, one smooth descent, never below the floor.
- Order of checks: zone errors and purpose first, hand-over after, so the
  feedback Gemini receives is the most useful one.
- **Prompt rewritten** with these criteria (what the engine checks is
  listed, with the reasons).
- **Intervals.icu upload: ready, unused.** `engine/intervals_upload.py`
  builds the payload (calendar bulk with upsert, or library), defaults to a
  dry run that shows the exact payload and the copy/paste text, needs
  `confirm=True` and `ICU_API_KEY` to send, and compares the load Intervals
  reports with the engine's TSS. `pedir.py` does not import it (a test
  guards that).
- Tests: 221 (30 new). Test mocks adapt canned warmups to the first work step
  through `tests/conftest.py`.

## v0.8.0 — Tidy repository, workouts filed by intention (2026-10-09)

### Why
Every generated workout was written to the repository root as
`workout_XXXXXXXX.md` (progressions as `progression_*` folders, the catalog as
`my_catalog.sqlite`), mixed in with the source and the documents. After a few
weeks the root was unusable.

### What changed
- **`workouts/` holds everything generated**, in a subfolder per intention:
  `recovery`, `endurance`, `tempo`, `sub_threshold` (sweet spot and HR
  SubThreshold), `threshold`, `vo2max`, `anaerobic`, `neuromuscular`. The
  intention comes from the requested zone (`engine/storage.py`, the same
  classes the shape library uses). Folders are created on first use.
- **Descriptive file names:** `2026-10-09_power_tempo_45min_382774b5.md`
  (date, mode, zone, total minutes, id). A progression gets its own folder,
  `<date>_<mode>_<zone>_progression_<id>/`, with `session_01.md`, `session_02.md`...
- **The catalog moved to `workouts/catalog.sqlite`.** An existing
  `my_catalog.sqlite` in the repository root is moved there the first time, so
  the engine keeps its memory.
- Anchored to the repository folder, so it no longer matters where the command
  is run from. `WORKOUT_ENGINE_WORKOUTS` keeps the workouts somewhere else.
- **`.gitignore`:** `workouts/*` is ignored except `workouts/README.md`. The
  old root patterns stay for leftovers.
- **Repository root cleaned:** `QUICKSTART.md`, the specification
  (`docs/specification.md`) and the schema (`docs/workout_engine_schema.json`)
  moved into `docs/`. The root now holds `README.md`, `CHANGELOG.md`, `VERSION`,
  `requirements.txt`, `athlete.example.yaml`, `pedir.py` and the folders
  `docs/`, `engine/`, `tests/`, `workouts/`. A test keeps it that way.
- **Preparation interval capped at 2 minutes** (was 5): 30 s to 2 min. Applies
  to the validator, the schema, the prompt and the offline warmups.
- Tests: 180 -> 191 (`tests/test_storage_v080.py`).

---

## v0.7.0 — Flexibility and creativity in session design (2026-10-09)

### Why
Several rules caged the reasoning layer into the most obvious session for the
requested zone: a work step had to sit entirely inside its zone, the requested
zone had to hold more work time than everything else combined, every zone used
had to be declared by hand, repeat blocks could not nest, and the prompt called
all of it "hard rules". The same lesson the Infame coaching system learned
(v7.35-v7.37): a session is defined by its purpose, and the way the work is
arranged around that purpose is the coach's design. This applies to every kind
of session: recovery, activation, aerobic, tempo, sweet spot, threshold, VO2max,
anaerobic and neuromuscular.

### What changed
- **The validator blocks errors, not designs.** Still rejected (and sent back
  to Gemini with the exact reason): a zone from the other system, impossible
  numbers (over 400% FTP / 120% LTHR), a step called recovery that is not easy
  (above 85%), a requested zone that never appears in the main set, a session
  longer than its budget, a target duration missed by more than 20%, a
  user-fixed warmup/cooldown length not met, a warmup that starts hard or lacks
  its preparation, a cooldown that is not easy. No longer rejected, now notes
  returned by `validate_proposal` and shown to the athlete as "Design notes":
  a work step that reaches past its zone, and most of the work time sitting
  outside the requested zone.
- **Complementary zones are derived by the engine** from what was built. The
  proposal no longer has to declare them correctly to be accepted.
- **One level of sub-repeat.** A repeat block may hold a sub-repeat, for example
  `4 x [5 x (30 s on / 30 s off), 4 min easy]`. The platform has no nested
  repeats, so `flatten_nested_repeats` unrolls the inner one into its block
  before anything is validated or built; deeper nesting and blocks over 80 steps
  are rejected.
- **Preparation interval, always.** Every warmup carries a short step or ramp
  (30 s to 5 min, `is_preparation: true`) that readies the body for the main
  block; it cannot be the whole warmup (from 2 min up). What it is stays the
  coach's design. The offline generator's warmups carry one too.
- **Shape library** (`engine/data/shapes.yaml`, `engine/shapes.py`): 20 ways to
  arrange the work (steady aerobic, aerobic touches, rolling, progressive
  blocks, intervals, ladders, pyramids, stepped builds, hard-start, over-unders,
  surges on a base, climb simulation, ramps, sprints, cadence contrast,
  activation openers, technique drills) and four ways they chain. Offered in
  the prompt as ideas: no default, no quota, no check that one was used, free
  to combine or to invent. No intensities. Ramp shapes are left out of HR mode.
  `WORKOUT_ENGINE_SHAPES=off` removes the library from the prompt. This is a
  deliberate, narrow amendment of spec 9.6 ("no pre-loaded knowledge base"),
  recorded there: arrangements only, no examples, numbers or authors.
- **Prompt rewritten** from "hard rules" to criteria: the purpose is the
  requested zone; variety must serve the purpose of the day; steady is right
  with a reason; the harder the session, the more a touch must earn its place;
  cadence is one tool among several. It lists exactly what the engine checks.
- **Intensity resolution with a TSS/IF target** now requires the dominant work
  as a whole (its time-weighted mean) to land inside the dominant zone, not every
  single step, so a build through a zone can still hit a target. A step the coach
  designed past its zone keeps its width.
- Parser: "recuperación", "activación", "pre-carrera" map to the right zones.
- `pedir.py` prints the design notes (Spanish and English).
- Tests: 146 -> 179 (`tests/test_flex_v070.py`); older tests that encoded the
  removed rules were rewritten to the new behaviour.

### Not changed
Output grammar, RPE derivation, the load formulas, budget ceiling, user-fixed
durations, and the engine staying independent of Infame.

---

## v0.6.0 — Warmup and cooldown designed per session (2026-10-08)

### Why
Every session had the same warmup — a 45-75% ramp plus a fixed 1-2 min
block at 45-55% — and the same 75-45% cooldown ramp, whether it was a
30-minute recovery spin or a two-hour VO2max session. The specification
already said the engine reasons them; the code had them as constants.

### What changed
- **The reasoning layer designs the warmup and cooldown** for the session in
  hand, in the same proposal as the main set, and gives the reason
  (`warmup_cooldown_rationale`). Criteria in the prompt, not rules: brief in
  short sessions (~5 min warmup, 2-3 min cooldown), longer as duration and
  intensity grow, short openers before hard work when they help.
- **Python checks sanity and arithmetic only** (`engine/sections.py`): a
  warmup starts easy (≤ 65% FTP / 80% LTHR) and, in HR mode, climbs; a
  cooldown stays at or below the Endurance top (75% / 89% LTHR) and ends
  easy; ramps are power-mode only; sanity lengths 25 min warmup / 15 min
  cooldown; the whole session within the time budget.
- **A length the user asks for is used exactly.** "calentamiento de 15
  minutos" → the parser fills `warmup_minutes`, the prompt states it, and a
  proposal that misses it is rejected with the exact reason and retried. Same
  for the cooldown. `engine.cli --warmup / --cooldown` do the same offline.
- **The fixed prep block is gone**, in power and HR mode.
- **Proposal schema:** `warmup` and `cooldown` are lists of `step`, `ramp`
  (power only) and `repeat` elements; `warmup_seconds`, `prep_seconds`,
  `cooldown_seconds` and `hr_warmup_staircase` are removed. The HR staircase
  is now simply the HR warmup, with its climbing check kept.
- **The intensity resolver** solves on the designed warmup and cooldown, so a
  TSS/IF target accounts for exactly what is built.

### Offline mode respects the duration
`python -m engine.cli --duration 50` produced 57 minutes: the placeholder main
set ignored the budget. It now uses 5/3 min sections up to 45-minute sessions
(10/5 beyond, or the requested lengths) and fits the main set to the time
left: 30, 45, 50, 60, 75 and 90 minutes all land within the budget (tested).

### Resting HR default
A missing resting HR now takes 60 bpm, Intervals.icu's own default: with 60
the HRSS formula reproduced both planned HR workouts of an athlete with no
resting HR on record (17 vs 18, 124 vs 125 TSS). The load is then reported as
exact HRSS; the typical profile is used only without LTHR or max HR.

### Other
- Specification v2.7: Section 11 rewritten; `workout_engine_schema.json`
  updated to match.
- Tests: 112 → 138.

---

## v0.5.0 — Training load as Intervals.icu computes it (2026-10-08)

### Power: Normalized Power with the 30 s rolling average
- The load was a simplified NP: segment powers to the 4th power, averaged by
  time, with no rolling window, and ramps costed at their midpoint.
- Now: a 1 Hz stream (ramps linear), 30 s rolling average (over the seconds
  available at the very start), 4th power, mean, 4th root.
- **Evidence.** 85 real planned power workouts from the head coach's
  Intervals.icu calendars were recomputed with three methods and compared
  with the load Intervals.icu stored for each:

  | Method | Mean error | Largest error |
  | --- | --- | --- |
  | NP with 30 s rolling window (new) | 0.48 TSS | 1.4 TSS |
  | Simplified NP, no window (v0.4.x) | 1.95 TSS | 58 TSS |
  | Per-step sum of hours × IF² × 100 | 2.41 TSS (mean −4%) | 11 TSS |

  The workouts are athletes' data and are not stored in this repository;
  only the result is recorded here.
- **Correction to an earlier review (2026-10-08).** A comparison with
  Infame Elite Endurance Coach had concluded that this engine over-read
  interval sessions by 9–29% against Intervals.icu, assuming Intervals.icu
  costs each step as hours × IF² × 100. The measurement above shows the
  opposite: Intervals.icu uses NP with the rolling window, and the per-step
  method under-reads intervals.
- The intensity resolver now solves on the session in its real order
  (warmup, prep, main set with repeats expanded, cooldown), because the
  rolling window makes NP depend on order, and by bisection (no closed form
  with the window). `solve_work_power_frac` / `solve_dominant_intensity`
  are replaced by `tss.solve_scale`; their hand-calculated tests are replaced
  by hand-calculated NP cases and reconstruction tests.

### Heart rate: HRSS
- The HR load was `IF_eq = 1.5 × (fraction of LTHR) − 0.5`, a mapping with
  no source in the platform.
- Now: HRSS (normalised Banister TRIMP), the method the Intervals.icu
  workout builder uses for heart-rate workouts — each second in whole bpm,
  `HRr = (HR − rest) / (max − rest)`, TRIMP per minute
  `HRr × 0.64 × e^(1.92 × HRr)`, scaled so 60 min at LTHR = 100.
- It needs LTHR, max HR and resting HR. Without them a typical profile
  (max = 1.09 × LTHR, rest = 0.37 × LTHR) stands in and the session is
  flagged approximate (`tss_method = "hrss_typical"`; `pedir.py` and the CLI
  say so next to the TSS).
- Evidence, and its limit: Intervals.icu's developer states that the
  builder uses HRSS for HR workouts, and the formula is the one Intervals.icu
  users have reproduced (Banister TRIMP with 0.64 and 1.92). Against real
  planned HR workouts the check is weaker than for power: with today's
  thresholds it reproduced 2 of the 8 sessions checked to within 0.6. The
  others were planned when the athletes' thresholds or resting HR were
  different (Intervals.icu keeps the values of the day), so they cannot be
  checked from here. Treat HR loads as close, not exact, until more
  HR workouts are checked.

### Athlete thresholds: `athlete.yaml`
- New optional file at the repository root (git-ignored), template
  `athlete.example.yaml`: `ftp_watts`, `w_prime_joules`, `lthr_bpm`,
  `max_hr_bpm`, `resting_hr_bpm`. Read by `pedir.py` and `engine.cli`
  (command-line values override it). Unknown fields, non-numbers and
  heart rates out of order are rejected with a clear message.
- `pyyaml` added to `requirements.txt`.

### Other
- `GeneratedSession.tss_method` records how the load was computed
  (`np_30s`, `hrss`, `hrss_typical`).
- Specification v2.6: Sections 5 and 16 rewritten.
- Tests: 94 → 112.

---

## v0.4.1 — Cleanup, current model, single surviving engine (2026-10-08)

This repository is now the only workout engine. The Claude-based
`cycling-workout-engine` is archived: everything it had is here, plus the
HR-staircase content check it never received. The engine stays independent
of Infame Elite Endurance Coach — anything taken from Infame is copied in,
never read from that repository at run time.

### Model
- **Default model: `gemini-3.8-flash`** (newest on the API, stable, Sept
  2026). The Pro tier is still `gemini-3.1-pro-preview` (older, preview).
  All model settings moved to one module, `engine/llm_config.py`; the model
  and the thinking level of each call can be overridden with environment
  variables.
- **Temperature removed everywhere.** The research, structure and parser
  calls set 0.5, 0.4 and 0.0. Google documents that Gemini 3 models can
  loop or degrade below the default of 1.0. A test now fails if any module
  sets a temperature.
- **Thinking levels set explicitly:** research `medium`, structure `high`,
  parser `low`.
- The two-call research/structure pattern stays. Gemini 3 now accepts
  structured output together with Google Search; merging the calls is a
  possible saving once tested against the live API.

### Corrections to the v0.4.0 record
- v0.4.0 reported 115 tests and 8 new HR-staircase tests. The repository
  had 77 tests and none of those 8. They are written now
  (`tests/test_cleanup_v041.py`), together with the other new tests:
  94 in total.
- `test_hr_staircase_schema.py`, a one-off script at the root that called
  the live API, made a plain `pytest` run fail at collection without
  `google-genai`. Removed: its question (does Gemini accept the
  array-of-arrays shape) is answered by the engine running in use.

### New checks
- **Unknown proposal fields are rejected.** The API schema cannot carry
  `additionalProperties: false`, so a misspelled field (e.g.
  `cooldown_secs`) was silently ignored and the default used instead.
- JSON answers are parsed in one place (`llm_config.parse_json_text`), with
  a clear error on an empty answer instead of a bare `JSONDecodeError`.

### Repository
- `requirements.txt` added (`google-genai>=2.29`, `pytest`, `jsonschema`).
- GitHub Actions runs the tests on every push
  (`.github/workflows/tests.yml`).
- `docs/SETUP.md` rewritten for Gemini (it still described the Anthropic
  key and 48 tests). README and SETUP no longer point to a `workout_engine/`
  folder that does not exist: everything runs from the repository root.

---

## 0.0. v0.4.0 — Gemini reasoning-layer migration + audit (6 findings closed)

Full port of the reasoning layer from the Claude API (`anthropic` SDK,
tool-use) to the Gemini API (`google-genai` SDK, `response_schema`). Every
finding below was reproduced/confirmed before fixing — two of them (the dead
model, the schema-content loss) live-tested against the real API, not just
inferred. Test count: 77 → 115 (added `generator.py`'s suite back in +
8 new HR-staircase-content edge cases). All 115 pass.

### Critical
- **G1 — Default model was already retired.** `gemini_client.py` and
  `request_parser.py` both defaulted `WORKOUT_ENGINE_MODEL` to
  `gemini-1.5-pro`. Confirmed: all Gemini 1.0/1.5 models are shut down
  API-wide and return 404. Fixed to `gemini-3.1-pro-preview` (current GA-
  quality flagship reasoning tier at time of writing; see README for the
  naming caveat and the deprecation-check reminder — this exact bug is
  guaranteed to recur if the model string is never revisited).
- **G2 — `response_schema` + `google_search` tool are incompatible on the
  current API** (`400 INVALID_ARGUMENT: controlled generation is not
  supported with google_search tool`). `pedir.py` calls both
  `generate_single_v2` and `generate_progression` with `use_web_search=True`
  unconditionally, so every generation with search enabled would have failed
  outright. Rearchitected into two calls, always active (confirmed with the
  project owner that web search here is deliberately about variety/
  creativity/effectiveness, not fact-grounding, so it stays on for every
  request, not just a narrow case): a **research call** (`google_search`
  enabled, free-form prose, no schema) followed by a **structure call**
  (`response_schema` enabled, no tools, the research notes folded in as
  context). Both calls use the same model.
- **G3 — Tool schema's top-level `description` was silently dropped.** The
  transport layer only ever forwarded `tool["input_schema"]` to Gemini's
  `response_schema` — the wrapping `name`/`description` that Anthropic
  tool-use sends automatically has no Gemini equivalent, so it was just
  never sent. Most damaging in `PARSE_TOOL_SCHEMA`, whose top-level
  `description` carries the entire bilingual (ES/EN) zone-name mapping
  table — natural-language requests were being interpreted with none of that
  guidance reaching the model. Fixed: both `gemini_client.py` and
  `request_parser.py` now fold `tool["description"]` into
  `system_instruction` on every call.

### Minor
- **g1 — Broken prompt string.** `build_user_prompt` in `gemini_client.py`
  had a leftover `"%s"` literal (not an actual substitution) in the TSS/IF
  guidance text sent to the model. Corrected to read as intended.

### Medium (pre-existing, not introduced by this migration)
- **g2 — `hr_warmup_staircase` content was never validated.** Only its total
  seconds were summed for the budget; nothing checked that steps were
  ascending, that `low_pct <= high_pct`, that percentages were non-negative,
  or that values were even the right type. A malformed or descending
  staircase from the reasoning layer would have passed through silently in
  both the original Claude version and this fork. Added
  `_check_hr_staircase()` to `proposal.py`, wired into `validate_proposal()`
  for HR mode; 8 edge-case tests (ascending-valid, descending, inverted
  range, negative percent, zero duration, non-integer, malformed length,
  same-`low_pct` plateau).

### Verified, no change needed
- **Nested-array schema for `hr_warmup_staircase`** (`[[low,high,seconds], ...]`)
  was suspected to need flattening to an array of objects for Gemini's
  `response_schema` (a known JSON-Schema-subset gap on this API). Live-tested
  against `gemini-3.1-pro-preview`: accepted as-is. No change made to
  `proposal.py`'s schema or to `build_from_proposal.py`.

### What did NOT change
`proposal.py`'s hard-rule validation (zone containment, dominant/subordinate
boundary, no nested repeats, budget conservation), `progression.py`,
`generator_v2.py`, `generate_progression.py`, `zones.py`,
`build_from_proposal.py`, and the entire deterministic core (`tss.py`,
`render.py`, `rpe.py`, `structure.py`, `assembler.py`, `catalog.py`,
`resolve_intensity.py`, `generator.py`) required **no changes** — they never
depended on which provider sits behind the `Transport` interface. This was
confirmed by running the full pre-existing test suite (`test_phase2.py`,
which exercises the `Transport` contract directly: 38/38 pass unmodified)
alongside `test_core.py` (77/77 pass unmodified).

---


Result of a complete adversarial audit of the codebase against spec v2.3.
All findings were reproduced with code before fixing; every fix carries
regression tests. Test count: 50 → 77.

### Critical
- **C1 — HR mode + catalog crashed** (`generator.py` accessed `warmup.ramp`
  which is `None` in HR mode). The documented `cli.py` example command
  crashed. Fixed with mode-safe duration math; regression test added.
- **C2 — Budget ceiling could be silently violated.** A proposal omitting
  `warmup/prep/cooldown_seconds` validated with structure=0, then the builder
  filled large defaults: a 30-min request built a 45-min session. Validation
  now runs against the EFFECTIVE structure durations the builder will
  actually use (in HR, the real staircase sum governs the warmup — this also
  closed M2's budget side).
- **C3 — The deterministic TSS/IF resolution (spec 16.2) was never wired
  in.** `solve_work_power_frac` existed and was tested, but the pipeline hit
  TSS targets by letting Claude guess within ±10%. New module
  `resolve_intensity.py`: Claude fixes the STRUCTURE; the engine solves the
  one free variable (dominant work intensity) in closed form, preserving the
  proposal's internal ratios between work steps (over/under etc.).
  Infeasibility is reported with the closest achievable TSS (spec 16.3);
  rounding follows spec 16.4 (integer center, proposed width shrunk
  symmetrically only to stay in-zone). Hand-calculated reference tests per
  the spec 16.5 mandate.

### High
- **A1 — Zone validation only required overlap, not containment.** A
  75-105% "Tempo" interval passed. Work ranges must now be CONTAINED within
  their named zone (boundary-inclusive: 75-90% IS valid Tempo; open-ended
  Neuromuscular checks its lower bound only).
- **A2 — A requested IF was never verified.** `verify_if_target` added
  (power mode), symmetric to the TSS check; with the C3 resolver in the path
  it holds by construction.
- **A3 — The 80% budget floor was applied to `max_available`.** A maximum is
  a CEILING, never a target to fill (filling available time is a coaching
  decision). The floor now applies only to target durations (Day 1 of a
  progression included); later progression sessions are capped by max only.
- **A4 — Retries carried no feedback.** The exact rejection reason is now
  injected into the next attempt's prompt (sessions and progressions), so
  the model corrects instead of guessing blind.

### Medium
- **M1 — Spec self-contradiction on ramp RPE.** Section 6.3 and the 11.4
  examples said a 45-75% ramp → [RPE 1-4] while the implementation note said
  [RPE 1-5]. Corrected to [RPE 1-5] under the half-open boundary convention
  (75% falls in Tempo); spec bumped to v2.4.
- **M2 — Declared `warmup_seconds` vs. real HR staircase sum diverged**
  silently. The staircase sum now governs (see C2).
- **M3 — Missing proposal fields leaked `KeyError`.** Steps missing numeric
  fields, zero durations, or repeats missing/invalid now produce a clean
  `ProposalRejected`.
- **M4 — TSS-vs-duration conflicts without a user IF died generically.**
  New `check_zone_feasibility`: the requested zone's top intensity bounds
  what is achievable — "TSS 100, max 20 min, Tempo" now reports "needs at
  least 74.1 min at the zone's top (90%); highest achievable is ~27" BEFORE
  any API call. A target IF above the zone ceiling is likewise reported.

### Minor / New
- **m1** — Dead `use_web_search` parameter removed from
  `anthropic_transport` (the real toggle flows through the transport call).
- **m2** — HR staircase steps are flat steps, not ramps: role label
  corrected to `warmup_step`.
- **m3** — Recovery sanity check now bounds the range's HIGH end (an "easy"
  80-90% no longer slips through).
- **N1 — hrTSS-type estimate for HR mode (new spec Section 16.6).**
  Previously the HR-mode TSS applied power-NP math to %LTHR (physically
  incoherent). Now: continuous mapping `IF_eq = 1.5·(LTHR fraction) − 0.5`
  (floored at 0), TSS accumulated segment-wise (no NP — 4th-power weighting
  models power variability, meaningless on HR). A continuous function, not a
  zone-table correlation: Section 4's no-cross-correlation rule stands.
- Shared `DEFAULT_HR_STAIRCASE` constant (duplication removed); over-
  determined requests (TSS+IF+duration mutually inconsistent) reported per
  spec 16.1; TSS+IF without duration now derives the implied duration.

---

---

## 0.1. v0.2.1 — Deliberate loose budget floor (flexibility > exact-minute precision)

- **Decision:** the time-budget rule (spec 15/16) already had a hard ceiling
  (never exceed the stated budget). It had no floor — a session could come in
  well under budget with no signal. Real-world test: a 60-min request
  produced a 58-min session (a ~3.3% shortfall) with no issue flagged.
- **Explicit choice made:** maximize the engine's creative flexibility over
  exact-minute precision. Minor shortfalls (a couple of minutes) are left as
  acceptable — the athlete can add time manually (extra warmup, one more rep)
  if they want the exact total. Forcing an exact match would push the engine
  toward padding structure just to hit a number, which is the rigidity this
  project has consistently avoided.
- **What changed:** added a deliberately loose floor at 80% of the budget —
  only a genuinely considerable shortfall (e.g. 35 min of a 60-min request)
  is now rejected; anything above that floor passes with no friction. The
  ceiling behavior (never exceed) is unchanged.
- 2 new regression tests (minor shortfall passes; considerable shortfall
  rejected). Test count: 48 → 50.

---

---

## 0.2. v0.2.0 — Bilingual requests + Quick Start Guide

- **Bilingual natural-language requests (Spanish or English).** The parser
  (`request_parser.py`) now explicitly detects the input language and returns
  it as a `language` field; zone-wording examples in the prompt cover both
  languages for every zone (previously only 2 Spanish examples existed,
  leaving English behavior unguaranteed/implicit). `interpretation_note` is
  now guaranteed to mirror the request's language.
- **`pedir.py` fully bilingual end-to-end.** All fixed status text
  (interpreting/generating/errors/labels) is now selected from an ES/EN string
  table based on the detected language, so the whole interaction — not just
  Claude's interpretation — matches whichever language the user typed in. The
  no-argument usage message shows both languages (since the language isn't
  known yet at that point).
- **Added `QUICKSTART.md`** — a fast, practical, copy-paste usage guide in
  both Spanish and English (examples, phrasing table, what to expect,
  uploading to intervals.icu, common issues).
- No breaking changes; all 48 existing tests still pass unmodified.

---

---

## 0. Cleanup pass (latest session)

A full module-by-module review found and fixed:

- 🔴 **Critical (fixed):** `generate_progression.py` never applied the budget-aware
  warmup/prep/cooldown sizing or budget validation that `generator_v2.py` got
  earlier — every progression session silently used the max 10/2/5-min
  structure regardless of the user's stated time budget (e.g. a 30-min Day-1
  request). Now fixed: per-session budgets computed (Day 1 = initial budget;
  later sessions = user's max, if given), Claude-proposed structure durations
  used, budget conservation enforced identically to single sessions.
- 🟠 **Important (fixed):** a requested `target_tss`/`target_if` was never
  verified against what was actually built — `solve_work_power_frac` existed
  but was never called. Added `verify_tss_target()` (±10% tolerance) into the
  generation retry loop; a proposal whose real TSS deviates too much is now
  rejected and retried, never silently accepted.
- 🟡 Minor fixes: stale docstring in `models.py`; zone name now validated
  locally before spending API retries (fail fast); `format_duration` guards
  against a theoretical empty-duration render; `complementary_stimuli`
  metadata must now match what's actually used in `main_set` (metadata
  honesty check).
- Added: `pedir.py` (natural-language front-end command) + `request_parser.py`
  (Claude-based interpretation of plain-language requests into structured
  parameters — user never needs to know internal zone names).
- Test count: 43 → 48 (6 new regression tests covering all fixes above).

---

This document is a single-glance snapshot of where the project stands: every
locked decision, the architecture, what's built, what's tested, and what
remains. Use it to resume cleanly without re-reading the whole conversation.

---

## 1. Project in one paragraph

A **standalone, local** Python engine that generates **indoor cycling workouts**
(single sessions and reasoned multi-session progressions) as **intervals.icu
syntax** (`.md` files). Output is always **percentage-based** (`%` of FTP for
power, `% LTHR` for HR) with **RPE ranges**. The engine's intelligence comes
from a **Claude reasoning layer** (creativity, structure, progression logic)
sitting on top of a **deterministic Python core** (math, rendering, validation,
catalog). It is independent of all other projects (not tied to the existing
coach prompt or zone KBs).

---

## 2. Locked decisions (the spine of the project)

### Identity & philosophy
- **The engine reasons; it does not pick from a menu.** No fixed recipe tables.
- **NO pre-loaded knowledge base, ever** (spec §9.6). A KB degenerates into a
  template and makes the engine lazy. Reasoning = free reasoning + **live web
  search** only. Web search is kept; a static KB is forbidden.
- **The engine obeys; it is not a coach.** It generates what's asked. It never
  decides *when/whether* to apply training, athlete readiness, periodization
  shape — those belong to a separate coach. Incomplete requests are flagged,
  never silently filled.
- **Governing split:** training-methodology decisions are engine-reasoned (or
  user-specified), never defaulted by code; purely mechanical/arithmetic
  decisions (TSS math, budget conservation, rendering, catalog) are the core's.

### Zones (spec §4)
- **Friel preset zones**, used **natively and independently**. Power (%FTP) and
  HR (%LTHR) are **never cross-correlated** — same zone names (e.g. "Tempo")
  are different systems. Power is primary/default; HR is secondary.
- Friel zone boundaries are **unmodified** — naming-only relationship to CP.

### CP / W′ (spec §7)
- Physiological foundation is **CP/W′**; "FTP" is only the display label for the
  single power-anchor value (one number, not two).
- **CP/W′ model is optional**, engages only when the user supplies CP + W′.
  Canonical algorithm: **Skiba 2015 W′BAL-INT** (not the 2012 version).
- A 3-tier calculator is *designed* (direct entry / multi-effort linear /
  3-min all-out) but **not yet coded**.

### RPE (spec §6)
- Borg CR10, **always a range** `[low-high]`. Single value only as `[1-1]`/`[10-10]`.
- Confirmed zone→RPE table (§6.2): Recovery 1-2 · Endurance 2-4 · Tempo 3-5 ·
  Threshold 5-7 · VO2max 7-9 · Anaerobic 8-10 · Neuromuscular 9-10.
- Derivation (§6.3): flat segment → midpoint→zone→band; ramp → floor of lower
  endpoint's band to ceiling of upper endpoint's band.

### Mandatory session structure (spec §11) — flexible, engine-reasoned
- Every session = **Warmup + Main Set + Cooldown**, always.
- **Durations are flexible and engine-reasoned**; the 10-min warmup / 5-min
  cooldown figures are **caps, not targets**. Short sessions get short warmups.
- **Power mode:** warmup = ascending **ramp**; cooldown = descending ramp or a
  fixed easy block.
- **HR mode:** warmup = ascending **staircase of steps** (NOT a ramp — HR can't
  follow a smooth ramp); cooldown = fewest steps possible, ideally one block.
- **Prep block** (the only always-present block): `45-55%` (power) /
  `60-80% LTHR` (HR), duration **flexible 1–2 min**, always present.

### Output / export (spec §12)
- Engine writes **directly in intervals.icu syntax** (no narrative layer). Export
  is a thin wrapper that uploads the `.md` as-is.
- **Output-validation gate** rejects out-of-scope constructs (distance `mtr`/`km`,
  `freeride`, `% HR` vs max-HR, `% Pace`) before export.
- Repeat blocks are **never nested**; divided patterns = sequential blocks.

### TSS / IF (spec §16)
- Exact algebra: `TSS = hours × IF² × 100`. **Simplified NP** (4th-power
  weighted, no 30s rolling average) — option A, robust; engine TSS is a
  **design-time estimate**, intervals.icu computes the authoritative value.
- **Always round** to valid syntax; report the **real TSS of the rounded
  workout**, not the target.
- **Infeasibility is reported with numbers, never forced** (e.g. TSS target that
  can't fit in max duration). Budget conflicts likewise.

### Progressions (spec §15) — time-budget driven
- Driver = athlete's **available time per session**, not a week pattern or any
  author's recipe.
- **Case A** (initial duration only): grow to the stimulus's **physiological
  ceiling**, which the engine **researches live**; note graduation to next
  stimulus at the ceiling.
- **Case B** (initial + max): develop ideal load between the two.
- Only fixed floor: the sequence must be **coherent and directional**. *How* it
  progresses is engine-reasoned. No imposed methodology (the Cusick example was
  inspiration, never a rule).
- **Budget conservation is arithmetic** (Python): warmup+prep+cooldown+main ≤
  budget. The *split* of that budget is engine-reasoned.

### Catalog / anti-repetition (spec §17) — memory, not a rule engine
- **SQLite catalog** = the engine's own **memory + reusable library**. NOT a
  mechanical "signature comparison" (that approach was rejected — it broke
  natural progressions like `4×10`→`4×12:30`).
- Variety comes from the engine **reasoning over its own catalog** + knowledge +
  web search. `pattern_signature` concept was **dissolved**, not deferred.
- Dominant/subordinate boundary: the requested stimulus stays dominant; any
  complementary stimuli are subordinate (open-ended, engine-discovered).
- `progression_id` exempts within-progression repetition from penalty.

### Reasoning layer architecture (spec §9)
- **Claude API** via the `anthropic` SDK + **tool-use** (structured proposal) +
  optional **web search**. Not a Claude Project (not callable from code).
- Claude **proposes structure**; Python **validates against hard rules, does all
  math, renders**. Rejected proposals are discarded & re-requested — never
  silently fixed, never accepted blind.
- `--offline` mode runs the deterministic core without API calls.
- Future-web-portable: no Claude Project dependency, no static KB to port.

---

## 3. What's BUILT and TESTED (43 tests passing)

### Deterministic core (Phase 1)
| Module | Role |
|---|---|
| `zones.py` | Friel power/HR zones, independent |
| `rpe.py` | RPE derivation (flat midpoint / ramp endpoints) |
| `render.py` | intervals.icu syntax + rounding + output gate |
| `tss.py` | TSS/IF/NP math, single-unknown resolution, infeasibility |
| `catalog.py` | SQLite memory + library, persistent |
| `models.py` | request/session dataclasses |
| `structure.py` | mandatory structure (power ramp / HR staircase), flexible durations, budget conflict |
| `assembler.py` | final `.md` assembly + real TSS |
| `generator.py` | Phase-1 end-to-end (provisional placeholder structure) |
| `cli.py` | command-line interface, `--offline` |

### Reasoning layer (Phase 2)
| Module | Role |
|---|---|
| `proposal.py` | tool-use contract + hard-rule validator (incl. budget arithmetic) |
| `claude_client.py` | prompt building, API call (injectable transport), web search |
| `build_from_proposal.py` | validated proposal → engine components |
| `generator_v2.py` | Phase-2 single-session orchestration (validate→build→render) |

### Progressions
| Module | Role |
|---|---|
| `progression.py` | progression tool contract + per-session validation |
| `generate_progression.py` | full reasoned progression, shared `progression_id` |

### Test coverage
- TSS/IF math with **hand-calculated reference cases** (spec §16.5 mandate).
- RPE derivation (flat + ramp).
- Rendering + output gate (accepts `% LTHR`, rejects distance/freeride/`% HR`).
- End-to-end power & HR generation.
- HR staircase (not ramp) + single-block cooldown; power unchanged.
- Phase-2 integration via **mock transport**: valid proposal flows through;
  invalid ones (complementary dominates, cross-mode zone, nested repeat) rejected.
- Progression: volume/TSS up while IF stable, shared `progression_id`, valid `.md`.
- **Budget conservation**: fitting session passes, over-budget rejected with exact overage.

---

## 4. Companion artifacts

| File | What |
|---|---|
| `cycling_workout_generator_specification.md` | Canonical spec, v2.3 (~460 lines) |
| `workout_engine_schema.json` | Validated lean JSON Schema (decision 2a) |
| `workout_engine/` | The engine package + tests + README |

---

## 5. What remains (next candidate steps)

1. **Wire the budget logic into progressions** so Day-1 (e.g. 30 min) truly fits
   and grows from there (single-session budget conservation is done; progression
   path should use the same).
2. **CP/W′ calculator** (spec §7.2) — designed, not coded.
3. **intervals.icu export script** — upload the `.md` via API (thin wrapper).
4. **Real-API run** on the user's machine (`pip install anthropic`,
   `ANTHROPIC_API_KEY`) to see Claude reason live vs. the mock.
5. (Later, if ever) the future web front-end — architecture already kept
   portable (no Claude Project, no static KB).

---

## 6. Known notes / honest flags

- All "creative" structure in Phase-1 `generator.py` is **provisional placeholder**
  — superseded by Phase-2 reasoning. Kept for `--offline` and as durable plumbing.
- The spec's illustrative RPE/structure examples are explicitly **examples, not
  rules** throughout — this was a recurring correction and is now baked in.
- Web search + the catalog are **additive**, not exclusive; neither is a KB.
