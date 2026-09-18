from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ALLOWED_ROLES = {"REGISTRATION_NOTICE", "CONTEST_CALENDAR", "CONTEST_PROCEDURE"}
ALLOWED_STATES = {"DOCUMENT_TEXT_EXTRACTED_SHADOW", "DOCUMENT_CONTENT_CAPTURED_SHADOW", "BLOCKED"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(doc: dict[str, Any], *, expected_year: int) -> dict[str, Any]:
    assert doc.get("publication_authority") == "NONE"
    assert doc.get("acceptance_ready") is False
    assert doc.get("material_fact_use") is False
    assert doc.get("fact_kernel_promotion_allowed") is False
    assert doc.get("writer_allowed") is False
    assert doc.get("production_writer_ready") is False
    assert doc.get("site_publish_allowed") is False
    assert doc.get("social_publish_allowed") is False

    context_verified = doc.get("contest_context_verified") is True
    selected_count = int(doc.get("selected_context_document_count") or 0)
    extracted_count = int(doc.get("document_text_extracted_shadow_count") or 0)
    blocked_count = int(doc.get("blocked_count") or 0)
    rows = doc.get("rows") or []
    assert isinstance(rows, list)

    if not context_verified:
        assert selected_count == 0
        assert extracted_count == 0
        for row in rows:
            assert row.get("state") == "BLOCKED"
            assert row.get("content_fetch_attempted") is not True
        return {
            "contest_context_verified": False,
            "selected_context_document_count": 0,
            "document_text_extracted_shadow_count": 0,
            "blocked_count": blocked_count,
            "selected_roles": [],
        }

    assert doc.get("expected_contest_session_year") == expected_year
    assert doc.get("contest_session_year") == expected_year
    assert str(doc.get("contest_session_field_evidence_id") or "").startswith("isj-field-")
    assert str(doc.get("contest_session_document_text_evidence_id") or "")
    assert str(doc.get("contest_session_page_text_sha256") or "")
    assert selected_count == len(rows)

    observed_roles: set[str] = set()
    observed_extracted = 0
    observed_blocked = 0
    for row in rows:
        state = row.get("state")
        assert state in ALLOWED_STATES
        assert row.get("publication_authority") == "NONE"
        assert row.get("material_fact_use") is False
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert row.get("deadline_verified") is not True
        assert row.get("calendar_verified") is not True
        assert row.get("event_time_verified") is not True
        assert "fact_kernel" not in row and "article_package" not in row
        assert row.get("contest_session_year") == expected_year
        assert row.get("contest_session_field_evidence_id") == doc.get("contest_session_field_evidence_id")
        assert row.get("context_binding_method") == "verified_contest_session_field_evidence_plus_same_parent_document_target"

        role = str(row.get("document_role") or "")
        assert role in ALLOWED_ROLES
        observed_roles.add(role)
        assert row.get("target_identity_verified") is True

        if state == "BLOCKED":
            observed_blocked += 1
            continue

        assert row.get("content_verified") is True
        assert str(row.get("document_content_evidence_id") or "")
        assert str(row.get("content_sha256") or "")
        assert row.get("raw_bytes_persisted") is False

        if state == "DOCUMENT_TEXT_EXTRACTED_SHADOW":
            observed_extracted += 1
            assert row.get("text_extracted") is True
            assert str(row.get("document_text_evidence_id") or "")
            assert str(row.get("normalized_text_sha256") or "")
            provenance = row.get("extractor_provenance") or {}
            assert str(provenance.get("name") or "")
            assert provenance.get("ocr_used") is False
            pages = row.get("pages") or []
            assert pages
            for page in pages:
                assert int(page.get("page_number") or 0) > 0
                assert str(page.get("text_sha256") or "")

    assert observed_extracted == extracted_count
    assert observed_blocked == blocked_count
    selected_roles = sorted(observed_roles)
    asserted_roles = sorted(str(value) for value in (doc.get("selected_roles") or []))
    assert asserted_roles == selected_roles
    return {
        "contest_context_verified": True,
        "selected_context_document_count": selected_count,
        "document_text_extracted_shadow_count": extracted_count,
        "blocked_count": blocked_count,
        "selected_roles": selected_roles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ISJ context-document truth boundary and provenance invariants")
    parser.add_argument("--context", required=True)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    summary = validate(load(Path(args.context)), expected_year=args.year)
    print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
