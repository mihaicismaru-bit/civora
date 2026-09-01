#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))


def load(name: str):
    path = INGEST / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


watch_mod = load("creative_europe_ft_watch")
handoff = load("creative_europe_ft_competitive_handoff")
exact = load("creative_europe_ft_competitive_exact")

PARENT = "CREA-CULT-2026-PERFORM-EU"
CID = "49521170"
URL = exact.competitive_url(CID)
OPEN = "31094502"
CLOSED = "31094503"

SEARCH = {
    "results": [
        {
            "metadata": {
                "identifier": [PARENT], "callIdentifier": [PARENT], "status": [CLOSED],
                "type": ["1"], "programAbbreviation": ["CREA"], "programmePeriod": ["2021 - 2027"],
                "deadlineDate": ["2026-01-15T00:00:00.000+0000"],
                "esST_URL": ["https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/" + PARENT],
            },
            "content": "Perform EU parent topic",
        },
        {
            "metadata": {
                "identifier": [PARENT], "callIdentifier": [PARENT], "status": [OPEN],
                "type": ["8"], "programAbbreviation": ["CREA"], "programmePeriod": ["2021 - 2027"],
                "deadlineDate": ["2026-10-22T23:59:00.000+0000"], "budget": ["1400000"],
                "esST_URL": [URL],
            },
            "content": "Perform EU", "url": URL,
        },
    ]
}
FACET = {"facets": [{"name": "status", "values": [
    {"rawValue": OPEN, "value": "Open for submission"},
    {"rawValue": CLOSED, "value": "Closed"},
]}]}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = SEARCH
    else:
        payload = FACET if text in {"CREA-", PARENT} else {"facets": []}
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}


def fake_readback(url, *, max_bytes=None, opener=None):
    assert url == URL
    return {"url": url, "final_url": url, "http_status": 200, "content_type": "text/html", "bytes": 64, "body_sha256": "b" * 64, "verified": True}


