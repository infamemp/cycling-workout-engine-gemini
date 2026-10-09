"""
intervals_upload.py — send a finished workout to Intervals.icu.

STATUS: ready and tested, NOT used by pedir.py. Nothing in the engine calls
this module. When the time comes, pedir.py (or any script) imports
`upload_workout` and passes a GeneratedSession.

Safe by construction:
  * Dry run is the default. Without confirm=True nothing leaves the machine:
    you get the exact payload that WOULD be sent (and a copy/paste text).
  * The API key is read from the ICU_API_KEY environment variable (the
    athlete id from ICU_ATHLETE_ID, default "0" = the key's own athlete).
    The key is never printed, logged or stored.
  * After a confirmed upload the load Intervals.icu computed is compared with
    the engine's TSS (the same check Infame does). A disagreement is reported
    to the athlete, never hidden.

Intervals.icu API (https://intervals.icu/api/v1, HTTP Basic, user "API_KEY"):
  calendar  POST /athlete/{id}/events/bulk?upsert=true  (category WORKOUT)
  library   POST /athlete/{id}/workouts                 (folder optional)
upsert=true + a deterministic external_id means sending the same session
twice updates it instead of duplicating it.

Standard library only; the HTTP functions are injectable so tests never
touch the network.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Callable, Optional

BASE_URL = "https://intervals.icu/api/v1"
LOAD_TOLERANCE = 0.05            # engine TSS vs Intervals.icu load: 5 %
TARGETS = ("calendar", "library")


class UploadError(Exception):
    """Anything that stops an upload, with a message for the athlete."""


@dataclass
class IntervalsConfig:
    api_key: str
    athlete_id: str = "0"
    base_url: str = BASE_URL

    @classmethod
    def from_env(cls) -> "IntervalsConfig":
        key = os.environ.get("ICU_API_KEY", "").strip()
        if not key:
            raise UploadError(
                "ICU_API_KEY is not set. Intervals.icu → Settings → "
                "Developer Settings → API Key, then set it as an environment "
                "variable. (ICU_ATHLETE_ID is optional; default is your own.)")
        return cls(api_key=key,
                   athlete_id=os.environ.get("ICU_ATHLETE_ID", "0").strip() or "0")


@dataclass
class UploadResult:
    dry_run: bool
    target: str
    payload: dict
    copy_paste: str                       # the workout text, for pasting by hand
    response: Optional[dict] = None
    engine_load: Optional[float] = None
    intervals_load: Optional[float] = None
    load_check: str = "not_checked"       # ok | mismatch | not_available | not_checked
    notes: list = field(default_factory=list)


# --- payload -----------------------------------------------------------------

def external_id(session_id: str, day: str) -> str:
    """Deterministic: the same session on the same day is one calendar item."""
    return f"wge-{day}-{session_id}"


def build_payload(session, *, name: Optional[str] = None,
                  day: Optional[str] = None, target: str = "calendar",
                  folder_id: Optional[int] = None, sport: str = "Ride") -> dict:
    if target not in TARGETS:
        raise UploadError(f"target must be one of {TARGETS}, got {target!r}")
    day = day or _date.today().isoformat()
    try:
        _date.fromisoformat(day)
    except ValueError:
        raise UploadError(f"date must be YYYY-MM-DD, got {day!r}")
    title = (name or session.summary or f"{session.dominant_zone} session").strip()
    payload = {
        "name": title[:120],
        "description": session.markdown_output,
        "type": sport,
        "external_id": external_id(session.id, day),
    }
    if target == "calendar":
        payload.update({"category": "WORKOUT",
                        "start_date_local": f"{day}T00:00:00"})
    elif folder_id is not None:
        payload["folder_id"] = folder_id
    return payload


# --- HTTP (injectable) ----------------------------------------------------------

def _auth_header(cfg: IntervalsConfig) -> dict:
    token = base64.b64encode(f"API_KEY:{cfg.api_key}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json",
            "Accept": "application/json"}


def _http(method: str, url: str, cfg: IntervalsConfig,
          body: Optional[object] = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=_auth_header(cfg))
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode() or "null"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        hint = {401: "the API key was refused", 403: "the key cannot write to "
                "this athlete", 404: "athlete or endpoint not found"}.get(
                    e.code, "Intervals.icu rejected the request")
        raise UploadError(f"Intervals.icu answered HTTP {e.code}: {hint}.")
    except urllib.error.URLError as e:
        raise UploadError(f"could not reach Intervals.icu: {e.reason}")


Post = Callable[[str, IntervalsConfig, object], object]
Get = Callable[[str, IntervalsConfig], object]


def default_post(url, cfg, body):
    return _http("POST", url, cfg, body)


def default_get(url, cfg):
    return _http("GET", url, cfg)


# --- load check ------------------------------------------------------------------

def _load_of(event) -> Optional[float]:
    if not isinstance(event, dict):
        return None
    for key in ("icu_training_load", "training_load"):
        v = event.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def compare_loads(engine_tss: float, intervals_load: Optional[float]):
    if intervals_load is None:
        return "not_available", None
    if engine_tss <= 0:
        return "ok", 0.0
    dev = abs(intervals_load - engine_tss) / engine_tss
    return ("ok" if dev <= LOAD_TOLERANCE else "mismatch"), dev


# --- the one entry point -----------------------------------------------------------

def upload_workout(session, *, name: Optional[str] = None,
                   day: Optional[str] = None, target: str = "calendar",
                   folder_id: Optional[int] = None, confirm: bool = False,
                   config: Optional[IntervalsConfig] = None,
                   post: Optional[Post] = None,
                   get: Optional[Get] = None) -> UploadResult:
    """Prepare (default) or perform (confirm=True) the upload of a session.

    The result always carries `copy_paste`: the workout text, so the athlete
    can paste it into Intervals.icu by hand instead.
    """
    payload = build_payload(session, name=name, day=day, target=target,
                            folder_id=folder_id)
    result = UploadResult(dry_run=not confirm, target=target, payload=payload,
                          copy_paste=session.markdown_output,
                          engine_load=round(session.estimated_tss, 1))
    if not confirm:
        result.notes.append("Dry run: nothing was sent. Call again with "
                            "confirm=True to upload, or paste the text by hand.")
        return result

    cfg = config or IntervalsConfig.from_env()
    post = post or default_post
    get = get or default_get
    athlete = cfg.athlete_id
    if target == "calendar":
        url = f"{cfg.base_url}/athlete/{athlete}/events/bulk?upsert=true"
        resp = post(url, cfg, [payload])
        event = resp[0] if isinstance(resp, list) and resp else resp
    else:
        url = f"{cfg.base_url}/athlete/{athlete}/workouts"
        resp = post(url, cfg, payload)
        event = resp
    result.response = event if isinstance(event, dict) else {"raw": event}

    load = _load_of(event)
    if load is None and target == "calendar":
        # the bulk answer did not carry the load: read the day back
        day_s = payload["start_date_local"][:10]
        try:
            events = get(f"{cfg.base_url}/athlete/{athlete}/events"
                         f"?oldest={day_s}&newest={day_s}", cfg)
        except UploadError as e:
            events = None
            result.notes.append(f"Uploaded, but the load could not be read "
                                f"back: {e}")
        for e in events or []:
            if isinstance(e, dict) and e.get("external_id") == payload["external_id"]:
                load = _load_of(e)
    result.intervals_load = load
    result.load_check, dev = compare_loads(session.estimated_tss, load)
    if result.load_check == "mismatch":
        result.notes.append(
            f"Load differs: engine {session.estimated_tss:.1f} vs "
            f"Intervals.icu {load:.1f} ({dev*100:.0f}%). Check the FTP/LTHR "
            f"in Intervals.icu against the ones used here.")
    elif result.load_check == "not_available":
        result.notes.append("Intervals.icu did not report a load for this "
                            "workout (it may still be calculating).")
    return result
