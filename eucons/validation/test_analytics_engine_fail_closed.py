#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "eucons" / "analytics" / "analytics_contract.json").read_text(encoding="utf-8"))
ENGINE_PATH = ROOT / "eucons" / "analytics" / "analytics_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_analytics_failclosed", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load analytics engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = load_engine()
BASE = {
    "product": "EUCONS_COMMERCIAL_OS",
    "event_name": "lead_qualified",
    "occurred_at": "2026-08-19T12:00:00Z",
    "session_id": "c" * 64,
    "properties": {"lead_id": "a" * 64, "lead_score": 82},
    "attribution": {
        "first_touch": {"source": "linkedin", "medium": "social", "landing_path": "/"},
        "last_touch": {"source": "eucons", "medium": "website", "referrer_domain": "eucons.ro", "landing_path": "/evaluare-proiect/"},
    },
}


def must_fail(name: str, payload: dict) -> None:
    try:
        ENGINE.build_event(copy.deepcopy(payload), copy.deepcopy(CONTRACT))
    except ENGINE.AnalyticsError:
        return
    raise SystemExit(f"{name}: analytics engine failed open")


def main() -> None:
    payload = copy.deepcopy(BASE); payload["event_name"] = "unknown"
    must_fail("unknown event", payload)
    payload = copy.deepcopy(BASE); del payload["properties"]["lead_score"]
    must_fail("missing required property", payload)
    payload = copy.deepcopy(BASE); payload["properties"]["email"] = "person@example.invalid"
    must_fail("raw PII key", payload)
    payload = copy.deepcopy(BASE); payload["properties"]["lead_id"] = "lead-123"
    must_fail("non-pseudonymous lead id", payload)
    payload = copy.deepcopy(BASE); payload["session_id"] = "session-raw"
    must_fail("non-pseudonymous session id", payload)
    payload = copy.deepcopy(BASE); payload["properties"]["lead_score"] = 101
    must_fail("invalid lead score", payload)
    payload = copy.deepcopy(BASE); payload["occurred_at"] = "2026-08-19T15:00:00+03:00"
    must_fail("non-UTC timestamp", payload)
    payload = copy.deepcopy(BASE); payload["attribution"]["first_touch"]["landing_path"] = "/?utm_source=linkedin"
    must_fail("query in landing path", payload)
    payload = copy.deepcopy(BASE); payload["attribution"]["last_touch"]["referrer_domain"] = "https://example.com/path"
    must_fail("full referrer URL", payload)
    payload = copy.deepcopy(BASE); payload["properties"]["unexpected"] = "x"
    must_fail("unknown property", payload)
    payload = copy.deepcopy(BASE); payload["attribution"]["first_touch"]["email"] = "person@example.invalid"
    must_fail("PII in attribution", payload)
    payload = copy.deepcopy(BASE); payload["properties"]["message"] = "free text"
    must_fail("free-text message leakage", payload)

    try:
        ENGINE.assert_output_path_safe(ROOT / "eucons" / "analytics" / "runtime-events.json")
    except ENGINE.AnalyticsError:
        pass
    else:
        raise SystemExit("analytics repository runtime-output guard failed open")

    print("EUCONS E20 analytics fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
