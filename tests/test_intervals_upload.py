"""The Intervals.icu upload is ready but unused: these tests prove it is safe
and correct without ever touching the network."""
import pytest

from engine import intervals_upload as up
from engine.models import GenerationRequest
from engine.generator_v2 import generate_single_v2
from test_flex_v070 import prop, step_el


@pytest.fixture
def session():
    p = prop([step_el(1800, 78, 84, "Tempo")], summary="Tempo 30 min")
    return generate_single_v2(GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo"),
        transport=lambda *a: p)


CFG = up.IntervalsConfig(api_key="secret-key", athlete_id="i123")


def boom(*_a, **_k):
    raise AssertionError("the network must not be touched")


def test_dry_run_is_the_default_and_sends_nothing(session):
    r = up.upload_workout(session, day="2026-10-10", post=boom, get=boom)
    assert r.dry_run and r.response is None
    assert r.copy_paste == session.markdown_output
    assert r.payload["category"] == "WORKOUT"
    assert r.payload["start_date_local"] == "2026-10-10T00:00:00"
    assert r.payload["external_id"] == f"wge-2026-10-10-{session.id}"
    assert "secret-key" not in repr(r)


def test_dry_run_needs_no_api_key(session, monkeypatch):
    monkeypatch.delenv("ICU_API_KEY", raising=False)
    assert up.upload_workout(session).dry_run


def test_confirmed_upload_to_calendar_and_load_ok(session):
    calls = []

    def post(url, cfg, body):
        calls.append((url, body))
        return [{"external_id": body[0]["external_id"],
                 "icu_training_load": session.estimated_tss + 0.5}]
    r = up.upload_workout(session, day="2026-10-10", confirm=True,
                          config=CFG, post=post, get=boom)
    assert calls[0][0].endswith("/athlete/i123/events/bulk?upsert=true")
    assert isinstance(calls[0][1], list)
    assert not r.dry_run and r.load_check == "ok"


def test_load_mismatch_is_reported_not_hidden(session):
    r = up.upload_workout(session, day="2026-10-10", confirm=True, config=CFG,
                          post=lambda u, c, b: [{"icu_training_load":
                                                 session.estimated_tss * 1.3}])
    assert r.load_check == "mismatch" and any("Load differs" in n for n in r.notes)


def test_load_read_back_when_the_answer_has_none(session):
    def post(url, cfg, body):
        return [{"external_id": body[0]["external_id"]}]

    def get(url, cfg):
        assert "oldest=2026-10-10" in url
        return [{"external_id": f"wge-2026-10-10-{session.id}",
                 "icu_training_load": session.estimated_tss}]
    r = up.upload_workout(session, day="2026-10-10", confirm=True, config=CFG,
                          post=post, get=get)
    assert r.load_check == "ok"


def test_library_target_posts_to_workouts(session):
    seen = {}

    def post(url, cfg, body):
        seen.update(url=url, body=body)
        return {"id": 9}
    r = up.upload_workout(session, target="library", folder_id=5, confirm=True,
                          config=CFG, post=post)
    assert seen["url"].endswith("/athlete/i123/workouts")
    assert seen["body"]["folder_id"] == 5 and "start_date_local" not in seen["body"]
    assert r.load_check == "not_available"


def test_bad_inputs_and_missing_key(session, monkeypatch):
    with pytest.raises(up.UploadError):
        up.build_payload(session, day="10/10/2026")
    with pytest.raises(up.UploadError):
        up.build_payload(session, target="somewhere")
    monkeypatch.delenv("ICU_API_KEY", raising=False)
    with pytest.raises(up.UploadError, match="ICU_API_KEY"):
        up.upload_workout(session, confirm=True)


def test_auth_header_is_basic_api_key():
    import base64
    h = up._auth_header(CFG)["Authorization"]
    assert base64.b64decode(h.split()[1]).decode() == "API_KEY:secret-key"


def test_pedir_does_not_import_the_uploader():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "pedir.py").read_text()
    assert "intervals_upload" not in src
