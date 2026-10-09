# Cycling Workout Generator — Project Specification

**Status:** Draft v2.10 — Sections 11 and 12 (v0.9.0): the requested zone must carry at least 70% of the work (by step midpoint); the warmup is one build that arrives at the level of the first work step and closes with a very easy preparation pause; the cooldown only descends; the Intervals.icu upload is specified as dry-run by default and not wired into the generator. Previous: v2.9 — Section 11.2: the warmup preparation interval is 30 s to 2 min (v0.8.0); generated workouts are filed under `workouts/<intention>/` and the document files live in `docs/`. Previous: v2.8 — Sections 11.2, 12.2, 12.3 and 17 revised (v0.7.0): the validator blocks errors, not designs (zone containment and the dominance rule become notes), one level of sub-repeat is unrolled before output, every warmup carries a preparation interval, and a shape library is offered to the reasoning layer as ideas. Previous: v2.7 — Section 11 rewritten (v0.6.0): warmup and cooldown designed per session by the reasoning layer, a user-requested length adopted exactly, the fixed prep block removed. Previous: v2.6 — Section 16 rewritten (v0.5.0): power load is Normalized Power with the 30 s rolling average, HR load is HRSS (normalised TRIMP), both as Intervals.icu computes planned workouts; Section 5 gains the athlete settings file (`athlete.yaml`). Previous: v2.5 — Gemini reasoning-layer fork (`cycling-workout-engine-gemini`). Section 9 rewritten for the `google-genai` SDK / `response_schema` architecture, including the two-call research+structure pattern required by the API's grounding/structured-output incompatibility. All other sections (4–8, 10–17) are unchanged from v2.4 — they describe the deterministic core and hard rules, which are provider-agnostic. Previous: v2.4 — (a) Section 6.3/11.4 ramp-RPE examples corrected to the half-open zone-boundary convention: a `45-75%` ramp resolves to `[RPE 1-5]` (75% falls in Tempo), fixing the internal contradiction with the earlier `[RPE 1-4]` examples; (b) Section 16.6 added: hrTSS-type design-time estimate for HR mode; (c) Section 16 hardened in implementation: deterministic work-intensity resolution wired into the pipeline, budget ceiling enforced on effective structure, floor applies to targets only, zone containment (not overlap), rejection feedback on retries, zone-bounded conflict detection without a user IF. Previous: v2.3 (no-KB rule, Section 9.6).
**Governing principle — engine identity:** the engine has no prescribed menu. It is intelligent and equipped to investigate the methodology and physiology of the required training stimuli in depth, and from that foundation create individual sessions and progressions aligned with sound training principles. Reference material (the athlete's initial stimulus matrix, peer-reviewed sources) is *foundation to reason from*, never a lookup table to copy values out of. This is the core distinction from the monotonous generators this project replaces.
**Governing principle — coaching boundary:** the engine never defaults a training-methodology decision about *when/whether* to apply work (ramp-rate-over-weeks, recovery-week reduction, periodization shape, athlete readiness). Those belong to a separate coach. An incomplete request is flagged, never filled in. Purely mechanical/software decisions (algebraic solving, log schema, config defaults like a lookback window) and physiological generation decisions (work/recovery structure within a session, sampled by reasoning) remain the engine's legitimate territory.
**Scope:** This document assumes nothing beyond what is written here. Any behavior not explicitly listed should be treated as undefined and raised for clarification before implementation.

---

## 1. Project Identity

- This is a **standalone, independent project**. It does NOT read from, write to, or share logic with:
  - `Standardized_Cycling_Training_Zones.md`
  - `infame_elite_endurance_coach.md`
  - Any other existing coaching prompt or knowledge base
- The engine has no concept of "the athlete's other training," "what else they did this week," or any coaching judgment about appropriateness. It is a **command executor**, not a coach. Coaching judgment (whether a workout is wise given context) lives outside this project entirely.

## 2. Execution Environment

- **Language:** Python (chosen over Java — no technical reason favors Java here; the task is combinatorial generation + text/JSON output, not performance-critical computation).
- **Platform:** Local execution on Windows 11.
- **Mode:** Non-interactive. The engine runs as a script invoked with explicit parameters (CLI arguments and/or a config file). It does not prompt the user mid-run and does not hold a conversation.
- An `--offline` mode must exist that runs the deterministic Python core without calling the Gemini API (for development/testing without incurring API cost).

## 3. Core Design Philosophy

- **The engine obeys.** If the user requests "a Tempo workout, 50 minutes," the engine produces it. If the user supplies a target Load (TSS) and/or Intensity Factor (IF), the engine produces a workout matching those constraints.
- **The engine obeys for progressions too.** If the user requests "an 8-week Tempo progression, 1–2 sessions/week," the engine produces it.
- **The user may specify maximum available duration(s)** for sessions; the engine respects this as a hard constraint.
- **Physiological validity is a non-negotiable boundary, but the engine is an intelligent agent, not a selector.** The engine has no prescribed menu. It investigates the methodology and physiology of the required training stimuli in depth, reasons from that foundation, and creates individual sessions and progressions aligned with it. Creativity operates *within* physiological coherence, never by violating it — but it is genuine reasoning, not picking from a static list of named "recipe" workouts (e.g., always "4×4min") and not drawing values verbatim from a lookup table.
- **No drills, ever**, under any circumstance.

## 4. Zone Systems — Used Natively and Independently

The project uses Joe Friel's preset Power and Heart Rate zone tables exactly as configured in intervals.icu (see athlete's screenshots, FTP 225W / Threshold HR 156 / Max HR 176 example).

**Critical rule: the two tables are never cross-referenced or correlated.** If the user requests power-based generation, only the Power table (with its own RPE correlation, see Section 6) is used. If the user requests HR-based generation, only the HR table (with its own RPE correlation) is used. There is no mapping between "Power Z5" and "HR Z5" — they are independent systems that happen to share zone-index numbers, nothing more.

### 4.1 Power Zones (Friel preset, % of FTP)

| Zone | Name | % FTP |
|---|---|---|
| Z1 | Active Recovery | 0–55% |
| Z2 | Endurance | 55–75% |
| Z3 | Tempo | 75–90% |
| Z4 | Threshold | 90–105% |
| Z5 | VO2 Max | 105–120% |
| Z6 | Anaerobic | 120–150% |
| Z7 | Neuromuscular | 150%+ |
| SS | Sweet Spot (overlay) | 84–97% |

### 4.2 Heart Rate Zones (Friel preset, % of LTHR)

