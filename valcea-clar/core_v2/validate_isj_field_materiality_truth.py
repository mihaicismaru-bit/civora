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
    assert "interview_window_text" in excluded
    assert "appointment_decision_deadline_text" in excluded
    assert "registration_deadline" in excluded
    assert "isj-calendar-field-" not in " ".join(str(v) for v in ids if "interview" in str(v))
    assert "fact_kernel" not in candidate
    assert "article" not in candidate

    deadline_consumed = doc.get("registration_deadline_materiality_consumed") is True
    if deadline_consumed:
        assert doc.get("unresolved_fields") == []
        deadline = str(doc.get("registration_deadline") or "")
        assert deadline == str(candidate.get("registration_deadline") or "")
        assert deadline.startswith("2026-")
        promoted = (candidate.get("materiality_only_promoted_fields") or {}).get("registration_deadline")
        assert isinstance(promoted, dict)
        assert promoted.get("value") == deadline
        assert promoted.get("epistemic_status") == "INDEPENDENTLY_VALIDATED_MATERIALITY_ONLY_PROMOTION"
        assert promoted.get("fact_kernel_status") == "NOT_PROMOTED"
        assert promoted.get("writer_status") == "NOT_PROMOTED"
        assert str(promoted.get("field_evidence_id") or "").startswith("isj-calendar-scope-")
        promotion_id = str(promoted.get("promotion_evidence_id") or "")
        assert promotion_id.startswith("isj-deadline-promotion-")
        assert doc.get("registration_deadline_promotion_evidence_id") == promotion_id
        assert promoted.get("field_evidence_id") not in ids
    else:
        assert "registration_deadline" in (doc.get("unresolved_fields") or [])
        assert candidate.get("registration_deadline") is None
        assert not candidate.get("materiality_only_promoted_fields")

    return {
        "state": state,
        "materiality_candidate_count": 1,
        "vacant_function_count": vacancy_count,
        "field_evidence_id_count": len(ids),
        "registration_deadline_materiality_consumed": deadline_consumed,
        "registration_deadline": doc.get("registration_deadline"),
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
