from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(doc: dict[str, Any]) -> dict[str, Any]:
    assert doc.get("publication_authority") == "NONE"
    assert doc.get("acceptance_ready") is False
    assert doc.get("material_fact_use") is False
    assert doc.get("fact_kernel_promotion_allowed") is False
    assert doc.get("writer_allowed") is False
    assert doc.get("production_writer_ready") is False
    assert doc.get("site_publish_allowed") is False
    assert doc.get("social_publish_allowed") is False
    assert int(doc.get("fabricated_claim_count") or 0) == 0

    state = doc.get("state")
    candidates = doc.get("materiality_candidates") or []
    if state != "MATERIALITY_CANDIDATE_SHADOW":
        assert int(doc.get("materiality_candidate_count") or 0) == 0
        assert not candidates
        return {"state": state, "materiality_candidate_count": 0}

    assert int(doc.get("materiality_candidate_count") or 0) == 1
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.get("category") == "LOCAL_EDUCATION_LEADERSHIP"
    assert candidate.get("epistemic_status") == "FIELD_EVIDENCE_SUPPORTED_MATERIALITY_CANDIDATE"
    assert candidate.get("fact_kernel_status") == "NOT_PROMOTED"
    assert candidate.get("contest_session_year") == 2026
    vacancy_count = candidate.get("vacant_function_count")
    assert isinstance(vacancy_count, int) and vacancy_count > 0
    assert str(candidate.get("vacancy_list_date") or "")
    assert str(candidate.get("appointment_effective_date") or "")
    ids = candidate.get("field_evidence_ids") or []
    assert len(ids) == 4
    assert len(set(ids)) == 4
    assert all(str(value).startswith(("isj-field-", "isj-calendar-field-")) for value in ids)
    excluded = set(candidate.get("excluded_unverified_or_non_normalized_fields") or [])
    assert "registration_deadline" in excluded
    assert "interview_window_text" in excluded
    assert "appointment_decision_deadline_text" in excluded
    assert "isj-calendar-field-" not in " ".join(str(v) for v in ids if "interview" in str(v))
    assert "fact_kernel" not in candidate
    assert "article" not in candidate
    return {
        "state": state,
        "materiality_candidate_count": 1,
        "vacant_function_count": vacancy_count,
        "field_evidence_id_count": len(ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ISJ field materiality remains evidence-bound and non-authorizing")
    parser.add_argument("--materiality", required=True)
    args = parser.parse_args()
    doc = json.loads(Path(args.materiality).read_text(encoding="utf-8"))
    summary = validate(doc)
    print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
