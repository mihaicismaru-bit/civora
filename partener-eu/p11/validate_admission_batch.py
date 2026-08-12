#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re

from opportunity_contract import MATERIAL_FACT_CLASSES, validate_bundle

ROOT = pathlib.Path(__file__).resolve().parent


def main() -> int:
    bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))
    batch = json.loads((ROOT / "admission_batch_01.json").read_text(encoding="utf-8"))
    validate_bundle(bundle)
    ids = batch["opportunity_ids"]
    if len(ids) != 5 or len(set(ids)) != len(ids):
        raise SystemExit("batch 01 must contain exactly five unique opportunity IDs")
    if batch.get("publication_allowed") is not False or batch.get("automatic_material_fact_update_allowed") is not False:
        raise SystemExit("batch admission must be fail-closed")
    for artifact in batch.get("source_artifacts") or []:
        if not artifact.get("path") or not re.fullmatch(r"[0-9a-f]{40}", artifact.get("blob_sha", "")):
            raise SystemExit("source artifact must have a path and pinned Git blob SHA")

    opportunities = {row["opportunity_id"]: row for row in bundle["opportunities"]}
    evidence = {row["evidence_id"]: row for row in bundle["evidence"]}
    open_blocks = {
        row["opportunity_id"]: set(row["blocked_fact_classes"])
        for row in bundle["resolution_tasks"]
        if row["status"] in {"OPEN", "IN_REVIEW"}
    }
    for opportunity_id in ids:
        item = opportunities[opportunity_id]
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
    print(json.dumps({"batch_id": batch["batch_id"], "admitted": len(ids), "publishable": 0, "material_fact_action": "NONE"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
