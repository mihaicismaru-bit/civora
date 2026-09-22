#!/usr/bin/env python3
"""Regression tests for the fail-closed AFIR material resolution queue."""

from __future__ import annotations

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
        "snapshotFingerprint": "s" * 64,
        "policy": {
            "publishableDedicatedSnapshot": True,
            "autoPromoteIntoDossierBudget": False,
        },
        "summary": {
            "rowCount": 5,
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
