from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(doc: dict[str, Any]) -> None:
    assert doc.get("publication_authority") == "NONE"
    assert doc.get("acceptance_ready") is False
    assert doc.get("material_fact_use") is False
    assert doc.get("fact_kernel_promotion_allowed") is False
    assert doc.get("writer_allowed") is False
    assert doc.get("production_writer_ready") is False
    assert doc.get("site_publish_allowed") is False
    assert doc.get("social_publish_allowed") is False

    verified = 0
    blocked = 0
    fields: list[dict[str, Any]] = []
    field_ids: set[str] = set()
    for row in doc.get("rows") or []:
        state = row.get("state")
        assert state in {"FIELD_EVIDENCE_VERIFIED_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert "fact_kernel" not in row and "article" not in row and "article_package" not in row
        if state == "BLOCKED":
            blocked += 1
            assert int(row.get("field_evidence_count") or 0) == 0
            assert not (row.get("fields") or [])
            continue
        verified += 1
        row_fields = row.get("fields") or []
        assert int(row.get("field_evidence_count") or 0) == len(row_fields)
        assert row_fields
        for field in row_fields:
            assert field.get("state") == "FIELD_EVIDENCE_VERIFIED_SHADOW"
            assert field.get("fact_kernel_promotion_allowed") is False
            assert field.get("writer_allowed") is False
            evidence_id = str(field.get("field_evidence_id") or "")
            assert evidence_id.startswith("isj-field-") and evidence_id not in field_ids
            field_ids.add(evidence_id)
            assert field.get("document_text_evidence_id")
            assert field.get("document_text_sha256")
            assert int(field.get("page_number") or 0) > 0
            assert field.get("page_text_sha256")
            assert str(field.get("excerpt") or "").strip()
            assert str(field.get("derivation") or "").strip()
            fields.append(field)

    assert int(doc.get("verified_document_count") or 0) == verified
    assert int(doc.get("blocked_count") or 0) == blocked
    assert int(doc.get("field_evidence_count") or 0) == len(fields)

    by_name = {str(field.get("field")): field.get("value") for field in fields}
    material_count = int(doc.get("material_candidate_shadow_count") or 0)
    assert material_count in {0, 1}
    if material_count == 1:
        assert by_name.get("contest_session_year") == 2026
        vacancy_count = by_name.get("vacant_function_count")
        assert isinstance(vacancy_count, int) and vacancy_count > 0
        vacancy_field = next(field for field in fields if field.get("field") == "vacant_function_count")
        assert vacancy_field.get("derivation") == "complete_contiguous_table_row_index_sequence_1_to_N"
        assert int(vacancy_field.get("first_row_index") or 0) == 1
        assert int(vacancy_field.get("last_row_index") or 0) == vacancy_count
        assert int(vacancy_field.get("row_index_unique_count") or 0) == vacancy_count
        assert vacancy_field.get("row_index_sequence_sha256")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ISJ field evidence remains auditable and non-authorizing")
    parser.add_argument("--fields", default="/tmp/valcea-core-v2-isj-field-evidence-shadow.json")
    args = parser.parse_args()
    doc = json.loads(Path(args.fields).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise AssertionError("field evidence artifact must be a JSON object")
    validate(doc)
    print("ISJ field evidence truth invariants: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