watch = watch_mod.collect_watch(run_id="watch-current", fetched_at="2026-09-01T09:00:00+00:00", page_size=50, max_pages=1, post_func=fake_post)
linked = watch["linked_competitive_discovery"]
assert len(linked) == 1
assert linked[0]["identity_key"] == f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}"
assert linked[0]["candidate_observation_state"] == "OPEN_CANDIDATE_NON_AUTHORIZING"
assert linked[0]["open_call_authorized"] is False

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    first = handoff.execute_handoff(watch, run_id="competitive-handoff-1", output_dir=root / "run1", history_root=root / "history-empty", post_func=fake_post, readback_func=fake_readback)
    assert first["observation_state"] == handoff.EXECUTED_STATE
    assert first["selection_reason"] == "NEW_ACTIVE_BOUNDED_COMPETITIVE_IDENTITY"
    assert first["selected_identity_key"] == f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}"
    assert first["exact_candidate_observation_state"] == "OPEN_CALL"
    assert first["exact_status_label"] == "Open"
    assert first["exact_semantic_reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert first["material_admission_ready_for_downstream_review"] is True
    assert first["open_call_authorized"] is False
    first_exact = root / "run1" / "current" / "ft-competitive-exact-evidence.json"
    assert first_exact.is_file()

    history_exact_dir = root / "history" / "download-1" / "competitive-handoff" / "current"
    history_exact_dir.mkdir(parents=True)
    history_exact = history_exact_dir / "ft-competitive-exact-evidence.json"
    history_exact.write_text(first_exact.read_text(encoding="utf-8"), encoding="utf-8")

    second = handoff.execute_handoff(watch, run_id="competitive-handoff-2", output_dir=root / "run2", history_root=root / "history", post_func=fake_post, readback_func=fake_readback)
    assert second["observation_state"] == handoff.EXECUTED_STATE
    assert second["selection_reason"] == "ACTIVE_CANDIDATE_FRESHNESS_REFRESH"
    assert second["previous_exact_evidence_sha256"]
    assert second["exact_semantic_reconciliation_state"] == "NO_CHANGE"
    assert second["exact_semantic_change_count"] == 0
    assert second["open_call_authorized"] is False

    changed_watch = copy.deepcopy(watch)
    candidate = changed_watch["linked_competitive_discovery"][0]
    candidate["title_candidate"] = "Perform EU revised discovery title"
    semantic = {key: candidate.get(key) for key in (
        "opportunity_class", "parent_reference", "structured_type", "competitive_call_id_candidate",
        "authority_url_candidate", "structured_url_observed", "status_code", "status_label_candidate",
        "candidate_observation_state", "programme_candidate", "call_identifier_candidate", "deadline_candidate", "title_candidate",
    )}
    candidate["semantic_fingerprint"] = watch_mod.sha256_bytes(watch_mod.canonical_json(semantic))
    selected, reason = handoff.select_candidate(changed_watch, history_root=root / "history")
    assert selected is not None and reason == "ACTIVE_DISCOVERY_SEMANTIC_FINGERPRINT_CHANGED"

opaque_watch = copy.deepcopy(watch)
opaque = opaque_watch["linked_competitive_discovery"][0]
opaque["competitive_call_id_candidate"] = None
opaque["authority_url_candidate"] = None
opaque["structured_url_observed"] = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home"
opaque["identity_key"] = "OPAQUE_TYPE8_RECORD:" + "d" * 64
opaque["semantic_fingerprint"] = "e" * 64
selected, reason = handoff.select_candidate(opaque_watch)
assert selected is None and reason is None

closed_watch = copy.deepcopy(watch)
closed = closed_watch["linked_competitive_discovery"][0]
closed["candidate_observation_state"] = "CLOSED_OBSERVATION_NON_AUTHORIZING"
closed["status_label_candidate"] = "Closed"
semantic = {key: closed.get(key) for key in (
    "opportunity_class", "parent_reference", "structured_type", "competitive_call_id_candidate",
    "authority_url_candidate", "structured_url_observed", "status_code", "status_label_candidate",
    "candidate_observation_state", "programme_candidate", "call_identifier_candidate", "deadline_candidate", "title_candidate",
)}
closed["semantic_fingerprint"] = watch_mod.sha256_bytes(watch_mod.canonical_json(semantic))
selected, reason = handoff.select_candidate(closed_watch)
assert selected is None and reason is None

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    previous_dir = root / "download-old" / "watch"
    previous_dir.mkdir(parents=True)
    previous_watch = copy.deepcopy(watch)
    previous_watch["fetched_at"] = "2026-09-01T08:00:00+00:00"
    previous_watch["run_id"] = "watch-old"
    (previous_dir / "ft-programme-watch-evidence.json").write_text(json.dumps(previous_watch), encoding="utf-8")

    current_without_active = copy.deepcopy(watch)
    current_without_active["fetched_at"] = "2026-09-01T09:00:00+00:00"
    current_without_active["run_id"] = "watch-now"
    current_without_active["linked_competitive_discovery"] = []
    current_without_active["stats"]["linked_competitive_discovery_candidates"] = 0
    current_without_active["stats"]["linked_competitive_parent_references"] = 0
    current_without_active["stats"]["open_linked_competitive_candidates_non_authorizing"] = 0
    selected, reason = handoff.select_candidate(current_without_active, history_root=root)
    assert selected is not None
    assert selected["identity_key"] == f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}"
    assert reason == "PREVIOUS_ACTIVE_DISCOVERY_PENDING_EXACT_RECHECK"

bad_watch = copy.deepcopy(watch)
bad_watch["linked_competitive_discovery"][0]["open_call_authorized"] = True
try:
    handoff.select_candidate(bad_watch)
except ValueError:
    pass
else:
    raise AssertionError("competitive handoff accepted self-authorizing discovery evidence")

print("PASS Creative Europe bounded active competitive handoff + pending replay stays non-authorizing")
__import__("runpy").run_path(str(Path(__file__).with_name("test_creative_europe_ft_competitive_admission.py")), run_name="__main__")
