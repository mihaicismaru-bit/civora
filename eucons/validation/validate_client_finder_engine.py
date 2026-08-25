#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ENGINE_PATH = EUCONS / "prospects" / "client_finder_engine.py"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"


def load_engine():
    spec = importlib.util.spec_from_file_location("client_finder_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load Client Finder engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_engine()
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if payload.get("evidence_label") != "NON_EVIDENCE":
        raise SystemExit("Client Finder fixture evidence label missing")
    reference_time = payload["reference_time"]
    state = engine.empty_state(reference_time)
    for observation in payload["observations"]:
        state = engine.ingest(state, observation["request_id"], observation["record"], reference_time)

    if len(state["records"]) != 2:
        raise SystemExit("organization dedupe failed")
    if len(state["receipts"]) != 3:
        raise SystemExit("idempotency receipt coverage drift")
    if any(record["state"] != "READY_FOR_SCORING" for record in state["records"].values()):
        raise SystemExit("valid synthetic prospects not ready for scoring")
    if any(record.get("synthetic_label") != "NON_EVIDENCE" for record in state["records"].values()):
        raise SystemExit("synthetic record evidence label lost")

    alfa_key = engine.VALIDATOR.organization_key(payload["observations"][0]["record"]["organization"])
    if len(state["source_versions"][alfa_key]["SRC-SYNTH-A"]) != 2:
        raise SystemExit("source version history incomplete")
    if len(state["signal_versions"][alfa_key]["SIGNAL-SYNTH-A"]) != 2:
        raise SystemExit("signal version history incomplete")

    before_events = len(state["events"])
    replay = engine.ingest(state, "REQ-SYNTH-A-002", payload["observations"][1]["record"], reference_time)
    if replay["last_result"]["status"] != "NOOP_REPLAY" or len(replay["events"]) != before_events:
        raise SystemExit("idempotent replay changed state")

    forbidden_event_keys = {
        "legal_name", "organization_name", "person_name", "email", "phone",
        "personal_email", "personal_phone", "official_domain",
    }
    for event in state["events"]:
        if forbidden_event_keys & set(event):
            raise SystemExit("Client Finder event contains identifying field")
        if set(event) - {"event_name", "occurred_at", "organization_key", "state", "reason"}:
            raise SystemExit("Client Finder event schema drift")

    refreshed = engine.refresh(state, "2026-10-01T00:00:00+03:00")
    if any(record["state"] != "HOLD_STALE" for record in refreshed["records"].values()):
        raise SystemExit("expiry refresh failed closed")
    if refreshed["production_collection_enabled"] is not False or refreshed["external_contact_enabled"] is not False:
        raise SystemExit("runtime boundary failed open")

    first = engine.empty_state(reference_time)
    second = engine.empty_state(reference_time)
    for observation in payload["observations"]:
        first = engine.ingest(first, observation["request_id"], observation["record"], reference_time)
        second = engine.ingest(second, observation["request_id"], observation["record"], reference_time)
    if engine.canonical_hash(first) != engine.canonical_hash(second):
        raise SystemExit("Client Finder processing is not deterministic")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "queue.json"
        engine.write_atomic(output, state)
        readback = json.loads(output.read_text(encoding="utf-8"))
        if engine.canonical_hash(readback) != engine.canonical_hash(state):
            raise SystemExit("atomic Client Finder readback drift")

    print(json.dumps({
        "status": "PASS",
        "unit": "R06-CF-ENGINE-001",
        "synthetic_observations": len(payload["observations"]),
        "deduplicated_organizations": len(state["records"]),
        "source_versions_for_updated_organization": 2,
        "signal_versions_for_updated_organization": 2,
        "idempotent_replay": "NOOP",
        "expiry_transition": "HOLD_STALE",
        "production_records": 0,
        "external_contact": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
