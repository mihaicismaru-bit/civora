#!/usr/bin/env python3
"""Publish the latest local run manifest as readable JSON on the evidence branch.

The ZIP remains the immutable raw bundle. This mirror exists so connected GitHub
readers can inspect health/change metadata without opening binary archives.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import agent


def main() -> int:
    base = Path(__file__).resolve().parent
    cfg = agent.load_json(base / "agent.local.json", {}) or {}
    root = agent.data_root(cfg)
    state = agent.load_json(root / "state.json", {}) or {}
    run_id = str(state.get("last_run_id") or "")
    if not run_id:
        print(json.dumps({"published": False, "reason": "NO_LOCAL_RUN"}))
        return 0
    manifest_path = root / "runs" / run_id / "manifest.json"
    publish_result_path = root / "runs" / run_id / "publish-result.json"
    if not manifest_path.exists():
        raise SystemExit("latest manifest missing")
    manifest = agent.load_json(manifest_path, {}) or {}
    publish_result = agent.load_json(publish_result_path, {}) or {}
    token = os.environ.get("PARTENER_RESEARCH_GITHUB_TOKEN")
    if not token:
        print(json.dumps({"published": False, "reason": "PARTENER_RESEARCH_GITHUB_TOKEN_NOT_SET"}))
        return 0
    repo = cfg["repository"]
    branch = cfg.get("evidence_branch", "partener-local-research-evidence")
    base_branch = cfg.get("evidence_base_branch", "main")
    agent.ensure_evidence_branch(repo, branch, base_branch, token)
    day = str(manifest["started_at"])[:10]
    readable_path = f"partener-eu/local-research-evidence/{day}/{run_id}.manifest.json"
    payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    agent.upload_contents(repo, branch, readable_path, payload, token, f"PARTENER local research readable manifest {run_id}")
    latest = {
        "schema": "PARTENER_EU_LOCAL_RESEARCH_LATEST_V2",
        "run_id": run_id,
        "created_at": agent.utc_now(),
        "manifest_path": readable_path,
        "manifest_sha256": agent.sha256_bytes(payload),
        "bundle_path": publish_result.get("bundle_path"),
        "bundle_sha256": manifest.get("bundle_sha256"),
        "source_count": manifest.get("source_count"),
        "healthy_source_count": manifest.get("healthy_source_count"),
        "degraded_source_count": manifest.get("degraded_source_count"),
        "changed_source_count": manifest.get("changed_source_count"),
        "fulfilled_request_ids": manifest.get("fulfilled_request_ids", []),
        "material_fact_use": False,
        "open_call_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }
    latest_path = "partener-eu/local-research-evidence/latest.json"
    agent.upload_contents(repo, branch, latest_path, (json.dumps(latest, sort_keys=True, indent=2) + "\n").encode("utf-8"), token, f"Update PARTENER local research readable latest {run_id}")
    print(json.dumps({"published": True, "manifest_path": readable_path, "latest_path": latest_path}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
