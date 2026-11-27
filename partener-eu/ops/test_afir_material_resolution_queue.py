#!/usr/bin/env python3
"""Regression tests for the fail-closed AFIR material resolution queue."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "partener-eu" / "ingest" / "build_afir_material_resolution_queue.py"


def run_builder(corpus: dict, live_funds: dict | None = None) -> tuple[dict, bytes]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        corpus_path = tmp / "afir_corpus.json"
        live_funds_path = tmp / "afir_live_funds.json"
        output_path = tmp / "queue.json"
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        command = [
            sys.executable,
            str(BUILDER),
            "--corpus",
            str(corpus_path),
            "--output",
            str(output_path),
            "--live-funds",
            str(live_funds_path),
        ]
        if live_funds is not None:
            live_funds_path.write_text(json.dumps(live_funds, ensure_ascii=False), encoding="utf-8")
        subprocess.run(command, check=True, capture_output=True, text=True)
        first = output_path.read_bytes()
        payload = json.loads(first)
        subprocess.run(command, check=True, capture_output=True, text=True)
        second = output_path.read_bytes()
        assert first == second, "queue must be byte-deterministic for identical corpus input"
        return payload, second


def main() -> int:
    corpus = {
        "schemaVersion": 2,
        "source": "AFIR",
        "generatedAt": "2026-09-22T16:00:00+00:00",
        "items": [
            {
                "url": "https://afir.ro/unchanged",
                "title": "Unchanged",
                "sha256": "0" * 64,
                "observedAt": "2026-09-22T15:59:00+00:00",
                "materialChangeCandidate": False,
            },
            {
                "url": "https://afir.ro/z-change",
                "title": "Z change",
                "sha256": "2" * 64,
                "observedAt": "2026-09-22T15:59:02+00:00",
                "materialChangeCandidate": True,
            },
            {
                "url": "https://afir.ro/a-change",
                "title": "A change",
                "sha256": "1" * 64,
                "observedAt": "2026-09-22T15:59:01+00:00",
                "materialChangeCandidate": True,
            },
        ],
    }
    payload, _ = run_builder(corpus)

    assert payload["schemaVersion"] == 1
    assert payload["generatedAt"] == corpus["generatedAt"]
    assert payload["policy"]["failClosed"] is True
    assert payload["policy"]["materialFactsAutopromoted"] is False
    assert payload["policy"]["dedicatedStructuredSnapshotsMayResolveExactCandidates"] is True
    assert payload["summary"] == {
        "candidateCount": 2,
        "unresolvedCount": 2,
        "publishableMaterialFactCount": 0,
    }
    assert [row["canonicalUrl"] for row in payload["items"]] == [
        "https://afir.ro/a-change",
        "https://afir.ro/z-change",
    ]
    for row in payload["items"]:
        assert row["status"] == "OPEN"
        assert row["requiresReconciliation"] is True
        assert row["publishMaterialFacts"] is False
        assert row["lastKnownGoodPolicy"] == "PRESERVE_UNTIL_RECONCILED"
        assert "budget" in row["blockedFactClasses"]
        assert "material_call_status" in row["blockedFactClasses"]

    counter_fingerprint = "c" * 64
    counter_corpus = {
        "schemaVersion": 2,
        "source": "AFIR",
        "generatedAt": "2026-09-22T16:29:38+00:00",
        "items": [
            {
                "url": "https://www.afir.ro/finantare/contor-fonduri-disponibile/",
                "title": "Contor fonduri disponibile",
                "sha256": counter_fingerprint,
                "observedAt": "2026-09-22T16:29:26+00:00",
                "materialChangeCandidate": True,
            }
        ],
    }
    rows = [
        {"interventionCode": "DR-14", "sector": "LEGUMICULTURĂ", "availableFundsEur": "100.00"},
        {"interventionCode": "DR-14", "sector": "ZOOTEHNIC", "availableFundsEur": "200.00"},
        {"interventionCode": "DR-14", "sector": "ALTE SECTOARE", "availableFundsEur": "0.00"},
        {"interventionCode": "DR-14", "sector": "ACHIZIȚII SIMPLE", "availableFundsEur": "0.00"},
        {"interventionCode": "DR-18", "sector": "FLORICULTURĂ", "availableFundsEur": "300.00"},
    ]
    snapshot_fingerprint = hashlib.sha256(json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    live_funds = {
        "schemaVersion": 1,
        "source": "AFIR",
        "status": "PASS",
        "canonicalUrl": "https://www.afir.ro/finantare/contor-fonduri-disponibile/",
        "corpusFingerprint": counter_fingerprint,
        "sourceFingerprint": counter_fingerprint,
        "sourceFingerprintMatchesCorpus": True,
        "sourceObservedAt": "2026-09-22T16:29:26+00:00",
        "generatedAt": "2026-09-22T16:29:38+00:00",
        "snapshotFingerprint": snapshot_fingerprint,
        "sourceFingerprintReconciledFromCanonicalLiveFetch": False,
        "rows": rows,
        "provenance": {
            "authority": "AFIR",
            "evidenceType": "OFFICIAL_LIVE_COUNTER",
            "corpusFingerprint": counter_fingerprint,
            "sourceFingerprint": counter_fingerprint,
            "snapshotFingerprint": snapshot_fingerprint,
            "sourceFingerprintMatchesCorpus": True,
            "sourceFingerprintReconciledFromCanonicalLiveFetch": False,
            "sourceObservedAt": "2026-09-22T16:29:26+00:00",
            "corpusObservedAt": "2026-09-22T16:29:26+00:00",
        },
        "policy": {
            "publishableDedicatedSnapshot": True,
            "autoPromoteIntoDossierBudget": False,
            "callStatusInferenceAllowed": False,
            "eligibilityInferenceAllowed": False,
            "scoringInferenceAllowed": False,
        },
        "summary": {
            "rowCount": 5,
            "interventionCount": 2,
            "interventions": ["DR-14", "DR-18"],
        },
    }
    resolved, _ = run_builder(counter_corpus, live_funds)
    assert resolved["summary"] == {
        "candidateCount": 1,
        "unresolvedCount": 0,
        "publishableMaterialFactCount": 0,
    }
    counter = resolved["items"][0]
    assert counter["status"] == "RESOLVED"
    assert counter["requiresReconciliation"] is False
    assert counter["publishMaterialFacts"] is False
    assert counter["materialFactAction"] == "NONE_DOSSIER_FIELDS_REMAIN_BLOCKED"
    assert counter["resolutionType"] == "STRUCTURED_AUTHORITATIVE_LIVE_FUNDS_SNAPSHOT"
    assert counter["dedicatedSnapshotPublishable"] is True
    assert counter["resolutionEvidence"]["sourceFingerprint"] == counter_fingerprint
    assert counter["resolutionEvidence"]["rowCount"] == 5
    assert "budget" in counter["blockedFactClasses"]
    assert "material_call_status" in counter["blockedFactClasses"]

    drifted = dict(live_funds)
    drifted["sourceFingerprint"] = "e" * 64
    drifted["sourceFingerprintMatchesCorpus"] = False
    unresolved, _ = run_builder(counter_corpus, drifted)
    assert unresolved["summary"]["unresolvedCount"] == 1
    assert unresolved["items"][0]["status"] == "OPEN"
    assert unresolved["items"][0]["requiresReconciliation"] is True

    # A PASS label and matching source hash alone must never resolve the queue.
    for name in (
        "missing_rows", "modified_row", "invalid_digest", "wrong_count",
        "wrong_interventions", "wrong_authority", "missing_provenance",
        "wrong_provenance_hash", "duplicate_identity", "malformed_policy",
        "status_inference", "nonofficial_url",
    ):
        bad = copy.deepcopy(live_funds)
        bad_corpus = copy.deepcopy(counter_corpus)
        if name == "missing_rows":
            bad.pop("rows")
        elif name == "modified_row":
            bad["rows"][0]["availableFundsEur"] = "999.00"
        elif name == "invalid_digest":
            bad["snapshotFingerprint"] = bad["provenance"]["snapshotFingerprint"] = "s" * 64
        elif name == "wrong_count":
            bad["summary"]["rowCount"] = 6
        elif name == "wrong_interventions":
            bad["summary"]["interventions"] = ["DR-14"]
        elif name == "wrong_authority":
            bad["provenance"]["authority"] = "OTHER"
        elif name == "missing_provenance":
            bad.pop("provenance")
        elif name == "wrong_provenance_hash":
            bad["provenance"]["sourceFingerprint"] = "e" * 64
        elif name == "duplicate_identity":
            bad["rows"][1]["sector"] = bad["rows"][0]["sector"]
            digest = hashlib.sha256(json.dumps(
                bad["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            bad["snapshotFingerprint"] = bad["provenance"]["snapshotFingerprint"] = digest
        elif name == "malformed_policy":
            bad["policy"] = []
        elif name == "status_inference":
            bad["policy"]["callStatusInferenceAllowed"] = True
        elif name == "nonofficial_url":
            bad["canonicalUrl"] = "https://example.invalid/finantare/contor-fonduri-disponibile/"
            bad_corpus["items"][0]["url"] = bad["canonicalUrl"]
        rejected, _ = run_builder(bad_corpus, bad)
        assert rejected["summary"]["unresolvedCount"] == 1, name
        assert rejected["items"][0]["status"] == "OPEN", name
        assert rejected["items"][0]["publishMaterialFacts"] is False, name

    empty_payload, _ = run_builder({
        "schemaVersion": 2,
        "source": "AFIR",
        "generatedAt": "2026-09-22T16:01:00+00:00",
        "items": [],
    })
    assert empty_payload["summary"]["candidateCount"] == 0
    assert empty_payload["items"] == []

    print("AFIR material resolution queue regression PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
