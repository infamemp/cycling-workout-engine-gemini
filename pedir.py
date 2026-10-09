"""
pedir.py — Natural-language workout request (front-end command).
Bilingual: Spanish or English, auto-detected from your request.

Usage (from the workout_engine folder):
    python pedir.py "entrenamiento de resistencia aerobica de 1 hora"
    python pedir.py "aerobic endurance workout for 1 hour"
    python pedir.py "una progresion de tempo empezando en 30 minutos"
    python pedir.py "a tempo progression starting at 30 minutes"
    python pedir.py "vo2 max de 45 min por frecuencia cardiaca"
    python pedir.py "vo2 max for 45 min by heart rate"

You write the request in plain language — Spanish or English, either works.
The engine interprets it (zone, duration, power vs HR, single session vs
progression, and which language you used), then generates a real,
validated intervals.icu workout. The result is printed and saved to a .md
file, and all status messages are shown in whichever language you wrote in.
"""

from __future__ import annotations
import sys

from engine.request_parser import parse_request, parse_transport_from_gemini
from engine.gemini_client import gemini_transport
from engine.generator_v2 import generate_single_v2
from engine.generate_progression import generate_progression
from engine.models import GenerationRequest
from engine.catalog import Catalog
from engine.athlete_settings import load_athlete, SettingsError
from engine import storage

# Bilingual UI strings. Keyed by [language]["key"]. Language is auto-detected
# by the parser from the user's own request text (spec: request_parser.py).
_STRINGS = {
    "es": {
        "usage_examples": "Ejemplos:",
        "interpreting": "Interpretando tu peticion...",
        "understood": "  Entendi:",
        "parse_error": "No pude interpretar la peticion:",
        "generating": "Generando... (Gemini esta razonando)",
        "gen_error": "Error al generar:",
        "estimated_tss": "TSS estimado:",
        "saved_to": "Guardado en:",
        "progression_header": "PROGRESION",
        "sessions_word": "sesiones",
        "reasoning": "Razonamiento:",
        "graduation": "Graduacion:",
        "session_word": "Sesion",
        "all_saved_in": "Todas las sesiones guardadas en la carpeta:",
        "load_typical": "(aproximado: faltan LTHR, FC maxima o FC de reposo en athlete.yaml)",
        "settings_error": "Revisa athlete.yaml:",
        "design_notes": "Notas de diseño:",
    },
    "en": {
        "usage_examples": "Examples:",
        "interpreting": "Interpreting your request...",
        "understood": "  Understood:",
        "parse_error": "Could not interpret the request:",
        "generating": "Generating... (Gemini is reasoning)",
        "gen_error": "Error generating workout:",
        "estimated_tss": "Estimated TSS:",
        "saved_to": "Saved to:",
        "progression_header": "PROGRESSION",
        "sessions_word": "sessions",
        "reasoning": "Reasoning:",
        "graduation": "Graduation:",
        "session_word": "Session",
        "all_saved_in": "All sessions saved in folder:",
        "load_typical": "(approximate: LTHR, max HR or resting HR missing in athlete.yaml)",
        "settings_error": "Check athlete.yaml:",
        "design_notes": "Design notes:",
    },
}


