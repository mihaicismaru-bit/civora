#!/usr/bin/env python3
"""Regression guard for retiring the applied lifecycle monotonic fixer."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXER = ROOT / "partener-eu" / "ops" / "fix_call_lifecycle_monotonic.py"
RUNTIME = ROOT / "partener-eu" / "ingest" / "build_call_lifecycle.py"
DECISION_PRODUCTS_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-decision-products.yml"
FINAL_CLEANUP_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-final-cleanup-qa.yml"


def load_runtime():
    spec = importlib.util.spec_from_file_location("partener_call_lifecycle_cleanup_test", RUNTIME)
    assert spec and spec.loader, "cannot load lifecycle runtime"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    assert not FIXER.exists(), f"retired one-shot fixer reappeared: {FIXER.relative_to(ROOT)}"

    decision_workflow = DECISION_PRODUCTS_WORKFLOW.read_text(encoding="utf-8")
    assert "fix_call_lifecycle_monotonic.py" not in decision_workflow, (
        "decision-products workflow still references the retired monotonic fixer"
    )

    final_cleanup_workflow = FINAL_CLEANUP_WORKFLOW.read_text(encoding="utf-8")
    assert "test_mipe_lifecycle_monotonic_cleanup.py" in final_cleanup_workflow, (
        "lifecycle monotonic cleanup regression is not wired into the final cleanup gate"
    )

    module = load_runtime()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        decision_path = tmp_path / "decision_products.json"
        mipe_path = tmp_path / "mipe_state.json"
        afir_path = tmp_path / "afir_corpus.json"
        mysmis_path = tmp_path / "mysmis-registry.js"
        previous_path = tmp_path / "call_lifecycle.previous.json"
        out_path = tmp_path / "call_lifecycle.json"
        out_js = tmp_path / "call-lifecycle.js"

        write_json(
            decision_path,
            {
                "generatedAt": "2026-08-27T00:00:00Z",
                "dossiers": [
                    {
                        "id": "TEST-CALL-1",
                        "title": "Apel de test pentru monotonicitate",
                        "programme": "TEST",
                        "code": "TEST-1",
                        "region": "RO",
                        "status": "OPEN",
                        "publicationState": "PUBLISHED",
                        "quality": {"completeness": 1.0},
                        "timeline": [],
                        "sources": [],
                    },
                    {
                        "id": "TEST-CALL-REOPENED",
                        "title": "Apel de test cu termen prelungit oficial",
                        "programme": "TEST",
                        "code": "TEST-2",
                        "region": "RO",
                        "status": "OPEN",
                        "publicationState": "PUBLISHABLE",
                        "quality": {
                            "completeness": 100,
                            "verifiedFactClasses": ["status", "deadline"],
                        },
                        "timeline": [
                            {
                                "date": "2026-08-27",
                                "kind": "DEADLINE_EXTENDED",
                                "text": "Termenul a fost prelungit oficial.",
                            }
                        ],
                        "sources": [],
                    }
                ],
            },
        )
        write_json(mipe_path, {})
        write_json(afir_path, {"items": []})
        mysmis_path.write_text(
            'window.PARTENER_DATA.mysmisRegistry={"status":"UNAVAILABLE","calls":[]};\n',
            encoding="utf-8",
        )
        write_json(
            previous_path,
            {
                "calls": [
                    {
                        "dossierId": "TEST-CALL-1",
                        "stage": "RESULTS",
                        "transitions": [
                            {
                                "observedAt": "2026-08-26T00:00:00Z",
                                "from": "EVALUATION",
                                "to": "RESULTS",
                                "reason": "NEW_OFFICIAL_EVIDENCE",
                            }
                        ],
                    },
                    {
                        "dossierId": "TEST-CALL-REOPENED",
                        "stage": "CLOSED",
                        "transitions": [
                            {
                                "observedAt": "2026-08-25T00:00:00Z",
                                "from": None,
                                "to": "OPEN",
                                "reason": "INITIAL_CANONICAL_PROJECTION",
                            },
                            {
                                "observedAt": "2026-08-26T00:00:00Z",
                                "from": "OPEN",
                                "to": "CLOSED",
                                "reason": "NEW_OFFICIAL_EVIDENCE",
                            },
                        ],
                    }
                ]
            },
        )

        module.DECISION_PATH = decision_path
        module.MIPE_PATH = mipe_path
        module.AFIR_PATH = afir_path
        module.MYSMIS_PATH = mysmis_path
        module.PREVIOUS_PATH = previous_path
        module.OUT_PATH = out_path
        module.OUT_JS = out_js

        assert module.main() == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(payload.get("calls") or []) == 2
        call = next(row for row in payload["calls"] if row["dossierId"] == "TEST-CALL-1")
        assert call["stage"] == "RESULTS", call
        preserved = [
            row
            for row in call.get("stageEvidence") or []
            if row.get("type") == "MONOTONIC_HISTORY_PRESERVED"
        ]
        assert len(preserved) == 1, call.get("stageEvidence")
        assert preserved[0].get("previousStage") == "RESULTS"
        assert preserved[0].get("candidateStage") == "OPEN"
        assert call.get("transitions") == [
            {
                "observedAt": "2026-08-26T00:00:00Z",
                "from": "EVALUATION",
                "to": "RESULTS",
                "reason": "NEW_OFFICIAL_EVIDENCE",
            }
        ], call.get("transitions")

        reopened = next(row for row in payload["calls"] if row["dossierId"] == "TEST-CALL-REOPENED")
        assert reopened["stage"] == "OPEN", reopened
        corrections = [
            row
            for row in reopened.get("stageEvidence") or []
            if row.get("type") == "AUTHORITATIVE_STATUS_CORRECTION"
        ]
        assert len(corrections) == 1, reopened.get("stageEvidence")
        assert not any(
            row.get("type") == "MONOTONIC_HISTORY_PRESERVED"
            for row in reopened.get("stageEvidence") or []
        ), reopened.get("stageEvidence")
        assert reopened.get("transitions") == [
            {
                "observedAt": "2026-08-25T00:00:00Z",
                "from": None,
                "to": "OPEN",
                "reason": "INITIAL_CANONICAL_PROJECTION",
            }
        ], reopened.get("transitions")

    print("PARTENER.EU lifecycle monotonic cleanup regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
