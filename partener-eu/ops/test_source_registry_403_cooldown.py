#!/usr/bin/env python3
"""Hermetic bounded 403 cooldown; no source freshness or OPEN_CALL promotion."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "source_registry_probe",
    ROOT / "partener-eu" / "ingest" / "source_registry_probe.py",
)
probe = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(probe)

source = {
    "id": "SRC-ADR-CENTRU-PR-ACTIONS",
    "url": "https://www.regiocentru.ro/actiuni/",
    "tier": "T1",
    "class": "official_regional_programme_call_registry",
    "authority_scope": "CALL_INDEX_DISCOVERY",
    "material_fact_use": False,
    "source_families": ["ROMANIA", "ADR", "CALL_REGISTRY"],
}
prior = {
    "id": source["id"], "url": source["url"], "health": "FAIL",
    "error": "RuntimeError: all declared official source transports failed: HTTPError: HTTP Error 403: Forbidden",
    "consecutive_failures": 101,
    "last_known_semantic_sha256": "previous-reviewed-hash",
}

assert probe.adr_centre_discovery_403_guard(source, prior)
for tamper_src in (
    {**source, "material_fact_use": True},
    {**source, "authority_scope": "AUTHORITATIVE_CALL"},
    {**source, "url": "https://other.example.invalid/actiuni/"},
    {**source, "id": "SRC-OTHER"},
):
    assert not probe.adr_centre_discovery_403_guard(tamper_src, prior)
for tamper_prev in (
    {**prior, "health": "PASS"},
    {**prior, "consecutive_failures": 99},
    {**prior, "error": "HTTP Error 429: Too Many Requests"},
    {**prior, "url": "https://other.example.invalid/actiuni/"},
):
    assert not probe.adr_centre_discovery_403_guard(source, tamper_prev)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    probe.REGISTRY = root / "registry.json"
    probe.STATE = root / "health.json"
    probe.TASK_DIR = root / "tasks"
    probe.REVIEWED_BASELINES = root / "baselines.json"
    probe.REGISTRY.write_text(json.dumps({"sources": [source]}), encoding="utf-8")
    probe.STATE.write_text(json.dumps({"sources": [prior]}), encoding="utf-8")
    attempts = []

    def denied(_src):
        attempts.append("403")
        raise RuntimeError("all declared official source transports failed: HTTPError: HTTP Error 403: Forbidden")

    probe.fetch_source = denied

    def cycle():
        with contextlib.redirect_stdout(io.StringIO()):
            probe.main()
        observed = json.loads(probe.STATE.read_text(encoding="utf-8"))
        assert observed["summary"]["total"] == 1
        row = observed["sources"][0]
        assert row["health"] == "FAIL" and row["quarantined"] is True
        assert row["ok"] is False
        assert row["publish_material_fact_update"] is False
        assert row["resolution_task_required"] is False
        assert row.get("raw_sha256") is None
        assert row.get("fetched_at") is None
        return row

    first = cycle()
    assert attempts == ["403"]
    assert first["probe_evidence_state"] == "HTTP_403_ATTEMPT_FAILED"
    assert first["cooldown_runs_remaining"] == 5
    assert first["consecutive_failures"] == 102

    for left in (4, 3, 2, 1, 0):
        row = cycle()
        assert attempts == ["403"], "cooldown must avoid duplicate 403 probes"
        assert row["probe_evidence_state"] == "SKIPPED_403_COOLDOWN_NOT_OBSERVED"
        assert row["cooldown_runs_remaining"] == left
        assert row["consecutive_failures"] == 102, "skips are not network failures"
        assert row["last_known_semantic_sha256"] == "previous-reviewed-hash"

    retried = cycle()
    assert attempts == ["403", "403"], "bounded retry must resume"
    assert retried["cooldown_runs_remaining"] == 5
    assert retried["consecutive_failures"] == 103

    # A changed source policy cannot inherit a 403 backoff or skip acquisition.
    authorizing = {**source, "material_fact_use": True}
    probe.REGISTRY.write_text(json.dumps({"sources": [authorizing]}), encoding="utf-8")

    def recovered(_src):
        attempts.append("recovered")
        return {
            "ok": True, "content_quality_ok": True,
            "semantic_sha256": "new-observed-semantic-hash",
            "semantic_chars": 900, "bytes": 1500,
            "selected_url": source["url"], "used_canonical_alias": False,
        }

    probe.fetch_source = recovered
    with contextlib.redirect_stdout(io.StringIO()):
        probe.main()
    recovered_row = json.loads(probe.STATE.read_text(encoding="utf-8"))["sources"][0]
    assert attempts[-1] == "recovered"
    assert recovered_row["health"] == "PASS"
    assert recovered_row["quarantined"] is False
    assert recovered_row.get("cooldown_runs_remaining") is None
    assert recovered_row.get("probe_evidence_state") is None
    assert recovered_row["publish_material_fact_update"] is None

print("PASS ADR Centru bounded 403 retry, FAIL-stale LKG, authority revocation")
