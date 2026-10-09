"""
athlete_settings.py — The athlete's own thresholds, read from a local file.

The engine's output is always in % of threshold (spec 4.3). The absolute
values are used only inside the engine: the HR-mode load (HRSS needs LTHR,
max HR and resting HR) and, later, the CP/W' model. They live in
`athlete.yaml` at the repository root — personal data, so the file is
git-ignored; `athlete.example.yaml` is the template to copy.

Every field is optional. A missing file or field never blocks a workout:
the engine falls back as each feature documents (e.g. HRSS with a typical
profile, labelled approximate).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import Athlete

DEFAULT_PATH = Path("athlete.yaml")

_FIELDS = {
    "ftp_watts": "cp_watts",
    "w_prime_joules": "w_prime_joules",
    "lthr_bpm": "lthr_bpm",
    "max_hr_bpm": "max_hr_bpm",
    "resting_hr_bpm": "resting_hr_bpm",
}


class SettingsError(ValueError):
    """The settings file exists but cannot be used as written."""


def load_athlete(path: Optional[Path | str] = None) -> Athlete:
    """Read athlete.yaml into an Athlete. No file -> an empty Athlete."""
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return Athlete()
    import yaml  # lazy: only needed when the file exists
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise SettingsError(f"{p} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SettingsError(f"{p} must be a list of 'name: value' lines")
    unknown = sorted(set(data) - set(_FIELDS))
    if unknown:
        raise SettingsError(
            f"{p}: unknown field(s) {unknown}; valid fields: "
            f"{sorted(_FIELDS)}")
    values = {}
    for key, attr in _FIELDS.items():
        v = data.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise SettingsError(f"{p}: {key} must be a positive number, "
                                f"found {v!r}")
        values[attr] = float(v)
    athlete = Athlete(**values)
    if athlete.lthr_bpm and athlete.max_hr_bpm and athlete.resting_hr_bpm \
            and athlete.hr_profile() is None:
        raise SettingsError(
            f"{p}: heart rates must satisfy resting < LTHR < max "
            f"(found {athlete.resting_hr_bpm:g} / {athlete.lthr_bpm:g} / "
            f"{athlete.max_hr_bpm:g})")
    return athlete
