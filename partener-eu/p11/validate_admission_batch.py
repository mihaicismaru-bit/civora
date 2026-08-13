#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re

from opportunity_contract import MATERIAL_FACT_CLASSES, validate_bundle

ROOT = pathlib.Path(__file__).resolve().parent
EXPECTED_BATCH_SIZES = {
    "P11-I04-B01": 5,
    "P11-I04-B02": 5,
    "P11-I04-B03": 5,
    "P11-I04-B04": 4,
}
TARGET_CANONICAL_OPPORTUNITIES = 25


def explicitly_resolved_admission_ids() -> set[str]:
    result: set[str] = set()
    for path in sorted((ROOT / "resolutions").glob("*_resolution.json")):
        resolution = json.loads(path.read_text(encoding="utf-8"))
        resolved_tasks = {
            row["opportunity_id"]
            for row in resolution.get("resolution_tasks", [])
            if row.get("status") == "RESOLVED"
        }
        result.update(
            row["opportunity_id"]
            for row in resolution.get("opportunities", [])
            if row.get("publication_state") == "PUBLISHABLE"
            and row["opportunity_id"] in resolved_tasks
        )
    return result


def main() -> int:
    bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))
    validate_bundle(bundle)
    batches = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(ROOT.glob("admission_batch_*.json"))]
    ids = [opportunity_id for batch in batches for opportunity_id in batch["opportunity_ids"]]
    if {batch["batch_id"] for batch in batches} != set(EXPECTED_BATCH_SIZES):
        raise SystemExit("admission manifest set must exactly cover P11-I04-B01 through P11-I04-B04")
    if len(ids) != len(set(ids)):
        raise SystemExit("opportunity IDs must be unique across admission batches")
    for batch in batches:
        batch_ids = batch["opportunity_ids"]
        expected_size = EXPECTED_BATCH_SIZES[batch["batch_id"]]
        if len(batch_ids) != expected_size or len(set(batch_ids)) != len(batch_ids):
            raise SystemExit(f"{batch['batch_id']} must contain exactly {expected_size} unique opportunity IDs")
        if batch.get("publication_allowed") is not False or batch.get("automatic_material_fact_update_allowed") is not False:
            raise SystemExit(f"{batch['batch_id']} admission must be fail-closed")
        for artifact in batch.get("source_artifacts") or []:
            if not artifact.get("path") or not re.fullmatch(r"[0-9a-f]{40}", artifact.get("blob_sha", "")):
                raise SystemExit("source artifact must have a path and pinned Git blob SHA")

    opportunities = {row["opportunity_id"]: row for row in bundle["opportunities"]}
    if len(opportunities) < TARGET_CANONICAL_OPPORTUNITIES:
        raise SystemExit(f"canonical corpus must contain at least {TARGET_CANONICAL_OPPORTUNITIES} opportunities")
    evidence = {row["evidence_id"]: row for row in bundle["evidence"]}
    resolved_admissions = set(ids) & explicitly_resolved_admission_ids()
    open_blocks = {
        row["opportunity_id"]: set(row["blocked_fact_classes"])
        for row in bundle["resolution_tasks"]
        if row["status"] in {"OPEN", "IN_REVIEW"}
    }
    for opportunity_id in ids:
        item = opportunities[opportunity_id]
        if opportunity_id in resolved_admissions:
            if item["publication_state"] != "PUBLISHABLE" or item.get("candidate_material_facts"):
                raise SystemExit(f"resolved admission is not explicitly publishable: {opportunity_id}")
            continue
        if item["status"] != "DISCOVERED" or item["publication_state"] != "REVIEW_REQUIRED":
            raise SystemExit(f"admitted opportunity is not fail-closed: {opportunity_id}")
        if item.get("material_facts") or item.get("fact_evidence"):
            raise SystemExit(f"admitted opportunity promotes material facts: {opportunity_id}")
        refs = item.get("evidence_refs") or []
        if not refs or any(evidence[ref]["semantic_verdict"] != "UNRESOLVED" for ref in refs):
            raise SystemExit(f"admitted evidence must remain semantically unresolved: {opportunity_id}")
        if any(evidence[ref].get("supports_fact_classes") for ref in refs):
            raise SystemExit(f"admitted evidence must support no material facts: {opportunity_id}")
        candidates = set((item.get("candidate_material_facts") or {}).keys())
        if candidates != MATERIAL_FACT_CLASSES or not candidates <= open_blocks.get(opportunity_id, set()):
            raise SystemExit(f"admitted candidate facts are not fully blocked: {opportunity_id}")
    print(json.dumps({
        "batches": [batch["batch_id"] for batch in batches],
        "admitted": len(ids),
        "explicitly_resolved_overlays": len(resolved_admissions),
        "unresolved_admissions": len(ids) - len(resolved_admissions),
        "admission_material_fact_action": "NONE",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
