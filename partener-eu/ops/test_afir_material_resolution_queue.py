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


def run_builder(corpus: dict) -> tuple[dict, bytes]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        corpus_path = tmp / "afir_corpus.json"
        output_path = tmp / "queue.json"
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(BUILDER), "--corpus", str(corpus_path), "--output", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        first = output_path.read_bytes()
        payload = json.loads(first)
        subprocess.run(
            [sys.executable, str(BUILDER), "--corpus", str(corpus_path), "--output", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
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
