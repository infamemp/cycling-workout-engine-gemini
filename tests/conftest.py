"""Test support: mocked Gemini transports return canned proposals.

Canned proposals were written before warmups had to hand over to the main
set. `fit_warmup` adapts the canned warmup's preparation to the first work
step (and lifts HR levels to the floor) so each test can stay about what it
tests. Tests of the handover/floor rules themselves call validate_proposal
directly and are not touched by this.
"""
from __future__ import annotations
import copy
import pytest

from engine import gemini_client
from engine.proposal import _first_work_range, flatten_nested_repeats
from engine.sections import HANDOVER_CAP, HANDOVER_BELOW, HANDOVER_ABOVE, LEVEL_FLOOR, PREP_CEILING


def _fit(prop, mode):
    if not isinstance(prop, dict):
        return prop
    p = copy.deepcopy(prop)
    warm = p.get("warmup")
    if not isinstance(warm, list) or not warm:
        return p
    floor = LEVEL_FLOOR[mode]
    for el in warm:
        if el.get("element") == "step":
            if el["low_pct"] < floor:
                el["low_pct"] = floor
                el["high_pct"] = max(el["high_pct"], floor)
        elif el.get("element") == "ramp":
            el["from_pct"] = max(el["from_pct"], floor)
            el["to_pct"] = max(el["to_pct"], floor)
    if warm[-1].get("is_preparation") and warm[-1].get("element") == "step":
        ceiling = PREP_CEILING[mode]
        if (warm[-1]["low_pct"] + warm[-1]["high_pct"]) / 2 > ceiling:
            lo = max(floor, 50 if mode == "power" else 62)
            warm[-1]["low_pct"], warm[-1]["high_pct"] = lo, lo + 5
    try:
        fw = _first_work_range(flatten_nested_repeats(p))
    except Exception:
        fw = None
    if fw and len(warm) >= 2 and warm[-1].get("is_preparation"):
        build = warm[-2]
        cap = HANDOVER_CAP[mode]
        lo, hi = min(fw[0], cap), min(fw[1], cap)
        if build.get("element") == "ramp":
            level = build["to_pct"]
        elif build.get("element") == "step":
            level = (build["low_pct"] + build["high_pct"]) / 2
        else:
            return p
        if level < lo - HANDOVER_BELOW or level > hi + HANDOVER_ABOVE:
            target = int(hi if level > hi else max(lo - 5, floor))
            if build["element"] == "ramp":
                build["to_pct"] = target
                build["from_pct"] = min(build["from_pct"], target)
            else:
                build["low_pct"], build["high_pct"] = max(target - 4, floor), target
    return p


def _wrap(transport, mode_of):
    def t(system, user, tools, web):
        out = transport(system, user, tools, web)
        mode = mode_of(user)
        if isinstance(out, dict) and isinstance(out.get("sessions"), list):
            out = dict(out, sessions=[_fit(s, mode) for s in out["sessions"]])
        else:
            out = _fit(out, mode)
        return out
    return t


@pytest.fixture(autouse=True)
def _fit_canned_warmups(monkeypatch):
    real_p, real_g = gemini_client.request_proposal, None

    def mode_of(user):
        return "hr" if "Mode: hr" in user else "power"

    def request_proposal(*, transport, **kw):
        return real_p(transport=_wrap(transport, mode_of), **kw)
    monkeypatch.setattr(gemini_client, "request_proposal", request_proposal)
    import engine.generator_v2 as g2
    monkeypatch.setattr(g2, "request_proposal", request_proposal, raising=False)
    if hasattr(gemini_client, "request_progression"):
        real_g = gemini_client.request_progression

        def request_progression(*, transport, **kw):
            return real_g(transport=_wrap(transport, mode_of), **kw)
        monkeypatch.setattr(gemini_client, "request_progression", request_progression)
        import engine.generate_progression as gp
        monkeypatch.setattr(gp, "request_progression", request_progression, raising=False)
