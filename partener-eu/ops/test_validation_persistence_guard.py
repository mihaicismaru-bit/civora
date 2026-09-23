#!/usr/bin/env python3
"""Regression tests for PARTENER.EU validation-state race protection."""

from __future__ import annotations

from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / "partener-eu" / "ops" / "validation_persistence_guard.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "partener-eu-validation.yml"

spec = importlib.util.spec_from_file_location("validation_persistence_guard", GUARD_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_path_classification() -> None:
    relevant = [
        "partener-eu/ingest/state/source_registry_health.json",
        "partener-eu/ingest/state/intelligence_index.json",
        "partener-eu/ingest/intelligence_index.py",
        ".github/workflows/partener-eu-source-registry.yml",
        ".github/workflows/partener-edge-local.yml",
    ]
    safe = [
        "valcea-clar/site/index.html",
        "README.md",
        "partener-eu/validation/latest.json",
        "partener-eu/deployment/pages_latest.json",
        "partener-eu/P10_ACCEPTANCE.json",
    ]
    for path in relevant:
        require(module.is_relevant_partener_drift(path), f"expected relevant drift: {path}")
    for path in safe:
        require(not module.is_relevant_partener_drift(path), f"expected safe drift: {path}")


def test_workflow_ordering_and_guard() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    capture = text.index("name: Capture validation base")
    regenerate = text.index("name: Regenerate canonical data products")
    monitor = text.index("python partener-eu/ops/p10_monitor_integrity.py")
    reconcile = text.index("name: Reconcile canonical intelligence index after monitor evidence")
    acceptance = text.index("name: Synchronize P10 acceptance ledger")
    persistence = text.index("name: Persist validation ledger and safe source corrections")
    retry = text.index("for attempt in 1 2 3 4 5; do", persistence)
    guard = text.index("python partener-eu/ops/validation_persistence_guard.py", retry)
    rebase = text.index("git rebase origin/main", guard)
    guarded_push = text.index("if git push origin HEAD:main; then", rebase)

    require(capture < regenerate, "validation base must be captured before derived products are generated")
    require(monitor < reconcile < acceptance, "intelligence index must be rebuilt after monitor/resolution evidence and before acceptance sync")
    require(persistence < retry < guard < rebase < guarded_push, "every persistence retry must re-fetch, classify drift, rebase safely, then attempt the push")
    require("git pull --rebase origin main" not in text, "unconditional stale-evidence rebase must not return")
    require("main advanced during validation persistence; retrying" in text, "non-fast-forward persistence races must have bounded retry")
    require("Unable to persist validation outputs after five attempts." in text, "retry exhaustion must fail explicitly")
    require("test_validation_persistence_guard.py" in text, "production validation must execute this regression")


def main() -> int:
    test_path_classification()
    test_workflow_ordering_and_guard()
    print("PASS validation persistence guard regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
