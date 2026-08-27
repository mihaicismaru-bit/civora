#!/usr/bin/env python3
"""Regression guard for retiring the applied lifecycle result-evidence fixer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXER = ROOT / "partener-eu" / "ops" / "fix_call_lifecycle_result_evidence.py"
RUNTIME = ROOT / "partener-eu" / "ingest" / "build_call_lifecycle.py"
DECISION_PRODUCTS_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-decision-products.yml"
FINAL_CLEANUP_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-final-cleanup-qa.yml"
SELF = "test_mipe_lifecycle_result_evidence_cleanup.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("partener_call_lifecycle_result_evidence_test", RUNTIME)
    assert spec and spec.loader, "cannot load lifecycle runtime"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    assert not FIXER.exists(), f"retired one-shot fixer reappeared: {FIXER.relative_to(ROOT)}"

    decision_workflow = DECISION_PRODUCTS_WORKFLOW.read_text(encoding="utf-8")
    assert "fix_call_lifecycle_result_evidence.py" not in decision_workflow, (
        "decision-products workflow still references the retired result-evidence fixer"
    )

    final_cleanup_workflow = FINAL_CLEANUP_WORKFLOW.read_text(encoding="utf-8")
    assert SELF in final_cleanup_workflow, (
        "result-evidence cleanup regression is not wired into the final cleanup gate"
    )

    module = load_runtime()

    generic_dossier = {
        "id": "AFIR-GENERIC",
        "title": "Investiții agricole pentru tineri fermieri",
        "programme": "AFIR",
        "sourceType": "AFIR_PROVISIONAL",
        "sources": [
            {
                "label": "Evidența oficială beneficiari",
                "url": "https://www.afir.ro/beneficiari",
                "tier": "T1",
            },
            {
                "label": "Ghidul solicitantului",
                "url": "https://www.afir.ro/ghid",
                "tier": "T1",
            },
        ],
    }
    generic_afir = {
        "items": [
            {
                "title": "Beneficiari și contracte",
                "url": "https://www.afir.ro/beneficiari-contracte",
                "documentLinks": [
                    {"name": "Contracte", "url": "https://www.afir.ro/contracte"},
                ],
            }
        ]
    }
    assert module.result_sources(generic_dossier, generic_afir) == [], (
        "generic beneficiary/contract navigation must not become winner evidence"
    )

    explicit_source_dossier = {
        "id": "MIPE-RESULT",
        "title": "Digitalizarea IMM",
        "programme": "PEO",
        "sources": [
            {
                "label": "Lista proiectelor selectate",
                "url": "https://mfe.gov.ro/digitalizare-imm/rezultate",
                "tier": "T1",
                "observedAt": "2026-08-27T00:00:00Z",
            }
        ],
    }
    direct = module.result_sources(explicit_source_dossier, {"items": []})
    assert [row.get("url") for row in direct] == [
        "https://mfe.gov.ro/digitalizare-imm/rezultate"
    ], direct

    explicit_afir = {
        "items": [
            {
                "title": "Lista proiectelor selectate Investiții agricole tineri fermieri",
                "url": "https://www.afir.ro/tineri-fermieri/rezultate",
                "observedAt": "2026-08-27T00:00:00Z",
                "documentLinks": [
                    {
                        "name": "Lista beneficiarilor selectați",
                        "url": "https://www.afir.ro/tineri-fermieri/lista-beneficiari.pdf",
                    }
                ],
            }
        ]
    }
    afir_rows = module.result_sources(generic_dossier, explicit_afir)
    afir_urls = [row.get("url") for row in afir_rows]
    assert "https://www.afir.ro/tineri-fermieri/rezultate" in afir_urls, afir_rows
    assert "https://www.afir.ro/tineri-fermieri/lista-beneficiari.pdf" in afir_urls, afir_rows
    assert len(afir_urls) == len(set(afir_urls)), "result evidence URLs must remain deduplicated"

    print("PARTENER.EU lifecycle result-evidence cleanup regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
