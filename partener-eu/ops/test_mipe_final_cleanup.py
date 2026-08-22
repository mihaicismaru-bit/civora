#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

FORBIDDEN_PATHS = (
    ".github/workflows/partener-eu-mipe-access-bridge.yml",
    ".github/workflows/partener-eu-mipe-ro-runner.yml",
    "partener-eu/ingest/mipe_browser_ingest.py",
    "partener-eu/ingest/mipe_browser_ingest_v2.py",
    "partener-eu/ingest/mipe_ingest.py",
    "partener-eu/ingest/mipe_ingest_ipv4.py",
    "partener-eu/ingest/mipe_known_seed_ingest.py",
    "partener-eu/ingest/mipe_pdds_ingest.py",
    "partener-eu/ingest/state/mipe_ro_trigger.txt",
    "partener-eu/ops/fix_mipe_decision_extraction.py",
    "partener-eu/ops/fix_mipe_dual_reporting.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
)

MATERIALIZED_RESILIENT_SHA256 = "ad82649456a2aced555ffd43ae768ab275e4b02fb6a32acd6e152097280e500b"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def assert_manual_read_only(workflow: str) -> None:
    text = read(workflow)
    assert "workflow_dispatch:" in text, workflow
    assert "schedule:" not in text and "cron:" not in text, workflow
    assert "push:\n" not in text, workflow
    assert "permissions:\n  contents: read" in text, workflow
    assert "git push" not in text and "git commit" not in text, workflow


def main() -> int:
    missing = [p for p in FORBIDDEN_PATHS if (ROOT / p).exists()]
    assert not missing, f"legacy paths still present: {missing}"

    resilient_rel = "partener-eu/ingest/mipe_resilient_ingest.py"
    resilient = read(resilient_rel)
    resilient_hash = sha256(resilient_rel)
    assert resilient_hash == MATERIALIZED_RESILIENT_SHA256, resilient_hash
    assert "def fetch_first_party_relay(" in resilient

    acquisition_rel = ".github/workflows/partener-eu-mipe-ro-crawl-v3.yml"
    engine_rel = ".github/workflows/partener-eu-mipe-engine-v3.yml"
    pages_rel = ".github/workflows/partener-eu-pages.yml"
    scheduler_rel = ".github/workflows/partener-eu-mipe-ro-v3-scheduler.yml"
    relay_rel = ".github/workflows/partener-eu-mipe-dual-relay.yml"
    cache_rel = ".github/workflows/partener-eu-mipe-dual-cache.yml"
    validation_rel = ".github/workflows/partener-eu-validation.yml"
    hosted_rel = ".github/workflows/partener-eu-mipe-ingest.yml"

    acquisition = read(acquisition_rel)
    engine = read(engine_rel)
    pages = read(pages_rel)
    scheduler = read(scheduler_rel)
    validation = read(validation_rel)
    hosted = read(hosted_rel)

    assert acquisition.count("cron: '17 */3 * * *'") == 1
    assert "runs-on: [self-hosted, Windows, X64]" in acquisition
    assert "MIPE_ACQUISITION_ONLY: '1'" in acquisition
    assert "permissions:\n  contents: read" in acquisition
    assert "PARTENER_MIPE_ACQUISITION_HANDOFF_V1" in acquisition
    assert "mipe-ro-acquisition-v3" in acquisition
    assert "git push" not in acquisition and "git commit" not in acquisition
    for forbidden in (
        "build_mipe_canonical_calls.py",
        "build_decision_products.py",
        "build_call_lifecycle.py",
        "intelligence_index.py",
    ):
        assert forbidden not in acquisition, forbidden

    assert "PARTENER.EU MIPE Windows Crawl v3" in engine
    assert "actions/download-artifact@v4" in engine
    assert "PARTENER_MIPE_ACQUISITION_HANDOFF_V1" in engine
    assert "project_mipe_v3_corpus.py" in engine
    assert "permissions:\n  actions: read\n  contents: write" in engine
    for required in (
        "build_mipe_canonical_calls.py",
        "build_decision_products.py",
        "build_call_lifecycle.py",
        "intelligence_index.py",
        "mipe_engine_v3_checkpoint.json",
    ):
        assert required in engine, required

    assert "PARTENER.EU MIPE Engine v3" in pages
    assert "- 'PARTENER.EU MIPE Windows Crawl v3'" not in pages

    assert "workflow_dispatch:" in scheduler
    assert "schedule:" not in scheduler and "cron:" not in scheduler
    assert "partener-eu-mipe-ro-crawl-v3.yml/dispatches" in scheduler

    assert_manual_read_only(relay_rel)
    assert_manual_read_only(cache_rel)

    assert "fix_mipe_" not in validation
    assert "mipe_direct_only_ingest.py" in hosted
    assert "forbidden_transport_markers = ('relay', 'jina-reader', 'translate')" in hosted
    assert "CANONICAL_DUAL_RELAY_CORROBORATED' not in feed_text" in hosted

    executable_refs: list[str] = []
    deleted_names = tuple(Path(p).name for p in FORBIDDEN_PATHS)
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        if "fix_mipe_" in text:
            executable_refs.append(str(wf.relative_to(ROOT)) + ":fix_mipe_")
        for name in deleted_names:
            if name in text:
                executable_refs.append(str(wf.relative_to(ROOT)) + ":" + name)
    ingest_dir = ROOT / "partener-eu" / "ingest"
    for src in sorted(ingest_dir.glob("*.py")):
        text = src.read_text(encoding="utf-8")
        if "fix_mipe_" in text:
            executable_refs.append(str(src.relative_to(ROOT)) + ":fix_mipe_")
        for name in deleted_names:
            if name in text:
                executable_refs.append(str(src.relative_to(ROOT)) + ":" + name)
    assert not executable_refs, f"residual executable legacy refs: {executable_refs}"

    proof = {
        "schema": "PARTENER_MIPE_FINAL_CLEANUP_PROOF_V1",
        "status": "PASS",
        "candidateSha": os.environ.get("GITHUB_SHA"),
        "legacyPathsPresent": 0,
        "residualExecutableLegacyRefs": 0,
        "materializedResilientSha256": resilient_hash,
        "surfacemc": "ACQUISITION_ONLY",
        "partenerEngine": "PROCESS_CANONICALIZE_PUBLISH",
        "relay": "MANUAL_READ_ONLY_DIAGNOSTIC",
        "cache": "MANUAL_READ_ONLY_DIAGNOSTIC",
        "romaniaRecurringOwner": "PARTENER.EU MIPE Windows Crawl v3 @ 17 */3 * * *",
        "hostedCanonical": "DIRECT_ONLY_FAIL_CLOSED",
        "pagesTrigger": "PARTENER.EU MIPE Engine v3",
        "rollback": "revert cleanup commit; all deleted blobs remain addressable in Git history",
    }
    out = ROOT / "partener-eu" / "ops" / "mipe_final_cleanup_proof.json"
    out.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
