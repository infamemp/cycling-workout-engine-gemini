"""
cli.py — Minimal command-line interface (Phase 1).

Runs the deterministic core. `--offline` (default in Phase 1, since no Claude
layer exists yet) generates using the provisional placeholder structure
without any API calls.

Examples:
  python -m engine.cli --mode power --zone Tempo --duration 50 --out tempo.md
  python -m engine.cli --mode hr --zone Tempo --offline --catalog my.sqlite
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .models import GenerationRequest, Athlete
from .generator import generate_single
from .structure import ConstraintConflict
from .catalog import Catalog
from .athlete_settings import load_athlete, SettingsError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workout-engine",
        description="Cycling workout generator (Phase-1 deterministic core).",
    )
    p.add_argument("--mode", choices=["power", "hr"], required=True)
    p.add_argument("--zone", required=True, help="Zone name in the chosen system")
    p.add_argument("--duration", type=int, default=None,
                   help="Target total duration in MINUTES")
    p.add_argument("--max-duration", type=int, default=None,
                   help="Hard max available duration in MINUTES")
    p.add_argument("--warmup", type=int, default=None,
                   help="Warmup length in MINUTES (used exactly)")
    p.add_argument("--cooldown", type=int, default=None,
                   help="Cooldown length in MINUTES (used exactly)")
    p.add_argument("--tss", type=float, default=None, help="Target TSS")
    p.add_argument("--if", dest="intensity_factor", type=float, default=None,
                   help="Target Intensity Factor")
    p.add_argument("--cp", type=float, default=None,
                   help="CP/FTP in watts (internal only; never rendered)")
    p.add_argument("--wprime", type=float, default=None, help="W' in joules")
    p.add_argument("--lthr", type=float, default=None, help="LTHR in bpm")
    p.add_argument("--max-hr", type=float, default=None, help="Max HR in bpm")
    p.add_argument("--rest-hr", type=float, default=None,
                   help="Resting HR in bpm")
    p.add_argument("--athlete", default=None,
                   help="Athlete settings file (default: athlete.yaml if "
                        "present). Command-line values override it.")
    p.add_argument("--seed", type=int, default=None, help="Random seed (repro)")
    p.add_argument("--offline", action="store_true",
                   help="Deterministic core only, no API (Phase-1 default).")
    p.add_argument("--catalog", default=None,
                   help="Path to the SQLite catalog (memory/library).")
    p.add_argument("--out", default=None,
                   help="Write the .md here; otherwise print to stdout.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        base = load_athlete(args.athlete)
    except SettingsError as e:
        print(f"SETTINGS: {e}", file=sys.stderr)
        return 2
    athlete = Athlete(
        cp_watts=args.cp or base.cp_watts,
        w_prime_joules=args.wprime or base.w_prime_joules,
        lthr_bpm=args.lthr or base.lthr_bpm,
        max_hr_bpm=args.max_hr or base.max_hr_bpm,
        resting_hr_bpm=args.rest_hr or base.resting_hr_bpm,
    )

    req = GenerationRequest(
        kind="single_session",
        mode=args.mode,
        requested_zone=args.zone,
        target_duration_seconds=args.duration * 60 if args.duration else None,
        max_available_seconds=args.max_duration * 60 if args.max_duration else None,
        target_tss=args.tss,
        target_if=args.intensity_factor,
        warmup_seconds=args.warmup * 60 if args.warmup else None,
        cooldown_seconds=args.cooldown * 60 if args.cooldown else None,
        athlete=athlete,
    )

    catalog = Catalog(args.catalog) if args.catalog else None
    try:
        sess = generate_single(req, catalog=catalog, seed=args.seed)
    except ConstraintConflict as e:
        print(f"INFEASIBLE: {e.report}", file=sys.stderr)
        return 2
    finally:
        if catalog:
            catalog.close()

    if args.out:
        Path(args.out).write_text(sess.markdown_output, encoding="utf-8")
        approx = " (approximate)" if sess.tss_method == "hrss_typical" else ""
        print(f"Wrote {args.out}  (estimated TSS {sess.estimated_tss}{approx}, "
              f"IF {sess.estimated_if})", file=sys.stderr)
    else:
        print(sess.markdown_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
