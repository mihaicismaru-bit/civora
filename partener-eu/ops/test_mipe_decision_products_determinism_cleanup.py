#!/usr/bin/env python3
"""Regression guard for retiring the applied decision-product determinism fixer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXER = ROOT / "partener-eu" / "ops" / "fix_decision_products_determinism.py"
RUNTIME = ROOT / "partener-eu" / "ingest" / "build_decision_products.py"
DECISION_PRODUCTS_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-decision-products.yml"
FINAL_CLEANUP_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-final-cleanup-qa.yml"
SELF = "test_mipe_decision_products_determinism_cleanup.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("partener_decision_products_determinism_test", RUNTIME)
    assert spec and spec.loader, "cannot load decision-products runtime"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    assert not FIXER.exists(), f"retired one-shot fixer reappeared: {FIXER.relative_to(ROOT)}"

    decision_workflow = DECISION_PRODUCTS_WORKFLOW.read_text(encoding="utf-8")
    assert "fix_decision_products_determinism.py" not in decision_workflow, (
        "decision-products workflow still references the retired determinism fixer"
    )

    final_cleanup_workflow = FINAL_CLEANUP_WORKFLOW.read_text(encoding="utf-8")
    assert SELF in final_cleanup_workflow, (
        "decision-product determinism cleanup regression is not wired into the final cleanup gate"
    )

    runtime_text = RUNTIME.read_text(encoding="utf-8")
    assert "generated_at = stable_generated_at(p11, mipe, afir)" in runtime_text, (
        "decision-products main path no longer derives generatedAt from authoritative snapshots"
    )
    assert "generated_at = utc_now()" not in runtime_text, (
        "wall-clock generatedAt would reintroduce nondeterministic product churn"
    )

    module = load_runtime()
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

    print("PARTENER.EU decision-product determinism cleanup regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
