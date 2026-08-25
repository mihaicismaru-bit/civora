#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "prospects" / "client_finder_engine.py"
FIXTURE_PATH = ROOT / "eucons" / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"

spec = importlib.util.spec_from_file_location("client_finder_engine", ENGINE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load Client Finder engine")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    now = payload["reference_time"]
    first = payload["observations"][0]
    second = payload["observations"][1]
    state = engine.empty_state(now)
    state = engine.ingest(state, first["request_id"], first["record"], now)

    changed_replay = deepcopy(first["record"])
    changed_replay["signals"][0]["confidence"] = 0.2
    must_fail("idempotency conflict", lambda: engine.ingest(state, first["request_id"], changed_replay, now))

    non_synthetic = deepcopy(first["record"])
    non_synthetic.pop("synthetic_label")
    must_fail("unauthorized production ingest", lambda: engine.ingest(engine.empty_state(now), "REQ-REAL-001", non_synthetic, now))

    backwards = "2026-08-25T23:00:00+03:00"
    must_fail("reference time rollback", lambda: engine.refresh(state, backwards))

    older_source = deepcopy(second["record"])
    older_source["sources"][0]["retrieved_at"] = "2026-08-26T00:59:00+03:00"
    older_source["signals"][0]["observed_at"] = "2026-08-26T01:11:00+03:00"
    must_fail("older source overwrite", lambda: engine.ingest(state, "REQ-OLDER-SOURCE", older_source, now))

    assertion_overwrite = deepcopy(second["record"])
    assertion_overwrite["assertions"][0]["statement"] = "Changed fact with reused assertion id."
    must_fail("assertion silent overwrite", lambda: engine.ingest(state, "REQ-ASSERTION-OVERWRITE", assertion_overwrite, now))

    suppressed_record = deepcopy(first["record"])
    suppressed_record["suppression"] = {"active": True, "reason": "SYNTHETIC_SUPPRESSION"}
    suppressed_record["updated_at"] = "2026-08-26T01:30:00+03:00"
    suppressed_record["expires_at"] = "2026-09-25T01:30:00+03:00"
    suppressed_record["sources"][0]["retrieved_at"] = "2026-08-26T01:30:00+03:00"
    suppressed_record["sources"][0]["content_hash"] = "d" * 64
    suppressed_record["signals"][0]["observed_at"] = "2026-08-26T01:30:00+03:00"
    suppressed_record["signals"][0]["expires_at"] = "2026-09-25T01:30:00+03:00"
    suppressed_state = engine.ingest(state, "REQ-SUPPRESS", suppressed_record, "2026-08-26T01:30:00+03:00")
    key = engine.VALIDATOR.organization_key(first["record"]["organization"])
    if suppressed_state["records"][key]["state"] != "SUPPRESSED":
        raise AssertionError("suppression did not close prospect")
    must_fail(
        "suppression reactivation",
        lambda: engine.ingest(suppressed_state, second["request_id"], second["record"], "2026-08-26T01:40:00+03:00"),
    )

    unsafe_state = engine.empty_state(now)
    unsafe_state["production_collection_enabled"] = True
    must_fail("production collection boundary", lambda: engine.ingest(unsafe_state, first["request_id"], first["record"], now))

    contact_state = engine.empty_state(now)
    contact_state["external_contact_enabled"] = True
    must_fail("external contact boundary", lambda: engine.ingest(contact_state, first["request_id"], first["record"], now))

    ambiguous = deepcopy(first["record"])
    ambiguous["organization"].pop("public_registration_id")
    ambiguous["organization"].pop("official_domain")
    held = engine.ingest(engine.empty_state(now), "REQ-AMBIGUOUS", ambiguous, now)
    if held["last_result"]["status"] != "HOLD_IDENTITY_AMBIGUOUS" or held["records"]:
        raise AssertionError("ambiguous identity was stored as prospect")

    must_fail(
        "repository runtime output",
        lambda: engine.write_atomic(ROOT / "eucons" / "prospects" / "runtime-state.json", state),
    )

    person = deepcopy(first["record"])
    person["organization"]["person_name"] = "Synthetic Person"
    must_fail("person-level record", lambda: engine.ingest(engine.empty_state(now), "REQ-PERSON", person, now))

    print("PASS: Client Finder engine rejects replay conflicts, stale overwrites, reactivation, PII, repo output and external-action states")


if __name__ == "__main__":
    main()
