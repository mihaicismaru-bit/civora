#!/usr/bin/env python3
"""PRS-045 acceptance: implemented adapter plus outbox-only runtime is PARTIAL."""
from __future__ import annotations
import json
from copy import deepcopy
from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

CAP = "C-SOCIAL-OUTBOX"

def main() -> int:
    payload = {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "decisions": [],
            "capabilities": [{
                "capability_id": CAP,
                "desired_state": "DIRECT_LIVE",
                "code_state": "READY",
                "runtime_state": "DIRECT",
                "external_state": "CONFIRMED",
                "direct_or_outbox": "DIRECT",
                "priority": "P0",
            }],
            "backlog": [],
        },
        "repository": {
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": {CAP: {
                "code_state": "READY",
                "runtime_state": "DURABLE_OUTBOX_ONLY",
                "evidence": ["adapter:implemented", "runtime:outbox-only"],
            }},
        },
        "external": {"decisions": {}, "capabilities": {CAP: {"external_state": "OUTBOX_ONLY"}}},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }
    before = deepcopy(payload)
    result = reconcile(payload)
    assert payload == before
    row = next(x for x in result["capabilities"] if x["capability_id"] == CAP)
    assert row["code_state"] == "READY"
    assert row["status"] == "PARTIAL"
    assert row["direct_or_outbox"] == "OUTBOX_ONLY"
    assert row["gap"] == "DIRECT_ADAPTER_OR_ACCESS_GAP"
    direct_publication = row["status"] == "IMPLEMENTED" and row["direct_or_outbox"] == "DIRECT"
    assert direct_publication is False
    assert any(x.get("kind") == "FALSE_POSITIVE_PERSISTENCE" and x.get("capability_id") == CAP and x.get("field") == "direct_or_outbox" for x in result["diagnostics"])
    assert result["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"
    print(json.dumps({"status":"PASS","prs":"PRS-045","capability_status":row["status"],"direct_publication":direct_publication,"direct_or_outbox":row["direct_or_outbox"],"gap":row["gap"],"repository_input_unchanged":True}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
