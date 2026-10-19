from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core_v2"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from historical_fact_evidence_preflight import build


def _reader(url: str) -> dict[str, object]:
    return {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes_hashed": 123,
        "content_sha256": "a" * 64,
        "bounded_read_truncated": False,
        "readback_ok": True,
    }


def test_legacy_fact_is_not_promoted_by_source_readback() -> None:
    candidates = {"first_ten_candidate_ids": ["story-legacy"]}
    facts = {
        "facts": [
            {
                "id": "story-legacy",
                "status": "verified",
                "material_fact_gate": "PASS",
                "sources": [{"name": "Official", "url": "https://example.test/source", "tier": "T1"}],
                "fact_kernel": {
                    "format_hint": "straight_news",
                    "claims": [{"text": "legacy claim"}],
                },
            }
        ]
    }
    result = build(candidates, facts, reader=_reader)
    row = result["rows"][0]
    assert row["state"] == "LEGACY_VERIFIED_FACT_SOURCE_READBACK_ONLY"
    assert row["legacy_verified_fact_record_present"] is True
    assert row["legacy_fact_kernel_present"] is True
    assert row["explicit_core_v2_fact_kernel_present"] is False
    assert row["all_t1_sources_readback_ok"] is True
    assert row["promotion_allowed"] is False
    assert result["publication_authority"] == "NONE"


def test_explicit_core_kernel_is_only_preflighted_not_authorized() -> None:
    candidates = {"first_ten_candidate_ids": ["story-core"]}
    facts = {
        "facts": [
            {
                "id": "story-core",
                "status": "verified",
                "material_fact_gate": "PASS",
                "sources": [{"name": "Official", "url": "https://example.test/source", "tier": "T1"}],
                "fact_kernel": {
                    "what": "what",
                    "who": "who",
                    "where": "where",
                    "when": "when",
                    "why_it_matters": "why",
                    "source": "Official",
                    "source_url": "https://example.test/source",
                    "claims": ["claim"],
                    "evidence_ids": ["evidence-1"],
                },
            }
        ]
    }
    result = build(candidates, facts, reader=_reader)
    row = result["rows"][0]
    assert row["state"] == "CORE_FACT_KERNEL_PRESENT_SOURCE_READBACK"
    assert row["explicit_core_v2_fact_kernel_present"] is True
    assert row["promotion_allowed"] is False
    assert result["explicit_core_v2_fact_kernel_story_count"] == 1


def test_t1_readback_failure_is_fail_closed() -> None:
    candidates = {"first_ten_candidate_ids": ["story-fail"]}
    facts = {
        "facts": [
            {
                "id": "story-fail",
                "status": "verified",
                "material_fact_gate": "PASS",
                "sources": [{"name": "Official", "url": "https://example.test/source", "tier": "T1"}],
            }
        ]
    }

    def failing_reader(url: str) -> dict[str, object]:
        return {"requested_url": url, "http_status": 503, "readback_ok": False, "error": "503"}

    result = build(candidates, facts, reader=failing_reader)
    row = result["rows"][0]
    assert row["state"] == "BLOCKED_T1_SOURCE_READBACK"
    assert row["promotion_allowed"] is False
    assert result["source_readback_story_count"] == 0


if __name__ == "__main__":
    test_legacy_fact_is_not_promoted_by_source_readback()
    test_explicit_core_kernel_is_only_preflighted_not_authorized()
    test_t1_readback_failure_is_fail_closed()
    print("historical fact evidence preflight tests: ok")
