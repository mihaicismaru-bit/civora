from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _base() -> dict[str, Any]:
    return {
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }


def _verified_fields(report: dict[str, Any], *, expected_state: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for row in report.get("rows") or []:
        if not isinstance(row, dict) or row.get("state") != expected_state:
            continue
        if row.get("publication_authority") != "NONE":
            raise ValueError("field_row_publication_boundary_violation")
        if row.get("fact_kernel_promotion_allowed") is True or row.get("writer_allowed") is True:
            raise ValueError("field_row_promotion_boundary_violation")
        for field in row.get("fields") or []:
            if not isinstance(field, dict) or field.get("state") not in {
                "FIELD_EVIDENCE_VERIFIED_SHADOW",
                "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW",
            }:
                continue
            name = str(field.get("field") or "").strip()
            evidence_id = str(field.get("field_evidence_id") or "").strip()
            if not name or not evidence_id:
                raise ValueError("verified_field_missing_name_or_evidence_id")
            if field.get("fact_kernel_promotion_allowed") is True or field.get("writer_allowed") is True:
                raise ValueError("verified_field_promotion_boundary_violation")
            previous = fields.get(name)
            if previous is not None and (previous.get("value") != field.get("value") or previous.get("field_evidence_id") != evidence_id):
                raise ValueError(f"conflicting_verified_field:{name}")
            fields[name] = field
    return fields


def _iso_date(field: dict[str, Any], *, name: str) -> date:
    if field.get("normalized_date") is False:
        raise ValueError(f"non_normalized_date_not_usable:{name}")
    try:
        return date.fromisoformat(str(field.get("value") or ""))
    except ValueError as exc:
        raise ValueError(f"invalid_iso_date:{name}") from exc


def adjudicate_field_materiality(
    field_report: dict[str, Any],
    calendar_report: dict[str, Any],
    *,
    as_of: date | None = None,
    expected_year: int = 2026,
    max_list_age_days: int = 90,
) -> dict[str, Any]:
    current = as_of or date.today()
    base = _base()

    for report_name, report in (("field", field_report), ("calendar", calendar_report)):
        if report.get("publication_authority") != "NONE":
            raise ValueError(f"{report_name}_report_publication_boundary_violation")
        if report.get("fact_kernel_promotion_allowed") is True or report.get("writer_allowed") is True:
            raise ValueError(f"{report_name}_report_promotion_boundary_violation")

    fields = _verified_fields(field_report, expected_state="FIELD_EVIDENCE_VERIFIED_SHADOW")
    calendar_fields = _verified_fields(calendar_report, expected_state="CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW")
    combined = {**fields, **calendar_fields}

    required_names = (
        "contest_session_year",
        "vacant_function_count",
        "list_document_date",
        "appointment_effective_date",
    )
    missing = [name for name in required_names if name not in combined]
    if missing:
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "BLOCKED",
            "reason": "required_verified_field_evidence_missing",
            "missing_fields": missing,
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }

    session = combined["contest_session_year"]
    count = combined["vacant_function_count"]
    list_date_field = combined["list_document_date"]
    appointment_field = combined["appointment_effective_date"]

    if session.get("value") != expected_year:
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "NO_STORY",
            "reason": "contest_session_not_current_expected_year",
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }

    vacancy_count = count.get("value")
    if not isinstance(vacancy_count, int) or vacancy_count <= 0:
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "BLOCKED",
            "reason": "vacancy_count_invalid_or_non_positive",
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }

    list_date = _iso_date(list_date_field, name="list_document_date")
    appointment_date = _iso_date(appointment_field, name="appointment_effective_date")
    if list_date > current + timedelta(days=7):
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "BLOCKED",
            "reason": "vacancy_list_date_implausibly_future",
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }
    if list_date < current - timedelta(days=max_list_age_days):
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "NO_STORY",
            "reason": "verified_vacancy_list_is_stale_for_current_news_materiality",
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }
    if appointment_date < current:
        return {
            **base,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "as_of_date": current.isoformat(),
            "state": "NO_STORY",
            "reason": "verified_appointment_effective_date_already_elapsed",
            "materiality_candidate_count": 0,
            "materiality_candidates": [],
            "usable_field_evidence_ids": [],
            "unresolved_fields": ["registration_deadline"],
            "fabricated_claim_count": 0,
        }

    evidence_fields = [session, count, list_date_field, appointment_field]
    usable_ids = [str(field["field_evidence_id"]) for field in evidence_fields]
    candidate = {
        "category": "LOCAL_EDUCATION_LEADERSHIP",
        "public_consequence": "current_official_school_leadership_competition_has_verified_vacancies_and_future_appointment_effective_date",
        "epistemic_status": "FIELD_EVIDENCE_SUPPORTED_MATERIALITY_CANDIDATE",
        "contest_session_year": expected_year,
        "vacant_function_count": vacancy_count,
        "vacancy_list_date": list_date.isoformat(),
        "appointment_effective_date": appointment_date.isoformat(),
        "field_evidence_ids": usable_ids,
        "excluded_unverified_or_non_normalized_fields": [
            "registration_deadline",
            "interview_window_text",
            "appointment_decision_deadline_text",
        ],
        "fact_kernel_status": "NOT_PROMOTED",
    }

    return {
        **base,
        "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
        "as_of_date": current.isoformat(),
        "state": "MATERIALITY_CANDIDATE_SHADOW",
        "reason": "current_reader_relevant_school_leadership_consequence_supported_only_by_exact_verified_field_evidence",
        "materiality_candidate_count": 1,
        "materiality_candidates": [candidate],
        "usable_field_evidence_ids": usable_ids,
        "unresolved_fields": ["registration_deadline"],
        "fabricated_claim_count": 0,
        "truth_rule": (
            "Materiality may use only exact field_evidence_id-bound values. The raw interview and appointment-decision ranges are excluded because their supporting lines do not themselves state a year, and the registration deadline remains unresolved. This gate does not create a FactKernel or authorize a writer, site publication, social delivery, or acceptance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate ISJ field-evidence materiality without promoting a FactKernel")
    parser.add_argument("--fields", required=True)
    parser.add_argument("--calendar-fields", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fields = json.loads(Path(args.fields).read_text(encoding="utf-8"))
    calendar_fields = json.loads(Path(args.calendar_fields).read_text(encoding="utf-8"))
    current = date.fromisoformat(args.as_of) if args.as_of else date.today()
    result = adjudicate_field_materiality(fields, calendar_fields, as_of=current, expected_year=args.year)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "materiality_candidate_count": result["materiality_candidate_count"],
        "fabricated_claim_count": result["fabricated_claim_count"],
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