| Zone | Name | % LTHR |
|---|---|---|
| Z1 | Recovery | 0–80% |
| Z2 | Aerobic | 81–89% |
| Z3 | Tempo | 90–93% |
| Z4 | SubThreshold | 94–99% |
| Z5 | SuperThreshold | 100–102% |
| Z6 | Aerobic Capacity | 103–105% |
| Z7 | Anaerobic | 106–113% |

### 4.3 Output Format

- Default/primary mode: **Power-based**.
- Secondary/alternative mode: **HR-based (anchored to LTHR, never to max HR)**, used when explicitly requested.
- All intensity output is expressed as a **percentage range**, never a single value. Exact literal syntax (see Section 12.2 for the full grammar):
  - Power: bare `xx-xx%` (no "FTP" word — intervals.icu syntax treats unlabeled `%` as power)
  - HR: `xx-xx% LTHR` (never `% HR`, since that would be relative to max HR, not LTHR — this project's HR zones are LTHR-anchored only)
  - Output is **always percentage-based** — `%` of FTP for power, `% LTHR` for heart rate — per the intervals.icu syntax. The engine **never** emits absolute watts or absolute bpm under any circumstance. The power anchor value (CP) and LTHR, when provided, are used only internally (CP for the W′bal simulation, Section 7.2); they are never converted into absolute figures in the generated output.

## 5. Athlete Inputs — All Optional, Graceful Degradation

- **Power anchor value (the single number that serves as CP for the W′bal simulation; see Section 7.2.3):** optional. Used internally only — never converted into absolute watts in the output (output is always %-based, Section 4.3). Its absence does not change the output format, only whether the CP/W′ model (Section 7.2) can run.
- **LTHR:** optional, internal-only, independent of the power anchor. Same logic — never converted into absolute bpm in the output.
- **Max HR and resting HR:** optional, internal-only. Together with LTHR they let the engine compute the HR-mode load (HRSS, Section 16.6) exactly as Intervals.icu does; without all three it uses a typical profile and labels the load approximate.
- **Where these values come from (v2.6):** the user's own settings file, `athlete.yaml` at the repository root (git-ignored; template `athlete.example.yaml`). Every field is optional and a missing file or field never blocks generation.
- **W′ (anaerobic work capacity, kJ):** optional. Only used if explicitly provided. If the user provides a power anchor value but not W′, the engine does **not** block — it relies on the always-on physiological foundation (Section 7.1) for high-intensity zones instead of the CP/W′ model.
- The engine never queries intervals.icu (or any platform) for these input values automatically.

## 6. RPE Layer (Borg CR10, 1–10)

This is a **project-specific addition**, not part of Friel's or intervals.icu's native zone tables. It exists purely to give the athlete an in-the-moment perceptual guide during execution.

### 6.1 Range Formatting Rule

RPE is always shown as a range `[low-high]`, never a bare single number, computed from a target value **N**:

- If N = 1 → `RPE [1-1]`
- If N = 10 → `RPE [10-10]`
- For any N from 2 to 9 → `RPE [N-1 - N+1]`

Example: target RPE 5 → `RPE [4-6]`. Target RPE 3 → `RPE [2-4]`. Target RPE 8 → `RPE [7-9]`.

This rule applies when a specific RPE target is being expressed for a generated interval.

### 6.2 Zone-to-RPE Correlation Table — ✅ CONFIRMED

This table assigns a native RPE band to each zone (used when the workout is generated by zone selection rather than a direct RPE target). It is independent for Power and HR — each zone system uses its own band keyed by physiological meaning, not by zone index number.

Verified reference: Coggan, A.C. and Allen, H. (2010). *Training and Racing with a Power Meter*. Boulder: VeloPress. Original published RPE column: Active Recovery <2, Endurance 2–3, Tempo 3–4, Lactate Threshold 4–5, VO2 Max 6–7, Anaerobic Capacity >7, Neuromuscular Power "Maximal." Table below adjusted from that source to track the athlete's continuum-based judgment while keeping Anaerobic above VO2max's ceiling, per the original source.

**Confirmed working table:**

| Zone (physiological meaning) | RPE band |
|---|---|
| Recovery / Active Recovery | 1–2 |
| Endurance / Aerobic | 2–4 |
| Tempo | 3–5 |
| Threshold / SubThreshold–SuperThreshold | 5–7 |
| VO2 Max / Aerobic Capacity | 7–9 |
| Anaerobic | 8–10 |
| Neuromuscular | 9–10 |

This table is locked into the data schema.

### 6.3 RPE Derivation per Segment — Flat vs. Ramp

Every generated line carries an RPE range, derived from the segment's intensity by one of two rules depending on segment type:

- **Flat-% segment** (single intensity range — main-set work intervals, recovery intervals, fixed cooldown): take the **midpoint** of the % range, identify which zone that midpoint falls into, and assign that zone's RPE band from the table in Section 6.2. Example: `45-55%` → midpoint 50% → Recovery zone → `[RPE 1-2]`.
- **Ramp segment** (crosses zones — warmups, descending cooldowns): the RPE range spans from the **floor of the lower endpoint's zone band** to the **ceiling of the upper endpoint's zone band**, per the Section 6.2 table. Worked example (illustrative only — the actual ramp `%` values are engine-determined per session, Section 11, so the resulting RPE varies): for a ramp of `45-75%`, lower endpoint 45% = Recovery (band 1–2, floor = 1); upper endpoint 75% sits on the Endurance/Tempo boundary and, under the project's half-open zone convention (low ≤ pct < high), falls in **Tempo** (band 3–5, ceiling = 5) → `[RPE 1-5]`. The **rule** (floor of lower, ceiling of upper) is fixed; the `[RPE 1-5]` result is just this one example's output, not a constant.

Note: the canonical source for these RPE bands is this project's Section 6.2 table, **not** the RPE column shown in the intervals.icu syntax reference file (which is based on the standard Coggan zone/RPE table and differs — e.g., it shows Endurance as 2–3, whereas Section 6.2 uses 2–4). Where the two differ, Section 6.2 always governs. This is why a `45-75%` warmup ramp resolves to `[RPE 1-5]` here rather than the `[RPE 1-3]` seen in the reference file's examples.

## 7. Physiological Validation Model

### 7.1 Always-On Physiological Foundation

For every zone, work duration, **recovery duration between repetitions**, and repetition count are governed by the physiological foundation established in the athlete's initial stimulus matrix (which carries concrete work:recovery examples per zone — e.g. `4×4 min (4 min recovery)`, `12×30s ON / 30s OFF`, `20 min SS → 3 min easy → 20 min SS`) together with peer-reviewed and established-coaching sources (Buchheit & Laursen's HIT taxonomy, Carmichael/CTS for anaerobic capacity, etc.). Zone boundaries themselves are Friel's (Section 4); Coggan & Allen is cited only as the starting reference for the RPE correlation (Section 6.2), not as the zone system.

