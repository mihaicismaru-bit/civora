#!/usr/bin/env python3
"""PRS-050 acceptance: persist social capability truth without false LIVE/direct claims."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile


SOCIAL = {
    "facebook": ("DIRECT_NATIVE", "REMOTE_PUBLICATION_EVIDENCE_PRESENT", "DIRECT", "IMPLEMENTED", None),
    "instagram": ("DIRECT_NATIVE", "REMOTE_PUBLICATION_EVIDENCE_PRESENT", "DIRECT", "IMPLEMENTED", None),
    "threads": ("DIRECT_NATIVE_FAIL_CLOSED", "VERIFIED_PUBLISHING_ACCESS_NO_STORY_CLAIM", "DIRECT", "PARTIAL", "EXTERNAL_CONFIRMATION_GAP"),
    "tiktok": ("DIRECT_NATIVE_GATED", "UNPROVEN_EXTERNAL_PUBLICATION", "GATED_DIRECT", "PARTIAL", "DIRECT_EXTERNAL_GATE"),
    "x": ("NO_DIRECT_ADAPTER", "OUTBOX_ONLY", "OUTBOX_ONLY", "PARTIAL", "DIRECT_ADAPTER_OR_ACCESS_GAP"),
    "linkedin": ("DURABLE_OUTBOX_ONLY", "OUTBOX_ONLY", "OUTBOX_ONLY", "PARTIAL", "DIRECT_ADAPTER_OR_ACCESS_GAP"),
    "youtube": ("DURABLE_OUTBOX_ONLY", "OUTBOX_ONLY", "OUTBOX_ONLY", "PARTIAL", "DIRECT_ADAPTER_OR_ACCESS_GAP"),
    "telegram": ("DURABLE_OUTBOX_ONLY", "OUTBOX_ONLY", "OUTBOX_ONLY", "PARTIAL", "DIRECT_ADAPTER_OR_ACCESS_GAP"),
    "whatsapp": ("DURABLE_OUTBOX_ONLY", "OUTBOX_ONLY", "OUTBOX_ONLY", "PARTIAL", "DIRECT_ADAPTER_OR_ACCESS_GAP"),
}


def main() -> int:
    persisted = []
    repository = {}
    external = {}
    for platform, (runtime, external_state, _mode, _status, _gap) in SOCIAL.items():
        capability_id = f"social:{platform}"
        persisted.append({
            "capability_id": capability_id,
            "desired_state": "DIRECT_LIVE",
            "code_state": "READY",
            "runtime_state": runtime,
            "external_state": external_state,
            "direct_or_outbox": "UNKNOWN",
            "priority": "P0",
        })
        repository[capability_id] = {
            "code_state": "READY",
            "runtime_state": runtime,
            "evidence": [f"channel_registry:{platform}"],
        }
        external[capability_id] = {
            "external_state": external_state,
            "evidence": [f"external_state_registry:{platform}"],
        }

    payload = {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {"decisions": [], "capabilities": persisted, "backlog": []},
        "repository": {
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": repository,
        },
        "external": {"decisions": {}, "capabilities": external},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }
    before = deepcopy(payload)
    result = reconcile(payload)
    assert payload == before

    rows = {row["capability_id"].split(":", 1)[1]: row for row in result["capabilities"]}
    assert set(rows) == set(SOCIAL)
    assert len(rows) == 9
    for platform, (_runtime, external_state, mode, status, gap) in SOCIAL.items():
        row = rows[platform]
        assert row["external_state"] == external_state, (platform, row)
        assert row["direct_or_outbox"] == mode, (platform, row)
        assert row["status"] == status, (platform, row)
        assert row["gap"] == gap, (platform, row)

    assert rows["facebook"]["status"] == "IMPLEMENTED"
    assert rows["instagram"]["status"] == "IMPLEMENTED"
    assert rows["threads"]["direct_or_outbox"] == "DIRECT"
    assert rows["threads"]["status"] == "PARTIAL"
    assert rows["tiktok"]["direct_or_outbox"] == "GATED_DIRECT"
    for platform in ("x", "linkedin", "youtube", "telegram", "whatsapp"):
        assert rows[platform]["direct_or_outbox"] == "OUTBOX_ONLY"
        assert rows[platform]["status"] == "PARTIAL"

    # Direct-capable is a runtime property, not a remote publication claim.
    successful_story_publication = {
        platform: rows[platform]["external_state"] == "REMOTE_PUBLICATION_EVIDENCE_PRESENT"
        for platform in SOCIAL
    }
    assert successful_story_publication["facebook"] is True
    assert successful_story_publication["instagram"] is True
    assert successful_story_publication["threads"] is False
    assert successful_story_publication["tiktok"] is False
    assert all(successful_story_publication[p] is False for p in ("x", "linkedin", "youtube", "telegram", "whatsapp"))

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-050",
        "channels": 9,
        "direct_capable": ["facebook", "instagram", "threads"],
        "gated_direct": ["tiktok"],
        "outbox_only": ["x", "linkedin", "youtube", "telegram", "whatsapp"],
        "remote_story_evidence": ["facebook", "instagram"],
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
