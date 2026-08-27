#!/usr/bin/env python3
"""Regression guards for retired one-shot decision-product patchers."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DETERMINISM_FIXER = ROOT / "partener-eu" / "ops" / "fix_decision_products_determinism.py"
SOURCE_COVERAGE_FIXER = ROOT / "partener-eu" / "ops" / "fix_decision_products_source_coverage.py"
ROMANIAN_UI_FIXER = ROOT / "partener-eu" / "ops" / "fix_decision_ui_romanian.py"
RUNTIME = ROOT / "partener-eu" / "ingest" / "build_decision_products.py"
UI_RUNTIME = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.js"
DECISION_PRODUCTS_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-decision-products.yml"
FINAL_CLEANUP_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-final-cleanup-qa.yml"
SELF = "test_mipe_decision_products_determinism_cleanup.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("partener_decision_products_cleanup_test", RUNTIME)
    assert spec and spec.loader, "cannot load decision-products runtime"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    for fixer in (DETERMINISM_FIXER, SOURCE_COVERAGE_FIXER, ROMANIAN_UI_FIXER):
        assert not fixer.exists(), f"retired one-shot fixer reappeared: {fixer.relative_to(ROOT)}"

    decision_workflow = DECISION_PRODUCTS_WORKFLOW.read_text(encoding="utf-8")
    assert "fix_decision_products_determinism.py" not in decision_workflow, (
        "decision-products workflow still references the retired determinism fixer"
    )
    assert "fix_decision_products_source_coverage.py" not in decision_workflow, (
        "decision-products workflow still references the retired source-coverage fixer"
    )
    assert "fix_decision_ui_romanian.py" not in decision_workflow, (
        "decision-products workflow still references the retired Romanian UI fixer"
    )
    assert "Apply Romanian UI rules" not in decision_workflow, (
        "decision-products workflow still contains the retired runtime UI patching step"
    )

    final_cleanup_workflow = FINAL_CLEANUP_WORKFLOW.read_text(encoding="utf-8")
    assert SELF in final_cleanup_workflow, (
        "decision-product cleanup regression is not wired into the final cleanup gate"
    )

    runtime_text = RUNTIME.read_text(encoding="utf-8")
    assert "generated_at = stable_generated_at(p11, mipe, afir)" in runtime_text, (
        "decision-products main path no longer derives generatedAt from authoritative snapshots"
    )
    assert "generated_at = utc_now()" not in runtime_text, (
        "wall-clock generatedAt would reintroduce nondeterministic product churn"
    )
    assert 'explicit = str(item.get("pageClass") or "").upper()' in runtime_text, (
        "explicit source pageClass handling disappeared from decision-products runtime"
    )

    ui_text = UI_RUNTIME.read_text(encoding="utf-8")
    for marker in (
        "const eventLabels=",
        "const eventLabel=v=>",
        "const statusLabels=",
        "const statusText=v=>",
        "const fundingFact=f=>",
        "const displayFact=",
        "eventLabel(n.kind)",
    ):
        assert marker in ui_text, f"canonical Romanian UI behavior missing after patcher retirement: {marker}"

    module = load_runtime()

    # Determinism: identical authoritative snapshots must generate an identical timestamp.
    p11 = {"asOf": "2026-08-27T09:15:00+03:00"}
    mipe = {
        "lastRun": {"observedAt": "2026-08-27T06:30:00Z"},
        "observedAt": "invalid",
        "items": [
            {"observedAt": "2026-08-27T06:45:00Z"},
            {"date": "2026-08-27T07:00:00Z"},
        ],
    }
    afir = {
        "observedAt": "2026-08-27T08:30:00+02:00",
        "items": [{"observedAt": "2026-08-27T09:05:00+02:00"}],
    }
    expected = "2026-08-27T07:05:00Z"
    first = module.stable_generated_at(p11, mipe, afir)
    second = module.stable_generated_at(p11, mipe, afir)
    assert first == expected, (first, expected)
    assert second == first, "identical authoritative inputs must produce an identical generatedAt"
    assert module.stable_generated_at({}, {"items": []}, {"items": []}) == "1970-01-01T00:00:00Z"
    assert module.stable_generated_at(
        {"asOf": "not-a-date"},
        {"observedAt": "also-invalid", "items": []},
        {"observedAt": None, "items": []},
    ) == "1970-01-01T00:00:00Z"

    # Source coverage: explicit upstream classification must remain authoritative without patching runtime.
    assert module.afir_page_class({"pageClass": "SESSION", "title": "Acasă"}) == "SESSION"
    assert module.afir_page_class({"pageClass": "DOCUMENT", "title": "Acasă"}) == "DOCUMENT"
    assert module.afir_call_like({"pageClass": "GUIDE", "title": "Acasă"}) is True
    assert module.afir_call_like({"title": "Portal informativ general"}) is False
    assert module.mipe_call_like({"pageClass": "CALL_OR_GUIDE", "title": "Acasă"}) is True
    assert module.mipe_call_like({"pageClass": "INTERVENTION_OR_CALL", "title": "Acasă"}) is True
    assert module.mipe_call_like({"pageClass": "SESSION", "title": "Acasă"}) is True
    assert module.mipe_call_like({"pageClass": "DOCUMENT", "title": "Acasă"}) is False
    assert module.mipe_call_like({"kind": "CALL_OPENED", "title": "Acasă"}) is True
    assert module.mipe_call_like({"title": "Portal informativ general"}) is False

    print("PARTENER.EU decision-product patcher cleanup regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
