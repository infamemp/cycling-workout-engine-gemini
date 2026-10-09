"""
storage.py — Where generated workouts and the catalog live (v0.8.0).

Workouts are saved under `workouts/`, in a subfolder for the session's
INTENTION (what it is for), not dumped in the repository root:

    workouts/
      recovery/  endurance/  tempo/  sub_threshold/  threshold/
      vo2max/    anaerobic/  neuromuscular/
      catalog.sqlite              (the engine's own memory)

A file is named for what it is:
    2026-10-09_power_tempo_45min_382774b5.md

A progression gets one folder, with one file per session:
    workouts/tempo/2026-10-09_power_tempo_progression_prog_ab12cd34/session_01.md

The intention comes from the requested zone, the same classes the shape
library speaks in (shapes.purpose_class). Sweet spot (power) and
SubThreshold (heart rate) both live in `sub_threshold`; an activation or
easy-with-touches session is `endurance`, the zone it was asked for.

Everything here is anchored to the repository folder, so it does not matter
where the command is run from. Set WORKOUT_ENGINE_WORKOUTS to keep the
workouts somewhere else.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

from . import shapes
from . import assembler

REPO_ROOT = Path(__file__).resolve().parents[1]
UNCLASSIFIED = "other"


def workouts_dir() -> Path:
    env = os.getenv("WORKOUT_ENGINE_WORKOUTS", "").strip()
    return Path(env).expanduser() if env else REPO_ROOT / "workouts"


def intention_for(mode: str, zone: str) -> str:
    """The folder a workout belongs in: what it is for."""
    return shapes.purpose_class(mode, zone) or UNCLASSIFIED


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "x"


def _minutes(sess) -> int:
    seconds = (assembler.elements_seconds(sess.warmup)
               + assembler.elements_seconds(sess.main_set)
               + assembler.elements_seconds(sess.cooldown))
    return int(round(seconds / 60.0))


def _date(sess) -> str:
    return str(sess.generated_at)[:10]


def session_filename(sess) -> str:
    return (f"{_date(sess)}_{_slug(sess.mode)}_{_slug(sess.dominant_zone)}_"
            f"{_minutes(sess)}min_{sess.id}.md")


def session_path(sess, base: Optional[Path] = None) -> Path:
    base = Path(base) if base else workouts_dir()
    return base / intention_for(sess.mode, sess.dominant_zone) / session_filename(sess)


def save_session(sess, base: Optional[Path] = None) -> Path:
    path = session_path(sess, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sess.markdown_output, encoding="utf-8")
    return path


def progression_dir(result, base: Optional[Path] = None) -> Path:
    first = result.sessions[0]
    base = Path(base) if base else workouts_dir()
    return (base / intention_for(first.mode, first.dominant_zone)
            / f"{_date(first)}_{_slug(first.mode)}_{_slug(first.dominant_zone)}"
              f"_progression_{result.progression_id}")


def save_progression(result, base: Optional[Path] = None) -> Path:
    """Write each session of a progression into its own folder."""
    folder = progression_dir(result, base)
    folder.mkdir(parents=True, exist_ok=True)
    for i, sess in enumerate(result.sessions, start=1):
        (folder / f"session_{i:02d}.md").write_text(
            sess.markdown_output, encoding="utf-8")
    return folder


def catalog_path(base: Optional[Path] = None) -> Path:
    """The catalog file inside workouts/. A catalog left in the repository
    root by an earlier version (my_catalog.sqlite) is moved there the first
    time, so the engine keeps its memory."""
    base = Path(base) if base else workouts_dir()
    target = base / "catalog.sqlite"
    legacy = REPO_ROOT / "my_catalog.sqlite"
    if not target.exists() and legacy.exists() and base == workouts_dir():
        base.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    base.mkdir(parents=True, exist_ok=True)
    return target


def shown(path: Path) -> str:
    """A path as short as it can be: relative to the repository if inside it."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)