**Crucial framing:** these examples are *reference and foundation* — they establish what is physiologically coherent (the "spirit" of each stimulus and the relationship between work and recovery) — **not a fixed menu the engine copies from.** The engine **consults this foundation, analyzes it, decides, and generates its own combinations** of work and recovery that honor the physiology without being limited to the exact example values. The recovery interval between reps is an intrinsic part of this reasoning — it is not a separately-decided parameter, not a coaching judgment, and not a value pulled verbatim from a lookup table. This is precisely the difference between this engine and the monotonous generators it replaces: it reasons from physiological principle rather than selecting from a static list. This foundation informs every generation, regardless of what athlete data is available.

### 7.2 Optional Enhancement: Critical Power / W′ Model

- **The power anchor is a single value; "FTP" is only its display label, "CP" its modeling role — see Section 7.2.3 (canonical definition).** Friel's zone boundaries and % bands (Section 4.1) remain exactly as defined, with zero modification — they are never re-derived from a CP/W′ curve.
- This module lives permanently in the engine, but only engages **per request**: it activates only when the user explicitly supplies both a CP and a W′ value for that specific session/progression/block request (no global "athlete profile" requirement). If only the power-anchor value is given without W′, the engine does **not** block — it relies on the always-on physiological foundation (Section 7.1) for that request.
- When active: simulates W′ depletion/reconstitution across a proposed interval structure to confirm a sampled combination is physiologically sustainable for that specific athlete before accepting it.
- This model is **power-based only**. It does not apply to HR-based generation (W′ has no direct heart-rate analog); HR-mode generation always relies on the physiological foundation (Section 7.1) only.
- **Canonical algorithm: Skiba et al. (2015), the W′BAL-INT (integral) model** — not the original Skiba et al. (2012) mono-exponential version. The 2015 refinement was specifically developed for, and validated on, optimizing intermittent/repeated-interval training sessions, which is exactly this engine's use case (multi-rep structures with varying recovery), whereas the 2012 original is more general-purpose. Both share the same core mechanics: linear W′ depletion above CP, exponential W′ reconstitution below CP with a time constant dependent on how far below CP the recovery power sits — but they differ substantially in formulation, so the version must be specified, not left as "the Skiba model" generically.
- **Known limitation, documented for transparency:** the Skiba-family models can overestimate sustainable capacity in the severe/extreme intensity domain, occasionally predicting structures that prove "impossible" in practice. Alternative hydraulic (2–3 tank) models exist and outperform work-balance models in some studies. Skiba 2015 is chosen for Phase 1 as the practical, widely-implemented standard; a hydraulic model is noted as a possible future refinement (alongside the 3-parameter hyperbolic CP model, Section 7.2.4), not in scope now.

#### 7.2.1 Acquisition Paths — Three Tiers, All User-Driven

The engine never measures or tests anything itself; it only consumes data the user already has and explicitly provides for that request.

1. **Direct entry.** The user already has CP and W′ from another source (intervals.icu, WKO5, Golden Cheetah, TrainingPeaks, etc.) and provides them directly. No calculation needed.
2. **Multi-effort estimation calculator (linear work-time model).** The user provides ≥2 maximal efforts of different durations, each as `(duration, average power)`. The calculator fits `Work = CP × t + W′` via linear regression — direct two-point solve if exactly 2 efforts are given, least-squares if 3+. This is the standard work-time critical power model (Monod & Scherrer, 1965), widely used for power durations of roughly 3–35 minutes. **No fixed protocol is hardcoded** (e.g., not locked to "3min + 12min") — the engine accepts any number ≥2 of user-supplied efforts of varying duration.
3. **Single 3-minute all-out test calculator.** The user provides power data from one maximal 3-minute all-out effort (at minimum: average power of the final 30 seconds, plus either the full power-time trace or total work for the test). End-test power (EP) — the mean power of the final 30 seconds — serves as the CP estimate; work done above end-test power (WEP) — the power-time integral above EP across the whole test — serves as the W′ estimate. Reference: Vanhatalo, Doust & Burnley (2007).

#### 7.2.2 Data Integrity Checks (not coaching judgment — mathematical validity only)

- Tier 2: efforts must have meaningfully different durations, both within the model's validated range (~2–35 min). Efforts too close together in duration, or outside this range, produce an unreliable fit and must be flagged to the user, never silently accepted.
- Tier 3: the power trace must show the expected decline-then-stabilize pattern. A trace that stays flat or rises indicates the test wasn't a genuine all-out effort; the result must be flagged, never silently used or "corrected."
- A flagged result is surfaced to the user as-is. The engine does not attempt to guess a better value or proceed regardless.

#### 7.2.3 Single Power Anchor — Resolved

