from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_FIELDS = {
    "calendar_order_date": ("2026-08-06", True),
    "registration_window_text": ("14 septembrie-2 octombrie", False),
    "interview_window_text": ("12-27 noiembrie", False),
    "appointment_decision_deadline_text": ("Până la data de 16 decembrie", False),
    "appointment_effective_date": ("2027-01-01", True),
}


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
    assert doc.get("expected_contest_session_year") == expected_year
    assert doc.get("registration_deadline_normalized") is False

    rows = doc.get("rows") or []
    verified_rows = [row for row in rows if isinstance(row, dict) and row.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW"]
    blocked_rows = [row for row in rows if isinstance(row, dict) and row.get("state") == "BLOCKED"]
    assert int(doc.get("verified_calendar_document_count") or 0) == len(verified_rows)
    assert int(doc.get("blocked_count") or 0) == len(blocked_rows)

    if not verified_rows:
        assert int(doc.get("field_evidence_count") or 0) == 0
        assert doc.get("registration_window_text_verified") is False
        return {
            "verified_calendar_document_count": 0,
            "field_evidence_count": 0,
            "blocked_count": len(blocked_rows),
            "fields": [],
            "registration_window_text_verified": False,
        }

    assert len(verified_rows) == 1
    row = verified_rows[0]
    assert row.get("publication_authority") == "NONE"
    assert row.get("material_fact_use") is False
    assert row.get("fact_kernel_promotion_allowed") is False
    assert row.get("writer_allowed") is False
    assert row.get("site_publish_allowed") is False
    assert row.get("social_publish_allowed") is False
    assert row.get("contest_session_year") == expected_year
    assert str(row.get("contest_session_field_evidence_id") or "").startswith("isj-field-")
    assert str(row.get("document_text_evidence_id") or "")
    assert "fact_kernel" not in row and "article_package" not in row

    fields = row.get("fields") or []
    assert isinstance(fields, list)
    assert int(row.get("field_evidence_count") or 0) == len(fields)
    assert int(doc.get("field_evidence_count") or 0) == len(fields)
    by_name = {str(field.get("field")): field for field in fields if isinstance(field, dict)}
    assert set(by_name) == set(EXPECTED_FIELDS)

    for name, (expected_value, normalized_date) in EXPECTED_FIELDS.items():
        field = by_name[name]
        assert field.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW"
        assert field.get("value") == expected_value
        assert field.get("normalized_date") is normalized_date
        assert str(field.get("field_evidence_id") or "").startswith("isj-calendar-field-")
        assert field.get("document_text_evidence_id") == row.get("document_text_evidence_id")
        assert field.get("contest_session_field_evidence_id") == row.get("contest_session_field_evidence_id")
        assert field.get("contest_session_year") == expected_year
        assert int(field.get("page_number") or 0) > 0
        assert str(field.get("page_text_sha256") or "")
        assert str(field.get("excerpt") or "")
        assert field.get("material_fact_use") is False
        assert field.get("fact_kernel_promotion_allowed") is False
        assert field.get("writer_allowed") is False

    registration = by_name["registration_window_text"]
    assert doc.get("registration_window_text_verified") is True
    assert doc.get("registration_window_text") == registration.get("value")
    assert doc.get("registration_window_field_evidence_id") == registration.get("field_evidence_id")
    assert registration.get("derivation") == "exact_registration_window_text_with_registration_descriptor_year_not_inferred"

    return {
        "verified_calendar_document_count": 1,
        "field_evidence_count": len(fields),
        "blocked_count": len(blocked_rows),
        "fields": sorted(by_name),
        "registration_window_text_verified": True,
        "registration_deadline_normalized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ISJ calendar field evidence remains exact, evidence-bound and non-authorizing")
    parser.add_argument("--fields", required=True)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    summary = validate(load(Path(args.fields)), expected_year=args.year)
    print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
