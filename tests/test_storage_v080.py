"""
test_storage_v080.py — v0.8.0: generated workouts are filed by intention.

  workouts/<intention>/<date>_<mode>_<zone>_<N>min_<id>.md
  workouts/<intention>/<date>_<mode>_<zone>_progression_<id>/session_NN.md
  workouts/catalog.sqlite

No API key or network needed.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import storage, shapes  # noqa: E402
from engine.generator import generate_single  # noqa: E402
from engine.models import GenerationRequest  # noqa: E402
from engine.zones import POWER_ZONES, HR_ZONES, POWER_SWEETSPOT  # noqa: E402


def _session(mode="power", zone="Tempo", minutes=45, **kw):
    return generate_single(GenerationRequest(
        kind="single_session", mode=mode, requested_zone=zone,
        target_duration_seconds=minutes * 60, **kw), seed=1)


def test_every_zone_has_an_intention_folder():
    for z in POWER_ZONES + (POWER_SWEETSPOT,):
        assert storage.intention_for("power", z.name) != storage.UNCLASSIFIED
    for z in HR_ZONES:
        assert storage.intention_for("hr", z.name) != storage.UNCLASSIFIED
    assert storage.intention_for("power", "Nonsense") == storage.UNCLASSIFIED


def test_sweet_spot_and_hr_subthreshold_share_a_folder():
    assert storage.intention_for("power", "SweetSpot") == "sub_threshold"
    assert storage.intention_for("hr", "SubThreshold") == "sub_threshold"
    assert storage.intention_for("power", "Endurance") == "endurance"
    assert storage.intention_for("hr", "Aerobic") == "endurance"
    assert storage.intention_for("power", "ActiveRecovery") == "recovery"


def test_session_is_filed_under_its_intention_with_a_descriptive_name(tmp_path):
    sess = _session("power", "Tempo", 45)
    path = storage.save_session(sess, tmp_path)
    assert path.parent == tmp_path / "tempo"
    assert path.read_text(encoding="utf-8") == sess.markdown_output
    name = path.name
    assert name.startswith(sess.generated_at[:10] + "_power_tempo_")
    assert name.endswith(f"min_{sess.id}.md") and "_4" in name   # ~45 min


def test_modes_and_zones_land_in_different_folders(tmp_path):
    a = storage.save_session(_session("power", "Threshold", 60), tmp_path)
    b = storage.save_session(_session("hr", "Aerobic", 60), tmp_path)
    c = storage.save_session(_session("power", "ActiveRecovery", 30), tmp_path)
    assert (a.parent.name, b.parent.name, c.parent.name) == (
        "threshold", "endurance", "recovery")
    assert "_hr_aerobic_" in b.name


def test_progression_gets_one_folder_with_numbered_sessions(tmp_path):
    from types import SimpleNamespace
    sessions = [_session("power", "Tempo", 40), _session("power", "Tempo", 50)]
    result = SimpleNamespace(progression_id="prog_ab12cd34", sessions=sessions)
    folder = storage.save_progression(result, tmp_path)
    assert folder.parent == tmp_path / "tempo"
    assert folder.name.endswith("_power_tempo_progression_prog_ab12cd34")
    assert sorted(p.name for p in folder.iterdir()) == [
        "session_01.md", "session_02.md"]


def test_workouts_dir_can_be_moved_with_an_environment_variable(
        tmp_path, monkeypatch):
    monkeypatch.setenv("WORKOUT_ENGINE_WORKOUTS", str(tmp_path / "mine"))
    path = storage.save_session(_session())
    assert (tmp_path / "mine" / "tempo") == path.parent


def test_default_location_is_workouts_in_the_repository(monkeypatch):
    monkeypatch.delenv("WORKOUT_ENGINE_WORKOUTS", raising=False)
    assert storage.workouts_dir() == ROOT / "workouts"


def test_old_catalog_in_the_repo_root_moves_into_workouts(
        tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "my_catalog.sqlite").write_bytes(b"old memory")
    monkeypatch.setattr(storage, "REPO_ROOT", repo)
    monkeypatch.delenv("WORKOUT_ENGINE_WORKOUTS", raising=False)
    target = storage.catalog_path()
    assert target == repo / "workouts" / "catalog.sqlite"
    assert target.read_bytes() == b"old memory"
    assert not (repo / "my_catalog.sqlite").exists()
    # a second call keeps what is there
    assert storage.catalog_path().read_bytes() == b"old memory"


def test_shown_prefers_a_path_relative_to_the_repository():
    p = ROOT / "workouts" / "tempo" / "x.md"
    assert storage.shown(p) in ("workouts/tempo/x.md", "workouts\\tempo\\x.md")


def test_generated_files_are_git_ignored_but_the_folder_readme_is_not():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "workouts/*" in ignore and "!workouts/README.md" in ignore
    assert (ROOT / "workouts" / "README.md").exists()


def test_repository_root_stays_tidy():
    allowed = {".env.example", ".git", ".gitattributes", ".github",
               ".gitignore", ".pytest_cache", "CHANGELOG.md", "README.md",
               "VERSION", "__pycache__", "athlete.example.yaml", "athlete.yaml",
               "docs", "engine", "pedir.py", "requirements.txt", "tests",
               "workouts", ".venv", "venv", ".vscode", ".idea", ".env"}
    extra = {p.name for p in ROOT.iterdir()} - allowed
    # generated leftovers from older versions are ignored by git; anything
    # else in the root is clutter
    extra = {n for n in extra if not (n.startswith("workout_")
                                      or n.startswith("progression_")
                                      or n.endswith(".sqlite"))}
    assert extra == set(), extra
