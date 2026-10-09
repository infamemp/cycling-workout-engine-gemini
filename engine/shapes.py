"""
shapes.py — The session-shape library (v0.7.0), loaded from
engine/data/shapes.yaml and offered to the reasoning layer as IDEAS.

The library is data, not code, and it carries no intensities: those come
from the zone tables. It exists so the reasoning layer starts from a wide
range of ways to arrange the work instead of rediscovering the same few,
and it is never a menu: no shape is a default, none has a quota, and the
reasoning layer may combine them or invent its own.

The engine does not pick a shape and does not check that one was used. It
only tells the reasoning layer which ones usually serve the requested
purpose, as a hint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DATA_FILE = Path(__file__).resolve().parent / "data" / "shapes.yaml"

# Requested zone -> the purpose class the library speaks in.
_POWER_CLASS = {
    "ActiveRecovery": "recovery", "Endurance": "endurance", "Tempo": "tempo",
    "SweetSpot": "sub_threshold", "Threshold": "threshold",
    "VO2Max": "vo2max", "Anaerobic": "anaerobic",
    "Neuromuscular": "neuromuscular",
}
_HR_CLASS = {
    "Recovery": "recovery", "Aerobic": "endurance", "Tempo": "tempo",
    "SubThreshold": "sub_threshold", "SuperThreshold": "threshold",
    "AerobicCapacity": "vo2max", "Anaerobic": "anaerobic",
}

_cache: Optional[dict] = None


def load_library(path: Path = DATA_FILE) -> dict:
    """The parsed library; an empty one when the file or PyYAML is missing,
    so a missing library never stops the engine (the prompt just carries
    no list)."""
    global _cache
    if _cache is not None and path == DATA_FILE:
        return _cache
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    lib = {"shapes": list(data.get("shapes") or []),
           "combinations": list(data.get("combinations") or [])}
    if path == DATA_FILE:
        _cache = lib
    return lib


def purpose_class(mode: str, zone: str) -> Optional[str]:
    return (_POWER_CLASS if mode == "power" else _HR_CLASS).get(zone)


def shapes_for(mode: str, zone: str) -> list[str]:
    """Names of the shapes that usually serve this purpose. A hint."""
    cls = purpose_class(mode, zone)
    return [s["name"] for s in load_library()["shapes"]
            if cls in (s.get("suits") or [])]


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def enabled() -> bool:
    """WORKOUT_ENGINE_SHAPES=off removes the library from the prompt (back to
    free reasoning plus live search only), with no other change."""
    return os.getenv("WORKOUT_ENGINE_SHAPES", "on").strip().lower() not in (
        "off", "0", "false", "no")


def prompt_block(mode: str, zone: str) -> str:
    """The shape library as prompt text for this request. Empty when it is
    switched off or cannot be loaded."""
    if not enabled():
        return ""
    lib = load_library()
    shapes = [s for s in lib["shapes"]
              if mode == "power" or s["name"] not in ("single_ramp",
                                                      "descending_ramp")]
    if not shapes:
        return ""
    usual = [n for n in shapes_for(mode, zone)
             if n in {s["name"] for s in shapes}]
    out = ["Ideas for arranging the work. They are NOT a menu: none is the "
           "default, there is no quota, you may combine them or invent your "
           "own, and the order means nothing."]
    if usual:
        out.append("Shapes that often serve this purpose (a hint): "
                   + ", ".join(usual) + ".")
    for s in shapes:
        out.append(f"- {s['name']}: {_one_line(s['idea'])}")
    if lib["combinations"]:
        out.append("Shapes can also chain: " + "; ".join(
            f"{c['name']} ({_one_line(c['idea'])})"
            for c in lib["combinations"]) + ".")
    return "\n".join(out)
