#!/usr/bin/env python3
"""PRS-051 acceptance: profile asset readiness is distinct from live deployment/readback."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"


def _capability(platform: str, dimension: str) -> str:
    return f"{NAMESPACE}:profile:{platform}:{dimension}"


def main() -> int:
    fb_asset = _capability("facebook", "asset")
    fb_deployment = _capability("facebook", "deployment")
    ig_asset = _capability("instagram", "asset")
    ig_deployment = _capability("instagram", "deployment")

    persisted = [
        {
            "capability_id": fb_asset,
            "instance_id": INSTANCE_ID,
            "persistence_namespace": NAMESPACE,
            "domain": "social_profile",
            "platform": "facebook",
            "profile_dimension": "asset",
            "desired_state": "READY",
            "code_state": "READY",
            "runtime_state": "UNKNOWN",
            "external_state": "UNCONFIRMED",
            "direct_or_outbox": "UNKNOWN",
            "priority": "P1",
        },
        {
            "capability_id": fb_deployment,
            "instance_id": INSTANCE_ID,
            "persistence_namespace": NAMESPACE,
            "domain": "social_profile",
            "platform": "facebook",
            "profile_dimension": "deployment",
            "desired_state": "EXTERNAL_LIVE",
            "code_state": "READY",
            "runtime_state": "DIRECT_NATIVE",
            "external_state": "LIVE_CONFIRMED",
            "direct_or_outbox": "DIRECT",
            "priority": "P1",
        },
        {
            "capability_id": ig_asset,
            "instance_id": INSTANCE_ID,
            "persistence_namespace": NAMESPACE,
            "domain": "social_profile",
            "platform": "instagram",
            "profile_dimension": "asset",
            "desired_state": "READY",
            "code_state": "READY",
            "runtime_state": "UNKNOWN",
            "external_state": "UNCONFIRMED",
            "direct_or_outbox": "UNKNOWN",
            "priority": "P1",
        },
        {
            "capability_id": ig_deployment,
            "instance_id": INSTANCE_ID,
            "persistence_namespace": NAMESPACE,
            "domain": "social_profile",
            "platform": "instagram",
            "profile_dimension": "deployment",
            "desired_state": "EXTERNAL_LIVE",
            "code_state": "READY",
            "runtime_state": "DIRECT_NATIVE",
            "external_state": "UNCONFIRMED",
            "direct_or_outbox": "DIRECT",
            "priority": "P1",
        },
    ]

    repository = {
        fb_asset: {"code_state": "READY", "runtime_state": "UNKNOWN", "evidence": ["brand_pack:facebook_profile_assets"]},
        fb_deployment: {"code_state": "READY", "runtime_state": "DIRECT_NATIVE", "evidence": ["profile_adapter:facebook"]},
        ig_asset: {"code_state": "READY", "runtime_state": "UNKNOWN", "evidence": ["brand_pack:instagram_profile_assets"]},
        ig_deployment: {"code_state": "READY", "runtime_state": "DIRECT_NATIVE", "evidence": ["profile_adapter:instagram"]},
    }
    external = {
        fb_asset: {"external_state": "UNCONFIRMED", "evidence": ["remote_readback:not_required_for_asset"]},
        fb_deployment: {"external_state": "UNCONFIRMED", "evidence": ["remote_profile_readback:absent"]},
        ig_asset: {"external_state": "UNCONFIRMED", "evidence": ["remote_readback:not_required_for_asset"]},
        ig_deployment: {"external_state": "REMOTE_PUBLICATION_EVIDENCE_PRESENT", "evidence": ["remote_profile_readback:verified"]},
    }

    payload = {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
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

    rows = {row["capability_id"]: row for row in result["capabilities"]}
    assert set(rows) == {fb_asset, fb_deployment, ig_asset, ig_deployment}

    for capability_id in rows:
        row = rows[capability_id]
        assert row["instance_id"] == INSTANCE_ID
        assert row["persistence_namespace"] == NAMESPACE
        assert capability_id.startswith(f"{NAMESPACE}:profile:")

    # Local profile assets can be READY independently of any external deployment claim.
    assert rows[fb_asset]["status"] == "IMPLEMENTED"
    assert rows[fb_asset]["code_state"] == "READY"
    assert rows[fb_asset]["external_state"] == "UNCONFIRMED"
    assert rows[fb_asset]["profile_dimension"] == "asset"

    # The same profile's deployment/readback remains separate and fail-closed.
    assert rows[fb_deployment]["status"] == "PARTIAL"
    assert rows[fb_deployment]["external_state"] == "UNCONFIRMED"
    assert rows[fb_deployment]["gap"] == "EXTERNAL_CONFIRMATION_GAP"
    assert rows[fb_deployment]["profile_dimension"] == "deployment"
    assert any(
        item.get("kind") == "FALSE_POSITIVE_PERSISTENCE"
        and item.get("capability_id") == fb_deployment
        and item.get("field") == "external_state"
        for item in result["diagnostics"]
    )

    # Independent remote evidence can promote deployment without changing asset identity/state.
    assert rows[ig_asset]["status"] == "IMPLEMENTED"
    assert rows[ig_deployment]["status"] == "IMPLEMENTED"
    assert rows[ig_deployment]["external_state"] == "REMOTE_PUBLICATION_EVIDENCE_PRESENT"
    assert rows[ig_asset]["profile_dimension"] != rows[ig_deployment]["profile_dimension"]

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-051",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "profile_rows": len(rows),
        "facebook_asset_status": rows[fb_asset]["status"],
        "facebook_deployment_status": rows[fb_deployment]["status"],
        "instagram_deployment_status": rows[ig_deployment]["status"],
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
