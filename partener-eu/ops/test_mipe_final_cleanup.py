#!/usr/bin/env python3
"""Fail-closed architecture contract for the consolidated PARTENER.EU MIPE cleanup."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ABSENT = (
    ".github/workflows/partener-eu-mipe-access-bridge.yml",
    ".github/workflows/partener-eu-mipe-ro-runner.yml",
    "partener-eu/ingest/mipe_browser_ingest.py",
    "partener-eu/ingest/mipe_browser_ingest_v2.py",
    "partener-eu/ingest/state/mipe_ro_trigger.txt",
    "partener-eu/ingest/mipe_ingest.py",
    "partener-eu/ingest/mipe_ingest_ipv4.py",
    "partener-eu/ingest/mipe_known_seed_ingest.py",
    "partener-eu/ingest/mipe_pdds_ingest.py",
    "partener-eu/ops/fix_mipe_decision_extraction.py",
    "partener-eu/ops/fix_mipe_dual_reporting.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
)

DELETED_FIXERS = tuple(Path(path).name for path in ABSENT if "/fix_mipe_" in path)
MATERIALIZED_RESILIENT_SHA256 = "ad82649456a2aced555ffd43ae768ab275e4b02fb6a32acd6e152097280e500b"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    for path in ABSENT:
        assert not (ROOT / path).exists(), f"retired MIPE path reappeared: {path}"

    validation = text(".github/workflows/partener-eu-validation.yml")
    dual_relay = text(".github/workflows/partener-eu-mipe-dual-relay.yml")
    dual_cache = text(".github/workflows/partener-eu-mipe-dual-cache.yml")
    scheduler = text(".github/workflows/partener-eu-mipe-ro-v3-scheduler.yml")
    acquisition = text(".github/workflows/partener-eu-mipe-ro-crawl-v3.yml")
    acquisition_qa = text(".github/workflows/partener-eu-mipe-ro-crawl-v3-qa.yml")
    engine = text(".github/workflows/partener-eu-mipe-engine-v3.yml")
    pages = text(".github/workflows/partener-eu-pages.yml")
    crawler = text("partener-eu/ingest/mipe_windows_crawl_v3.py")
    hosted_direct = text(".github/workflows/partener-eu-mipe-ingest.yml")

    for fixer in DELETED_FIXERS:
        assert fixer not in validation, f"runtime fixer still invoked by validation: {fixer}"
        assert fixer not in dual_relay, f"runtime fixer still invoked by dual relay: {fixer}"
    assert "partener-eu/ingest/mipe_resilient_ingest.py" not in validation
    assert "Validate immutable diagnostic runtime" in dual_relay

    assert "cron: '11 */3 * * *'" not in scheduler
    assert "workflow_dispatch:" in scheduler
    assert "17 */3 * * *" in acquisition
    assert "cron: '7 * * * *'" not in dual_cache
    assert "workflow_dispatch:" in dual_cache

    assert "permissions:\n  contents: read" in acquisition
    assert "MIPE_ACQUISITION_ONLY: '1'" in acquisition
    assert "PARTENER_MIPE_ACQUISITION_HANDOFF_V1" in acquisition
    assert "mipe-ro-acquisition-v3" in acquisition
    assert "MIPE_STATE_BEFORE_SHA" in acquisition and "MIPE_FEED_BEFORE_SHA" in acquisition
    for forbidden in (
        "build_mipe_canonical_calls.py",
        "build_decision_products.py",
        "build_call_lifecycle.py",
        "intelligence_index.py",
        "Refresh MIPE Romanian corpus, targeted deep dossiers and lifecycle",
    ):
        assert forbidden not in acquisition, f"SURFACEMC crossed processing boundary: {forbidden}"
    assert "contents: write" not in acquisition

    guard = 'if os.getenv("MIPE_ACQUISITION_ONLY", "").strip().lower() in {"1", "true", "yes"}:'
    assert crawler.count(guard) == 1
    assert crawler.index(guard) > crawler.index("CORPUS_PATH.write_text")
    assert crawler.index(guard) < crawler.index('prior_items = {i.get("url")')

    assert "- 'PARTENER.EU MIPE Windows Crawl v3'" in engine
    assert "actions/download-artifact@v4" in engine
    assert "PARTENER_MIPE_ACQUISITION_HANDOFF_V1" in engine
    assert "corpusSha256" in engine
    assert "project_mipe_v3_corpus.py" in engine
    assert "PARTENER_MIPE_ENGINE_V3_CHECKPOINT_V1" in engine
    assert "actions: read" in engine and "contents: write" in engine
    for required in (
        "build_mipe_canonical_calls.py",
        "build_decision_products.py",
        "build_call_lifecycle.py",
        "intelligence_index.py",
    ):
        assert required in engine, f"PARTENER engine missing processor: {required}"

    assert "PARTENER.EU MIPE Engine v3" in pages
    assert "- 'PARTENER.EU MIPE Windows Crawl v3'" not in pages
    assert "SURFACEMC acquisition-only -> PARTENER engine boundary: PASS" in acquisition_qa

    # The GitHub-hosted canonical route remains direct-only and fail-closed.
    assert "mipe_direct_only_ingest.py" in hosted_direct
    assert "CANONICAL_OFFICIAL_FETCH" in hosted_direct
    assert "forbidden_transport_markers = ('relay', 'jina-reader', 'translate')" in hosted_direct
    assert "transport.startswith('direct')" in hosted_direct

    resilient_path = ROOT / "partener-eu/ingest/mipe_resilient_ingest.py"
    resilient_sha = hashlib.sha256(resilient_path.read_bytes()).hexdigest()
    assert resilient_sha == MATERIALIZED_RESILIENT_SHA256, (
        "immutable resilient runtime drifted", resilient_sha, MATERIALIZED_RESILIENT_SHA256
    )

    audit_path = ROOT / "partener-eu/ops/mipe_legacy_audit.json"
    audit_summary = None
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        rows = {row["file"]: row for row in audit.get("candidates", [])}
        for path in ABSENT:
            row = rows.get(path)
            if row is None:
                continue
            assert row.get("status") == "ABSENT", (path, row.get("status"))
            assert row.get("strongCallerCount") == 0, (path, row.get("strongCallerCount"))
        audit_summary = audit.get("summary")

    print(json.dumps({
        "status": "PASS",
        "contract": "PARTENER_MIPE_FINAL_CLEANUP_V1",
        "retiredPaths": len(ABSENT),
        "materializedResilientSha256": resilient_sha,
        "surfacemcAcquisitionOnly": True,
        "partenerEngineOwnsProcessing": True,
        "hostedCanonicalDirectOnly": True,
        "auditSummary": audit_summary,
    }, ensure_ascii=False, indent=2))
    print("PARTENER.EU MIPE final cleanup contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
