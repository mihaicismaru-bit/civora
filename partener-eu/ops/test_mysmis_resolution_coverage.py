#!/usr/bin/env python3
"""Fail-closed regression guard for candidate-scoped MySMIS coverage evidence."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_PATH = ROOT / "partener-eu" / "validation" / "resolution-tasks" / "SRC-MYSMIS-CALLS.json"
CANONICAL_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


task = load(TASK_PATH)
canonical = load(CANONICAL_PATH)
reconciliation = task.get("reconciliation") or {}
calls = canonical.get("calls") or []

assert task.get("source_id") == "SRC-MYSMIS-CALLS"
assert str(task.get("status") or "").startswith("OPEN"), task.get("status")
assert task.get("automatic_material_fact_update_allowed") is False
assert task.get("material_fact_autoupdate_allowed") is False
assert reconciliation.get("classification") == "CONFIRMED_MATERIAL_COVERAGE_DELTA"
assert reconciliation.get("publish_authorized") is False
assert reconciliation.get("candidate_semantic_sha256") == task.get("candidate_semantic_sha256")
assert reconciliation.get("source_url") == task.get("source_url")
assert reconciliation.get("canonical_calls") == len(calls)
assert reconciliation.get("coverage_gap") == (
    reconciliation.get("official_validated_calls") - reconciliation.get("canonical_calls")
)
assert reconciliation.get("coverage_gap") > 0
assert "OPEN-call count" in reconciliation.get("official_inventory_semantics", "")
assert "does not imply" in reconciliation.get("coverage_gap_semantics", "")

blocked = set(task.get("blocked_fact_classes") or [])
reconciliation_blocked = set(reconciliation.get("blocked_fact_classes") or [])
required = {
    "deadline",
    "eligibility",
    "budget",
    "scoring",
    "beneficiaries",
    "material_call_status",
    "other_material_facts",
}
assert required <= blocked
assert required <= reconciliation_blocked

print(
    "PASS MySMIS coverage evidence: "
    f"official_validated={reconciliation['official_validated_calls']} "
    f"canonical={reconciliation['canonical_calls']} "
    f"gap={reconciliation['coverage_gap']} fail_closed=true"
)