def _usage() -> None:
    # Shown before we know the user's language, so show both.
    print('Uso / Usage: python pedir.py "tu peticion / your request"')
    print("Ejemplos / Examples:")
    print('  python pedir.py "resistencia aerobica de 1 hora"')
    print('  python pedir.py "aerobic endurance for 1 hour"')
    print('  python pedir.py "una progresion de tempo empezando en 30 minutos"')
    print('  python pedir.py "a tempo progression starting at 30 minutes"')
    print('  python pedir.py "vo2 max 45 min por frecuencia cardiaca"')
    print('  python pedir.py "vo2 max 45 min by heart rate"')


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        _usage()
        return 1

    text = " ".join(sys.argv[1:]).strip()

    # 1) Interpret the natural-language request (language-agnostic prompt).
    print("Interpretando / Interpreting...")
    parse_t = parse_transport_from_gemini()
    try:
        parsed = parse_request(transport=parse_t, text=text)
    except Exception as e:
        print(f"No pude interpretar la peticion / Could not interpret request: {e}")
        return 2

    lang = parsed.get("language", "es")
    if lang not in _STRINGS:
        lang = "es"
    S = _STRINGS[lang]

    note = parsed.get("interpretation_note", "")
    if note:
        print(f"{S['understood']} {note}")
    print(f"  -> mode={parsed['mode']}, zone={parsed['zone']}, "
          f"kind={parsed['kind']}, lang={lang}")
    print()

    # 2) Build the structured request (thresholds from athlete.yaml, if any).
    try:
        athlete = load_athlete()
    except SettingsError as e:
        print(f"{S['settings_error']} {e}")
        return 2
    dur_min = parsed.get("duration_minutes")
    maxd_min = parsed.get("max_duration_minutes")
    req = GenerationRequest(
        kind=parsed["kind"],
        mode=parsed["mode"],
        requested_zone=parsed["zone"],
        target_duration_seconds=dur_min * 60 if dur_min else None,
        max_available_seconds=maxd_min * 60 if maxd_min else None,
        target_tss=parsed.get("target_tss"),
        target_if=parsed.get("target_if"),
        warmup_seconds=(parsed.get("warmup_minutes") or 0) * 60 or None,
        cooldown_seconds=(parsed.get("cooldown_minutes") or 0) * 60 or None,
        level=parsed.get("level") if parsed.get("level") in
        ("basic", "intermediate", "advanced") else None,
        athlete=athlete,
    )

    catalog = Catalog(str(storage.catalog_path()))
    gen_t = gemini_transport()

    # 3) Generate (single session or full progression).
    print(S["generating"])
    print()
    try:
        if parsed["kind"] == "progression":
            result = generate_progression(
                req, transport=gen_t, catalog=catalog, use_web_search=True,
                initial_session_seconds=req.target_duration_seconds,
            )
            _show_progression(result, S)
        else:
            sess = generate_single_v2(
                req, transport=gen_t, catalog=catalog, use_web_search=True,
            )
            _show_session(sess, S)
    except Exception as e:
        print(f"{S['gen_error']} {e}")
        catalog.close()
        return 3

    catalog.close()
    return 0


def _show_session(sess, S: dict) -> None:
    print(sess.markdown_output)
    print(f"\n{S['estimated_tss']} {sess.estimated_tss}  |  IF: {sess.estimated_if}"
          + (f"  {S['load_typical']}" if sess.tss_method == "hrss_typical" else ""))
    _show_notes(sess, S)
    path = storage.save_session(sess)
    print(f"{S['saved_to']} {storage.shown(path)}")


def _show_notes(sess, S: dict) -> None:
    """Design observations from validation (a step past its zone, most of the
    work outside the requested zone): information for the coach, not errors."""
    notes = getattr(sess, "warnings", None) or []
    if notes:
        print(f"\n{S['design_notes']}")
        for n in notes:
            print(f"  - {n}")


def _show_progression(result, S: dict) -> None:
    print(f"{S['progression_header']} ({len(result.sessions)} {S['sessions_word']})")
    print(f"{S['reasoning']} {result.reasoning}")
    if result.graduation_note:
        print(f"{S['graduation']} {result.graduation_note}")
    print()
    for i, sess in enumerate(result.sessions, start=1):
        approx = " ~" if sess.tss_method == "hrss_typical" else ""
        print(f"--- {S['session_word']} {i}/{len(result.sessions)}  "
              f"(TSS{approx} {sess.estimated_tss}) ---")
        print(sess.markdown_output)
        _show_notes(sess, S)
        print()
    folder = storage.save_progression(result)
    print(f"{S['all_saved_in']} {storage.shown(folder)}")


if __name__ == "__main__":
    raise SystemExit(main())