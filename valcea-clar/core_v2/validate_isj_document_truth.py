from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise AssertionError(f"{path}: expected JSON object")
    return doc


def _none_authority(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}: publication authority escaped shadow"
    assert doc.get("acceptance_ready") is False, f"{label}: acceptance_ready must remain false"
    assert doc.get("fact_kernel_promotion_allowed") is False, f"{label}: FactKernel promotion must remain disabled"
    assert doc.get("writer_allowed") is False, f"{label}: writer must remain disabled"


def validate(targets: dict[str, Any], contents: dict[str, Any]) -> None:
    _none_authority(targets, "isj_targets")
    _none_authority(contents, "isj_contents")
    assert contents.get("site_publish_allowed") is False
    assert contents.get("social_publish_allowed") is False
    assert contents.get("material_fact_use") is False

    target_bound = 0
    for row in targets.get("rows") or []:
        assert row.get("state") in {"EMBEDDED_TARGET_IDENTITY_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        for binding in row.get("bindings") or []:
            assert binding.get("state") in {"TARGET_IDENTITY_BOUND_SHADOW", "BLOCKED"}
            if binding.get("state") != "TARGET_IDENTITY_BOUND_SHADOW":
                continue
            target_bound += 1
            assert binding.get("target_identity_verified") is True
            assert binding.get("future_content_fetch_eligible") is True
            assert binding.get("content_fetched") is False
            assert binding.get("content_verified") is False
            assert binding.get("material_fact_use") is False
            assert binding.get("resource_id")
            assert binding.get("target_class")
    assert int(targets.get("embedded_target_identity_shadow_count") or 0) == sum(
        row.get("state") == "EMBEDDED_TARGET_IDENTITY_SHADOW" for row in (targets.get("rows") or [])
    )

    captured = 0
    extracted = 0
    blocked = 0
    for row in contents.get("rows") or []:
        state = row.get("state")
        assert state in {"DOCUMENT_TEXT_EXTRACTED_SHADOW", "DOCUMENT_CONTENT_CAPTURED_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("production_writer_ready") is False
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert row.get("sensitive_result_projection_allowed") is False
        assert row.get("field_extraction_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        if state == "BLOCKED":
            blocked += 1
            assert row.get("reason")
            assert row.get("text_extracted") is not True
            continue

        captured += 1
        assert row.get("content_verified") is True
        assert row.get("document_content_evidence_id")
        assert row.get("content_sha256")
        assert int(row.get("content_length") or 0) > 0
        assert row.get("raw_bytes_persisted") is False
        assert row.get("final_host")

        if state == "DOCUMENT_CONTENT_CAPTURED_SHADOW":
            assert row.get("text_extracted") is False
            continue

        extracted += 1
        assert row.get("content_container") == "PDF"
        assert row.get("text_extracted") is True
        assert row.get("document_text_evidence_id")
        text = str(row.get("normalized_text") or "")
        assert text.strip()
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == row.get("normalized_text_sha256")
        provenance = row.get("extractor_provenance") or {}
        assert provenance.get("name") == "poppler_pdftotext"
        assert provenance.get("executable_basename") == "pdftotext"
        assert provenance.get("shell") is False
        assert provenance.get("ocr_used") is False
        assert provenance.get("version")
        assert provenance.get("args") == ["-layout", "-enc", "UTF-8", "-eol", "unix"]
        pages = row.get("pages") or []
        assert pages
        page_numbers: set[int] = set()
        for page in pages:
            number = int(page.get("page_number") or 0)
            assert number > 0 and number not in page_numbers
            page_numbers.add(number)
            page_text = str(page.get("text") or "")
            assert page_text.strip()
            assert hashlib.sha256(page_text.encode("utf-8")).hexdigest() == page.get("text_sha256")
            assert int(page.get("char_count") or 0) == len(page_text)

    assert int(contents.get("document_content_captured_shadow_count") or 0) == captured
    assert int(contents.get("document_text_extracted_shadow_count") or 0) == extracted
    assert int(contents.get("blocked_count") or 0) == blocked
    assert int(contents.get("selected_document_count") or 0) == len(contents.get("rows") or [])
    assert int(contents.get("selected_document_count") or 0) <= target_bound


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ISJ target and PDF text artifacts remain truth-bound and non-authorizing")
    parser.add_argument("--targets", default="/tmp/valcea-core-v2-isj-embedded-target-shadow.json")
    parser.add_argument("--contents", default="/tmp/valcea-core-v2-isj-embedded-content-shadow.json")
    args = parser.parse_args()
    validate(_load(Path(args.targets)), _load(Path(args.contents)))
    print("ISJ document target/text truth invariants: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
