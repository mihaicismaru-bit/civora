from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core_v2"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from historical_fact_kernel_evidence import SPECS, _normalize, build


CANDIDATES = {
    "first_ten_candidate_ids": [
        "valcea-apa-canal-contract-152m-20260902",
        "cet-govora-cine-a-decis-oprirea-20260821",
    ]
}


def _text_for_source(url: str) -> str:
    for spec in SPECS.values():
        for source_key, source in spec["sources"].items():
            if source["url"] != url:
                continue
            parts: list[str] = []
            parts.extend(source.get("identity_fragments") or [])
            for field in spec["fields"].values():
                if field["source"] == source_key:
                    parts.extend(field["fragments"])
            for claim in spec["claims"]:
                if claim["source"] == source_key:
                    parts.extend(claim["fragments"])
            return " ".join(parts)
    raise AssertionError(f"unknown fixture source: {url}")


def fixture_reader(url: str) -> dict:
    text = _text_for_source(url)
    raw_links: list[str] = []
    for spec in SPECS.values():
        for source in spec["sources"].values():
            if source["url"] == url:
                raw_links.extend(source.get("raw_link_fragments") or [])
    return {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=UTF-8",
        "bytes_hashed": 1000,
        "content_sha256": "a" * 64,
        "bounded_read_truncated": False,
        "readback_ok": True,
        "_normalized_text": _normalize(text),
        "_raw_lower": " ".join(raw_links).lower(),
    }


def test_two_historical_candidates_become_shadow_fact_kernel_evidence_ready() -> None:
    result = build(CANDIDATES, reader=fixture_reader)
    assert result["publication_authority"] == "NONE"
    assert result["live_promotion_allowed"] is False
    assert result["fact_kernel_evidence_ready_count"] == 2
    assert len(result["rows"]) == 2
    for row in result["rows"]:
        assert row["state"] == "FACT_KERNEL_EVIDENCE_READY_SHADOW"
        assert row["fact_kernel_evidence_ready"] is True
        assert row["site_publish_allowed"] is False
        assert row["social_publish_allowed"] is False
        kernel = row["fact_kernel"]
        assert kernel["what"] and kernel["who"] and kernel["where"] and kernel["when"]
        assert kernel["why_it_matters"] and kernel["source"] and kernel["source_url"]
        assert kernel["claims"] and kernel["evidence_ids"]
        assert len(row["claim_evidence"]) == len(kernel["claims"])
        assert all(item["verified"] is True for item in row["evidence"])


def test_missing_material_fragment_fails_closed() -> None:
    target = "https://apavil.ro/?p=8650"

    def reader(url: str) -> dict:
        result = fixture_reader(url)
        if url == target:
            result["_normalized_text"] = result["_normalized_text"].replace(_normalize("709 812 993 20"), "")
        return result

    result = build(CANDIDATES, reader=reader)
    row = next(row for row in result["rows"] if row["story_id"] == "valcea-apa-canal-contract-152m-20260902")
    assert row["fact_kernel_evidence_ready"] is False
    assert row["state"] == "BLOCKED_INCOMPLETE_FIELD_OR_CLAIM_EVIDENCE"
    assert "field:why_it_matters" in row["blockers"]
    assert "claim:1" in row["blockers"]
    assert "fact_kernel" not in row


def test_missing_official_document_link_fails_closed_for_hcl_mirror() -> None:
    target = "https://hcl.usr.ro/ramnicu_valcea/2026/h225"

    def reader(url: str) -> dict:
        result = fixture_reader(url)
        if url == target:
            result["_raw_lower"] = ""
        return result

    result = build(CANDIDATES, reader=reader)
    row = next(row for row in result["rows"] if row["story_id"] == "cet-govora-cine-a-decis-oprirea-20260821")
    assert row["fact_kernel_evidence_ready"] is False
    assert row["state"] == "BLOCKED_SOURCE_IDENTITY_OR_READBACK"
    assert any(value.startswith("h225:official_link:") for value in row["blockers"])
    assert "fact_kernel" not in row


def test_source_readback_failure_fails_closed() -> None:
    target = "https://hcl.usr.ro/ramnicu_valcea/2026/h5"

    def reader(url: str) -> dict:
        if url == target:
            return {"requested_url": url, "readback_ok": False, "error": "network down"}
        return fixture_reader(url)

    result = build(CANDIDATES, reader=reader)
    row = next(row for row in result["rows"] if row["story_id"] == "cet-govora-cine-a-decis-oprirea-20260821")
    assert row["fact_kernel_evidence_ready"] is False
    assert row["state"] == "BLOCKED_SOURCE_IDENTITY_OR_READBACK"
    assert "h5:readback" in row["blockers"]


def main() -> None:
    test_two_historical_candidates_become_shadow_fact_kernel_evidence_ready()
    test_missing_material_fragment_fails_closed()
    test_missing_official_document_link_fails_closed_for_hcl_mirror()
    test_source_readback_failure_fails_closed()
    print("historical FactKernel evidence tests: PASS")


if __name__ == "__main__":
    main()