There is no scenario in which "FTP" and "CP" are two different numbers for the same request. Whatever power-anchor value the engine has — whether stated directly by the user, or derived via the Tier 2/3 calculator — is the value used both for the W′bal simulation (as CP) and for the displayed `%` output in the Friel/intervals.icu zone tables (labeled "FTP" there only because that is the platform's own convention). This replaces the earlier (incorrect) assumption that these could diverge.

#### 7.2.4 Deferred: Alternative Models

Two more advanced alternatives exist in the literature, both deferred to avoid over-building before Phase 1 validates the simpler approach is sufficient:
- A 3-parameter hyperbolic CP model, offering better accuracy across varied athlete profiles (sprinters vs. time-triallists) and a wider range of effort durations.
- Hydraulic (2–3 tank) models, which have outperformed work-balance models for predicting recovery kinetics from intermittent exercise in some studies.

## 8. Creativity / Anti-Repetition Layer

- Structural patterns (continuous, classic interval, pyramidal, ladder, over/under, progressive, divided/split blocks, etc.) are defined as **parametrized rules in the data schema**, not as a closed list of named workouts. Adding a new pattern later means editing the JSON, not the engine code.
- The engine maintains its **own internal generation log** (SQLite — see Section 17 for the full schema and mechanism). This is the only memory it has.
- The engine **never** queries intervals.icu (or any other platform) to check what the athlete actually executed. Anti-repetition is based solely on the engine's own generation history, not real-world execution data.
- Methodologies explicitly **excluded**: the Norwegian double-threshold method's same-day double-session structure must never be used (single session per day, always).

## 9. Gemini Integration (Creative / Research Layer)

- **Mechanism:** Gemini API (`generate_content` endpoint), called from Python via the official `google-genai` SDK (`google.genai`). Structured proposals are returned via `response_schema` (JSON mode), not via free-text parsing or Anthropic-style tool-use.
- **Model:** configurable via the `WORKOUT_ENGINE_MODEL` environment variable; defaults to `gemini-3.1-pro-preview` (see README for the current-model rationale and Google's deprecation cadence — hardcoded model strings on this API have a short shelf life and must be periodically re-checked against https://ai.google.dev/gemini-api/docs/deprecations).
- **Web search — two-call architecture:** Gemini's `response_schema` (structured output) and the `google_search` grounding tool cannot be combined in a single `generate_content` call on the current API generation (confirmed: `400 INVALID_ARGUMENT`). Because web search here exists to widen **variety, flexibility, creativity, and effectiveness** of generated sessions/progressions — not to fetch facts the model lacks — it is split into two calls, always active:
  1. **Research call** — `google_search` enabled, free-form prose output. Gathers real structural approaches and methodological perspectives relevant to the exact request (zone, mode, duration) that a single default generation would tend not to surface.
  2. **Structure call** — `response_schema` enabled, no tools. Takes the research notes as additional context and returns the validated JSON proposal.
  Both calls use the same model. Python still validates/rebuilds the proposal deterministically regardless of what either call produced.
- **Reliability:** Gemini's creative proposals must be returned via `response_schema` matching the engine's data model — never parsed from free text. Python validates every Gemini-proposed structure against the physiological foundation (Section 7) before accepting it. A rejected proposal is discarded, never silently "fixed" by the engine.
- **Tool-schema description handling:** Gemini's `response_schema` only accepts the JSON Schema `input_schema` shape — it has no concept of a wrapping tool `name`/`description` the way Anthropic tool-use does. Any guidance that lived in a tool schema's top-level `description` (e.g. the bilingual zone-name mapping table) must be folded into `system_instruction` explicitly; the transport layer (`gemini_client.py`, `request_parser.py`) does this automatically for every call.
- This is an optional enhancement layer on top of the deterministic Python core, not a dependency for the engine to function (see `--offline` mode, Section 2).

## 9.5 Data-Layer Architecture (the JSON schema's role)

The project's JSON schema is **lean by design**: it defines the *structure* of the domain and the *hard, inviolable rules*, NOT a table of prescribed physiological values to copy from. Concretely, the JSON holds:

- The fixed Friel zone definitions (Section 4) — these are genuinely fixed, so they belong in data.
- The mandatory session structure rules (Section 11), output grammar constraints (Section 12), the purpose rule and the error checks (Section 17), the RPE derivation rules (Section 6.3), and the request/parameter shape.
- The set of structural-pattern *categories* that are expressible in the intervals.icu grammar (continuous, classic interval, pyramidal, ladder, over/under, progressive, divided/split), defined as parametrized rule-forms — not as fixed value ranges.

The JSON does **not** hold a lookup table of "Tempo = 3–4 reps × 10–20 min, rest 3–5 min." Those concrete physiological values are **reasoned** by the engine (deterministic Python core + the Gemini reasoning/web-search layer), grounded in exercise physiology and methodology the engine investigates live. This keeps the schema faithful to the governing principles: the engine reasons, it does not pick from a menu.

## 9.6 No Pre-Loaded Knowledge Base — Free Reasoning Only (hard architectural rule)

**The engine has NO pre-loaded knowledge base (KB) of methodology, no cached "good examples," no bundled training-source library — and must never acquire one.** This was decided deliberately and is non-negotiable.

The reasoning happens two ways only:
1. The engine's own reasoning from exercise-physiology and methodology principles.
2. **Live web search** (Section 9), used fresh each time to investigate and gather ideas.

**Why no KB (the failure mode this prevents):** any pre-loaded reference — even excellent material from a respected source (e.g. a WKO/TrainingPeaks progression by an expert) — degenerates into exactly what this whole project exists to avoid: a lookup table / menu. Two specific failures:
- It becomes a disguised template: "for Tempo, follow the cached expert example" → predictable, rigid, single-authority output. The KB just becomes the new menu with an expert's signature on it.
- It makes the engine **lazy**: if a ready-made excellent answer is always at hand, the engine stops investigating and reasoning — why think when you can copy? The mere existence of a KB atrophies the intelligence the project is built around.

**Consequence for implementation:** no module, prompt, file, or data store may pre-load methodology examples, progression templates, or curated training-source excerpts as engine input. Expert work (Cusick's WKO progressions, Buchheit/Laursen, Seiler, etc.) may inform the *project's* design thinking and may be *found live via web search* during reasoning, but is never bundled as standing engine knowledge. Reference material that appears in earlier drafts of this spec as "foundation the reasoning layer consults" is superseded by this rule: the reasoning layer consults its own reasoning + live web search, nothing pre-loaded.

**Amendment v2.8 (decision of 2026-10-09).** The rule above stands for methodology examples, progression templates and curated source excerpts: none of those is bundled. One narrow exception was decided deliberately: a list of *arrangements* of the work (`engine/data/shapes.yaml`: "intervals with recovery", "over-unders", "touches on an easy base", and so on), with no intensities, no durations, no examples and no authors, offered to the reasoning layer as ideas it may combine or ignore. The failure this section prevents (a disguised menu that makes the engine lazy) is guarded against by: no default, no quota, no check that a shape was used, an instruction to combine or invent, live web search still run first, and the `WORKOUT_ENGINE_SHAPES=off` switch to remove it. If the engine's output starts to look templated, turn it off.

**Web search is NOT removed by this rule** — it is the opposite of a KB. A KB is static, cached, and copy-prone; web search is live, fresh, and investigative. The engine keeps full web access; it simply has nothing pre-chewed to lean on.

This rule also protects the future-web goal: with no bundled KB, there is no static knowledge asset to port, sync, or keep from going stale — the engine reasons live wherever it runs.

## 10. Trainer/Indoor Context

- The engine generates exclusively for indoor smart trainer use.
- The engine has **no opinion** on ERG mode vs. manual/resistance mode — that decision belongs entirely to the athlete at execution time and is irrelevant to generation logic.
- The athlete's FTP-for-trainer value is taken at face value with no adjustment. No indoor-vs-outdoor physiological correction is applied.
- Rest/recovery segments within a workout always carry an explicit %FTP or %LTHR target — never an undefined "easy" or "coast," since there is no coasting on a trainer.

## 11. Mandatory Session Structure (v2.7)

Every generated session — without exception — has three required parts in this order: **Warmup, Main Set, Cooldown.** The engine never omits any of them.

**v2.7 — designed per session, never a template.** Up to v2.6 the warmup was always an ascending ramp plus a fixed 1–2 min block at 45–55% (60–80% LTHR in HR mode), and the cooldown always a descending ramp or one easy block: the same shape for a 30-minute recovery spin and a two-hour VO2max session. Now the reasoning layer designs the warmup and cooldown for the session in hand, gives the reason (`warmup_cooldown_rationale`), and Python validates and renders them like the main set (`engine/sections.py`). The always-present prep block is gone.

### 11.1 What the reasoning layer is asked to do (criteria, not rules)

- Short sessions: a brief warmup (~5 min) and cooldown (2–3 min), so the time goes to the work.
- Longer and harder sessions: longer warmups and cooldowns; a warmup before hard work may carry short openers.
- Every element has a reason for its shape.

### 11.2 What Python enforces (sanity and arithmetic only)

- A warmup **starts easy** (first value at or below 65% FTP / 80% LTHR) and, in HR mode, **climbs** step by step (heart rate needs each level to settle).
- A cooldown **stays easy** (nothing above 75% FTP / 89% LTHR — the Endurance tops) and **ends easy** (at or below 65% FTP / 80% LTHR).
- **Ramps are power-mode only.** Heart rate lags a changing target, so HR mode writes progressions as steps.
- **A warmup always carries a preparation interval (v2.8).** One step or ramp of 30 s to 2 min (v2.9; 5 min in v2.8), flagged `is_preparation`, that readies the body for the main block; from a 2-minute warmup up it cannot be the whole warmup. What it is (cadence spin-ups, an opener near the first work intensity, a brief build, a gentle lift before a recovery spin) is the coach's design; that it exists is not optional. A cooldown carries none.
- A sanity length: warmup ≤ 25 min, cooldown ≤ 15 min.
- **A length the user asked for is adopted exactly** ("calentamiento de 15 minutos" → the warmup adds up to 900 s); it overrides the sanity length. The request reaches the reasoning layer in the prompt, and a proposal that misses it is rejected with the exact reason and retried.
- The three parts together respect the time budget (Section 15/16).

### 11.3 Shape of a section

A section is a list of elements, the same as the main set plus a ramp:
`step` (duration, low %, high %, optional cadence), `ramp` (duration, from %, to %; power only) and `repeat` (count + steps; never nested).

The offline generator (no reasoning layer) uses a simple ascending ramp/steps warmup and an easy cooldown: 5 and 3 min up to 45-minute sessions, 10 and 5 beyond, or the lengths the user asked for; its placeholder main set is fitted to the remaining time.

### 11.4 RPE and output

**RPE:** every line carries its RPE per the derivation rules in Section 6.3 (midpoint method for flat segments and endpoint-span method for ramps).

**All output strictly follows the Section 12.2 grammar — no placeholders, no descriptive bracket notation, no deviation.** An illustrative power-mode session (every value is one session's choice, none is fixed):

```
# Warmup

- 5m ramp 45-70% [RPE 1-4]

# Main Set

3x
- 8m 83-87% [RPE 3-5]
- 2m 55-60% [RPE 2-4]

# Cooldown

- 3m ramp 65-45% [RPE 1-4]
```

An illustrative HR-mode session (steps only):

```
# Warmup

- 3m 60-68% LTHR [RPE 1-2]
- 3m 68-76% LTHR [RPE 1-2]
- 3m 76-84% LTHR [RPE 2-4]

# Main Set

3x
- 8m 90-93% LTHR [RPE 3-5]
- 3m 70-80% LTHR [RPE 1-2]

# Cooldown

- 5m 65-75% LTHR [RPE 1-2]
```

## 12. Output Artifacts & Export Grammar

### 12.1 Authoring Format — Confirmed: No Narrative Layer

The engine's native `.md` output is written **directly in intervals.icu's exact grammar** (Section 12.2), using Markdown headers only for human-readable organization (`# Warmup`, `# Main Set`, `# Cooldown`). There is no intermediate narrative/descriptive `.md` format and no translation script — the file the engine produces is, line for line, already valid intervals.icu syntax. The export step is a thin wrapper: read the file, send it to the intervals.icu API as-is.

### 12.2 Intervals.icu Workout Builder Syntax — Confirmed Reference

Provided directly by the athlete (`Intervals_Workout_Builder_Syntax.md`). Reproduced here in full as the canonical export grammar.

**Line grammar:** `[duration OR distance] [target] [optional cadence] [RPE]`

**Duration:**
- Hours: `1h` · Minutes: `10m`, `5m` · Seconds: `30s`, `90s` · Combined: `1h2m30s`, `5m30s`
- Distance (not used in this project — trainer/time-based only): `500mtr`, `2km`, `10km`
- ⚠ `m` = minutes, never meters. Meters require `mtr`.

**Targets:**
- Power: bare percentage, e.g. `75%`, `95-105%` — **this project's primary/default target type.**
- Heart rate: `xx% HR` (relative to max HR) or `xx% LTHR` (relative to threshold HR). **This project uses `% LTHR` exclusively** — `% HR` is never used, since the project's HR zones (Section 4.2) are LTHR-anchored, not max-HR-anchored.
- Pace: `xx% Pace` (relative to threshold pace) — **not used in this project** (cycling only, no running pace targets).

**Cadence (optional):** appears after the target, before RPE — e.g. `10m 75% 90rpm`, `12m 85% 90-100rpm`.

**RPE:** appears last on the line, in square brackets — e.g. `[RPE 4-6]`. This is an exact match to this project's RPE formatting rule (Section 6.1) — no translation needed between the two.

**Ramps:** `Xm ramp Y%-Z%` for gradual change, ascending or descending — e.g. `10m ramp 50%-75%`, `3m ramp 60-40%`. Useful for warmup/cooldown and for the "progressive" structural pattern (Section 13) without needing multiple discrete steps.

**Freeride:** `Xm freeride` = ERG off for that segment. Not used in this project (Section 10 — ERG mode is the athlete's concern, not the engine's; freeride implies an undefined/unstructured target, which conflicts with Section 10's rule that every segment always carries an explicit % target).

**Repeats:** two valid forms — a header line (`Main Set 4x`) or a standalone line before the steps (`5x`). **Hard constraints:**
- A blank line is required immediately before and immediately after every repeat block.
- **Nested repeats are not supported by the platform, so the output never has them.** (v2.8) The reasoning layer may place ONE level of sub-repeat inside a repeat block (`4 x [5 x (30s on / 30s off), 4 min easy]`); the engine unrolls the inner repeat into its block before validating, building or rendering, so the file holds a single level. Deeper nesting, and a block that unrolls to more than 80 steps, are rejected.

**Markdown formatting:** standard headers (`#` through `######`) and bold/italic (`**bold**`, `*italic*`) are accepted and ignored by the parser — safe to use for human-readable organization (section titles, notes) without breaking parsing.

### 12.3 Schema Implications

- The data schema's "structural pattern" definitions (Section 8) must distinguish single-level repeat structures from anything that would require nesting. Since v2.8 the proposal contract carries one level of sub-repeat and `flatten_nested_repeats` unrolls it first, so everything downstream of the proposal check (intensity resolution, building, rendering, load) sees only flat blocks.
- Every generated line must resolve to exactly the grammar above: duration → target → [cadence] → `[RPE x-y]`. No segment is ever output without an explicit target, per Section 10.
- **Output validation gate (mandatory pre-export check).** Before any file is written/exported, the engine validates its own output against the project's in-scope grammar and **rejects** (as an internal bug, not a silent pass) any line containing an out-of-scope construct, specifically: distance targets (`mtr`, `km` — this project is time-based only, Section 12.2); `freeride` (out of scope, Section 12.2 / Section 10); `% HR` relative to max HR (must be `% LTHR`, Section 4.3); and `% Pace` (running only, not cycling). The grammar permits these, so "the spec says not to" is not sufficient protection — this gate actively catches the whole class of bugs where such a construct slips into output, before it reaches intervals.icu.
- Minor open detail: the athlete's reference file shows repeat-block step lines both indented (two spaces) and unindented in different examples. Treat indentation as cosmetic unless testing against the real parser shows otherwise.

## 13. Stimulus Categories In Scope

Beyond the seven native Friel zones (Section 4), the following research-grounded structural patterns and modifiers are in scope, to be expressed as combinations of zones rather than as new zones themselves:

- **Threshold (Z4) as its own identity** — distinct from Sweet Spot, not a sub-case of it.
- **Over-Under / Lactate Shuttle** — a structural pattern spanning the Threshold↔Anaerobic boundary, not a zone.
- **Anaerobic Capacity (Z6)** — short (20s–3min) supramaximal glycolytic work.
- **Neuromuscular Power (Z7)** — maximal sprints, <15s, force-velocity/technique focus.
- **Durability** — modeled as a *modifier* (e.g., "this block follows X kJ of prior accumulated work"), never as a standalone zone.
- **Race-demand / surge simulation** — variable-intensity structural pattern reflecting "intermittent endurance event" research, not a zone.
- **Endurance (Z2)** — given full structural detail (continuous, surge-variant, cadence-variant), not left as an afterthought.
- **Recovery (Z1)** — formalized with its own valid structural options for completeness in progression-building.

## 14. Explicitly Out of Scope

- Drills of any kind.
- Same-day double sessions (Norwegian method structure).
- ERG-mode decision-making by the engine.
- Reading actual executed-workout history from intervals.icu or any external platform.
- Any cross-correlation between the Power and HR zone tables.
- Any workout structure not traceable to either the physiological foundation (Section 7.1) or a valid CP/W′ simulation (Section 7.2) when that module is active.

## 15. Progressions — Time-Budget Driven, Engine-Reasoned

When the athlete requests a progression (e.g. "a Tempo progression"), the **driver is the athlete's available training time per session**, not a prescribed week pattern or any single author's recipe. The engine reasons the whole sequence as a **coherent sequence with direction** — it progresses *toward* something, never random disconnected sessions — but *how* it progresses is the engine's own reasoning (free reasoning + live web search, Section 9.6), never an imposed methodology.

### 15.1 The two cases

**Case A — initial duration only.** The athlete gives only a starting session duration (e.g. "Tempo, starting at 30 min/day"). The engine grows the progression from there up to the **physiological ceiling of that stimulus**, which the engine **discovers by live web research** (e.g. "up to how many minutes of Sweet Spot does it make sense to progress?"). The ceiling is not hard-coded and not dictated here — the engine investigates and reasons it. When the ceiling is reached, the engine may note it's time to graduate to the next stimulus.

**Case B — initial duration + maximum duration.** The athlete gives a start and a max (e.g. "Tempo, 30 to 90 min"). The engine develops the ideal load between those two points based on its research/reasoning.

### 15.2 Day-1 sizing example (illustrative, not a rule)

If the athlete has 30 minutes total on Day 1, the engine does **not** spend 10 minutes warming up — that would waste valuable training time in a short session. It might reason ~5 min warmup + ~3 min cooldown, leaving ~22 min, which it could use as (for example) 2×10 min Tempo with 2 min recovery. Every number here is engine-reasoned within the 30-min budget; none is fixed. Warmup/cooldown scale to the budget (Section 11: designed per session; the sanity lengths are limits, not targets).

### 15.3 Coherent direction, engine-reasoned

The only non-negotiable floor is that the sequence be **coherent and directional** — each session a sensible step toward the progression's endpoint. Everything else (whether volume grows, density grows, structure alternates, recovery shrinks, etc.) is the engine's reasoning, informed by live research and its own catalog — **never a fixed methodology imposed by the spec or copied from one authority.**

### 15.4 "Don't reinvent the wheel" — the engine's own catalog

Over time the catalog (Section 17) accumulates the engine's *own* previously-reasoned progressions and sessions. The engine may consult this catalog — its **own memory and library**, not an external authority's KB — to adapt and reuse what it already worked out, rather than reasoning every progression from zero. This is distinct from the forbidden pre-loaded KB (Section 9.6): the catalog is knowledge the engine itself created, not a third party's recipe bundled in.

### 15.5 Anti-repetition interaction

Repetition of zone/stimulus *within* one progression is intentional and exempted from the anti-repetition penalty (Section 17, `progression_id`). The engine still varies session structure across the progression so it is not literally identical step to step — but that variation serves the coherent direction, it does not fight it.

## 16. TSS / IF / Duration Resolution Algorithm

This module exists because the athlete may specify any two of {TSS, IF, duration} (or just TSS/IF for a single session, letting the engine derive duration) and expects the third to be resolved correctly. This area has a documented history of unreliable implementations elsewhere, so the design below is deliberately explicit about both the exact math and the failure modes it is built to avoid.

### 16.1 Session-Level Algebra (exact, no approximation)

`TSS = duration_hours × IF² × 100`

Given any two of {TSS, IF, duration}, the third is solved by direct algebra — e.g., `duration_hours = TSS / (IF² × 100)`. This step is fully deterministic and should never produce a calculation error if implemented correctly; it is simple division/multiplication, not an estimate.

### 16.2 Normalized Power and Work-Segment Intensity Resolution (v2.6)

**How load is computed (power).** The session is expanded to a 1 Hz power stream (a ramp changes linearly second by second), smoothed with a 30-second rolling average (at the very start, the average of the seconds available), raised to the 4th power, averaged, and the 4th root taken. That is Normalized Power, as a fraction of FTP; `IF = NP`, `TSS = hours × IF² × 100`.

**Why this definition.** It is the one Intervals.icu applies to planned workouts. Checked on 2026-10-08 against 85 real planned power workouts from the head coach's Intervals.icu calendars: recomputed here, the load differed from the one Intervals.icu stored by 0.48 TSS on average and 1.4 at most. Two alternatives were measured on the same 85 workouts and rejected:
- the simplified 4th-power average without the rolling window (spec ≤ v2.5): off by up to 58 TSS on short efforts (30/30s, sprints), because the window is what damps them;
- a per-step sum of `hours × IF² × 100`: under-read interval sessions by up to 11 TSS (mean −4%), because it ignores the 4th-power weighting altogether.

The workouts themselves are not stored in this repository (they are athletes' data); the measurement and its numbers are recorded in CHANGELOG v0.5.0.

**Required algorithm order (strict, never simultaneous):**
1. Fix the structure first (rep count, work/rest durations, warmup/cooldown shape) by reasoning from the physiological foundation (Sections 7.1/8) — without reference to TSS/IF at this stage.
2. Only then solve for the one remaining free variable — the work-segment intensity `x` — so that `NP(session(x)) = NP_target`, where `NP_target = IF_target` or `sqrt(TSS_target / (hours × 100))`.

The rolling window makes NP depend on the order of the segments, so the solve runs on the session exactly as it will be assembled (warmup, main set in order with repeats expanded, cooldown). There is no closed form once the window is in the formula; NP rises monotonically with `x`, so the engine solves by bisection to 10⁻⁷.

For structural patterns with more than one distinct work intensity (e.g., over/under), the secondary intensity keeps a fixed ratio to the primary one (the proportions the reasoning layer proposed), so exactly one true degree of freedom remains — never two or more simultaneous unknowns.

### 16.3 Infeasibility Handling (mandatory, not optional)

If the resolved work-segment intensity falls outside the requested zone's valid % range (Section 4.1) or the structural pattern's typical sub-range, this is a **hard infeasibility**, not something to clamp or round silently. The engine must report it explicitly (e.g., the requested TSS/IF cannot be achieved within this zone/duration/structure; report the closest achievable value or ask for an adjusted constraint) rather than ever returning an out-of-range value as if it were valid.

**Conflicting hard constraints (e.g., target TSS vs. maximum available duration).** When the user imposes two hard constraints that cannot both be satisfied — for instance, "TSS 100" together with "maximum 45 min available," where reaching that TSS at any valid intensity for the zone would require more than 45 min — the engine does **not** silently choose which one to sacrifice (that would assume what the athlete prefers, which borders on coaching). It reports the conflict with the concrete numbers (e.g., "TSS 100 requires ~70 min at this zone's intensities; your maximum is 45 min; the highest TSS achievable in 45 min is ~X") and lets the user adjust. This is mathematical conflict detection, not a training judgment — the same report-don't-force principle as the out-of-range case above.

### 16.4 Rounding to intervals.icu Syntax

Resolved values may be fractional (e.g., `4m23.7s @ 88.4%`). The engine **always rounds** these to values valid in the intervals.icu syntax (whole seconds/minutes, integer percentages) — no second-pass fine-tuning, no compensation pass. Keep it simple: resolve, round, done.

After rounding, the engine reports the **real TSS of the rounded workout** (computed from the values actually written to the file), never the original theoretical target. If the user asked for "TSS 80" and the rounded session actually yields 78, the engine reports 78 — the number that corresponds to what will actually be executed. This prevents the silent label-vs-reality mismatch that has historically caused TSS errors in this kind of tool.

The engine's reported TSS is labeled as a **design-time estimate**, not the authoritative figure — the real value is whatever intervals.icu computes on upload (Section 16.2 shows how close the engine's figure is). The engine never presents its TSS as the final official number.

### 16.5 Failure Modes This Design Avoids

Documented as institutional memory, given the project's prior history of errors in this exact area:
- Solving structure and intensity simultaneously as one coupled unknown set, instead of sequencing them (Section 16.2, step order).
- Using a simple average, or a per-step `IF²` sum, instead of the 4th-power-weighted NP (measured: −4% mean, up to −11 TSS on intervals).
- Dropping the 30 s rolling window (measured: up to +58 TSS on short efforts).
- Costing a ramp at its midpoint as if it were flat: the stream follows the ramp.
- Failing to detect and report infeasibility, silently forcing an out-of-range intensity instead.
- Unit/formula errors (hours vs. seconds, % vs. fraction for IF).

**Mandatory before this module is considered complete:** a unit test suite built from hand-calculated reference cases (a constant session; two blocks whose 29 transition seconds are summed by hand; the partial window at the start; a ramp's linear stream) and reconstruction tests (build a session with a known work intensity, take its NP as the target, and the resolver must return that intensity).

### 16.6 HR-Mode Load: HRSS (v2.6)

NP, IF and power-based TSS are power math and do not apply to heart rate. For HR-mode sessions the engine reports **HRSS (normalised TRIMP)**, the method the Intervals.icu workout builder uses for heart-rate workouts:

- Each second's heart rate is the target %LTHR × the athlete's LTHR, in whole bpm (Intervals.icu sums HRSS bpm by bpm, not from the average).
- `HRr = (HR − resting HR) / (max HR − resting HR)`, limited to 0–1.
- `TRIMP per minute = HRr × 0.64 × e^(1.92 × HRr)` (Banister).
- `HRSS = 100 × TRIMP(session) / TRIMP(60 min at LTHR)`: one hour at LTHR is 100, the same scale as TSS.
- The session's reported IF is the equivalent IF from the session algebra (16.1): `IF = sqrt(HRSS / (hours × 100))`.

HRSS needs three values from the athlete (Section 5): LTHR, max HR and resting HR. With all three, this is the formula Intervals.icu applies; it keeps the thresholds of the day a workout was planned, so a later change there moves its number, not the engine's. The check against real planned HR workouts is weaker than for power (2 of 8 reproduced with today's thresholds; CHANGELOG v0.5.0), so HR loads are close, not guaranteed exact. Without them, the engine uses a typical profile (max HR = 1.09 × LTHR, resting HR = 0.37 × LTHR), still gets "one hour at LTHR = 100" exactly, and labels the load **approximate**.

This replaces the v2.4 continuous mapping `IF_eq = 1.5 × (fraction of LTHR) − 0.5`, which had no source in the platform. The mapping is a function of heart rate alone — it does not cross-correlate the Friel power and HR zone tables (Section 4's rule stands).

Same status as the power estimate: a design-time figure; the platform's own computation governs on upload.

## 17. Generation Catalog & Memory (variety through intelligence, not mechanical comparison)

**Core principle — this is the heart of the engine.** Variety and natural progression are NOT produced by a rule engine that compares "signatures" with buckets/thresholds. That approach was explicitly rejected: any fixed bucketing scheme either breaks physiology (e.g. it would wrongly flag `4×10min` → `4×12min30s`, a correct natural progression of small volume increase, as "repetition") or is too coarse/fine to be useful. Instead, the engine **reasons** — the way an expert coach does — grounded in the physiology and methodology it investigates (from the provided books, papers, and web search, Section 9), and informed by its own memory of what it has already produced.

### 17.1 The Catalog (living library + memory)

- **Storage:** SQLite (Python standard library, no extra dependency) — indexed, queryable, fast as it grows.
- The engine records every session/progression it generates into a **catalog**. This catalog serves two purposes at once:
  1. **Memory** — so that, when reasoning about the next session, the engine can read what it has recently produced and decide (intelligently, not by formula) how to add variety or how to continue a progression naturally.
  2. **Reusable library** — sessions accumulate into a growing, valid resource the engine may reconsult and reuse in the future. Building this catalog over time is an explicit, desirable outcome.
- **Each catalog entry is a human- and engine-readable description** of the session — enough for the engine (and a person) to understand what it was. Suggested fields: `id`, `generated_at`, `mode`, `dominant_stimulus` (zone + structural pattern), `complementary_stimuli`, total duration, estimated TSS/IF, the full rendered markdown, and `progression_id` (nullable; links sessions of one multi-week request). This is descriptive metadata, NOT a fingerprint for mechanical equality testing.

### 17.2 How variety actually happens

- When generating, the engine **consults its catalog as context** (alongside its physiological/methodological knowledge and web search) and reasons about what to produce — exactly as it reasons from physiology. There is no algorithm that computes "signature A == signature B → reject." The judgment "is this becoming monotonous?" or "does this progress well?" is made by the engine's intelligence reading its own history plus its knowledge.
- **What the user fixed is sacred:** any parameter the user specified — zone, mode, pattern type, session count — is honored 100% and never altered for variety (a Tempo progression is all Tempo; a power request is all power).
- **Within a progression** (same `progression_id`): the engine builds continuity with physiologically sound, typically small increments (e.g. `4×10min` → `4×12min30s` → `5×10min`). These are *not* treated as "repetition to avoid" — they are the intended natural progression, reasoned from methodology, not pulled from a lookup table.
- **Across unrelated requests:** the engine uses the catalog to avoid handing back effectively the same session with no reason — again by reasoning, not by mechanical match.
- **The requested zone is the session's purpose (v2.8, replaces the dominant/subordinate boundary).** The zone the user asked for must appear in the main set; how much of the work time it takes is the coach's design. Complementary stimuli — open-ended and engine-discovered via methodology + web search, any named pairing only an example — may be touches inside an easy day, surges on a base, a build through several zones, or the larger part of the work. When they outweigh the requested zone the engine reports it as a design note and the reasoning layer says so in the summary; it is never a rejection. A work step may also reach past its named zone (a build, a surge); that too is a note. The complementary zones recorded for a session are derived by the engine from what was built.
- **What still rejects (v2.8).** Errors, not designs: a zone from the other system (power and HR never mix), impossible numbers (above 400% FTP or 120% LTHR), a step called recovery above 85%, the requested zone absent from the main set, a session over its time budget or far under a target duration, a user-fixed length not met, an invalid warmup or cooldown (Section 11.2). Each rejection goes back to the reasoning layer with its exact reason.
- **Shape library (v2.8).** `engine/data/shapes.yaml` lists ways to arrange the work (steady aerobic, aerobic touches, rolling, progressive blocks, sustained effort, classic and progressive intervals, ladders, pyramids, stepped builds, hard-start, over-unders, surges on a base, climb simulation, ramps, sprints, cadence contrast, activation openers, technique drills) and how they chain. It is data with no intensities, offered in the prompt as ideas: no default, no quota, no check that one was used, free to combine or invent. This amends Section 9.6 (see the amendment there): the library is a list of arrangements, not a third party's recipes, examples or numbers, and `WORKOUT_ENGINE_SHAPES=off` removes it from the prompt without any other change.
- **Lookback window:** a configurable recency horizon (default ~21 days) bounds how much recent history the engine weighs as "recent" context. It is an input to the engine's reasoning, not a hard gate.
- **The engine always produces output.** Memory is context for better decisions, never a blocker; it never hangs, errors, or refuses for lack of a "novel enough" option.

## 18. Open Items Requiring Decision Before Implementation

1. **Anti-repetition lookback window default (Section 17)** — confirmed at ~21 days, user-overridable software default, used as reasoning context (not a hard gate).
2. **Sections 16 and 17 — reviewed and confirmed.** Section 17 was reworked away from any mechanical "signature comparison" toward a catalog/memory the engine's intelligence reasons over (the rejected bucketing approach would have broken natural progressions like `4×10min` → `4×12min30s`).
3. **`pattern_signature` (formerly G2) — dissolved, not deferred.** The concept of a mechanical fingerprint for equality testing was removed. The catalog stores descriptive, readable metadata per session (Section 17.1); variety and progression come from the engine reasoning over that catalog plus its physiological/methodological knowledge and web search — not from comparing signatures. No operational "signature definition" is needed.

*No blocking open items remain for the core design.*

---

*This document is the canonical reference for the project going forward. New decisions should be appended here (with a version note) rather than re-discussed from scratch in conversation.*
