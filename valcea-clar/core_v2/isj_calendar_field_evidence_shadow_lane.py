from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CALENDAR_ROLE = "CONTEST_CALENDAR"


def _evidence_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-calendar-field-{digest[:24]}"


def _line_matches(row: dict[str, Any], pattern: str) -> list[tuple[re.Match[str], dict[str, Any], str]]:
    compiled = re.compile(pattern, re.IGNORECASE)
    matches: list[tuple[re.Match[str], dict[str, Any], str]] = []
    for page in row.get("pages") or []:
        for raw in str(page.get("text") or "").splitlines():
            line = " ".join(raw.split())
            if not line:
                continue
            match = compiled.search(line)
            if match:
                matches.append((match, page, line))
    return matches


def _exact_one(row: dict[str, Any], pattern: str, *, field_name: str) -> tuple[re.Match[str], dict[str, Any], str]:
    matches = _line_matches(row, pattern)
    if len(matches) != 1:
        raise RuntimeError(f"expected_one_calendar_line:{field_name}:observed={len(matches)}")
    return matches[0]


def _field(
    name: str,
    value: Any,
    *,
    row: dict[str, Any],
    page: dict[str, Any],
    excerpt: str,
    derivation: str,
    normalized_date: bool = False,
) -> dict[str, Any]:
    page_number = int(page.get("page_number") or 0)
    page_sha = str(page.get("text_sha256") or "")
    text_evidence_id = str(row.get("document_text_evidence_id") or "")
    context_field_evidence_id = str(row.get("contest_session_field_evidence_id") or "")
    if page_number <= 0 or not page_sha or not text_evidence_id or not context_field_evidence_id or not excerpt.strip():
        raise RuntimeError("calendar_field_evidence_provenance_incomplete")
    return {
        "field": name,
        "value": value,
        "state": "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW",
        "field_evidence_id": _evidence_id(text_evidence_id, context_field_evidence_id, name, str(value), str(page_number), page_sha, excerpt),
        "document_text_evidence_id": text_evidence_id,
        "document_text_sha256": row.get("normalized_text_sha256"),
        "contest_session_year": row.get("contest_session_year"),
        "contest_session_field_evidence_id": context_field_evidence_id,
        "page_number": page_number,
        "page_text_sha256": page_sha,
        "excerpt": excerpt.strip(),
        "derivation": derivation,
        "normalized_date": normalized_date,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
    }


def _calendar_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    order_match, order_page, order_line = _exact_one(
        row,
        r"\bBucurești,\s*(6)\s+august\s+(2026)\.?$",
        field_name="calendar_order_date",
    )
    interview_match, interview_page, interview_line = _exact_one(
        row,
        r"\b(12-27\s+noiembrie)\s+Desfășurarea\s+probelor\s+de\s+interviu\b",
        field_name="interview_window_text",
    )
    appointment_match, appointment_page, appointment_line = _exact_one(
        row,
        r"\b(Până\s+la\s+data\s+de\s+16\s+decembrie)\s+Emiterea\s+și\s+comunicarea\s+deciziilor\s+de\s+numire,\s+cu\s+intrare\s+în\s+vigoare\s+de\s+la\s+(1\s+ianuarie\s+2027)\b",
        field_name="appointment_decision_and_effective_date",
    )

    return [
        _field(
            "calendar_order_date",
            "2026-08-06",
            row=row,
            page=order_page,
            excerpt=order_line,
            derivation="explicit_day_month_year_in_calendar_document",
            normalized_date=True,
        ),
        _field(
            "interview_window_text",
            interview_match.group(1),
            row=row,
            page=interview_page,
            excerpt=interview_line,
            derivation="exact_schedule_window_text_with_interview_descriptor_year_not_inferred",
            normalized_date=False,
        ),
        _field(
            "appointment_decision_deadline_text",
            appointment_match.group(1),
            row=row,
            page=appointment_page,
            excerpt=appointment_line,
            derivation="exact_deadline_text_year_not_inferred",
            normalized_date=False,
        ),
        _field(
            "appointment_effective_date",
            "2027-01-01",
            row=row,
            page=appointment_page,
            excerpt=appointment_line,
            derivation="explicit_day_month_year_in_schedule_line",
            normalized_date=True,
        ),
    ]


def extract_calendar_field_evidence(context_report: dict[str, Any], *, expected_year: int = 2026) -> dict[str, Any]:
    if context_report.get("publication_authority") != "NONE":
        raise ValueError("context_report_publication_boundary_violation")
    if context_report.get("fact_kernel_promotion_allowed") is True or context_report.get("writer_allowed") is True:
        raise ValueError("context_report_promotion_boundary_violation")
    if context_report.get("contest_context_verified") is not True or context_report.get("contest_session_year") != expected_year:
        return {
            "schema_version": "1.0",
            "mode": "ISJ_CALENDAR_FIELD_EVIDENCE_SHADOW",
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "expected_contest_session_year": expected_year,
            "verified_calendar_document_count": 0,
            "field_evidence_count": 0,
            "blocked_count": 1,
            "material_candidate_shadow_count": 0,
            "rows": [{
                "state": "BLOCKED",
                "reason": "verified_contest_context_missing_or_wrong_year",
                "publication_authority": "NONE",
                "material_fact_use": False,
                "fact_kernel_promotion_allowed": False,
                "writer_allowed": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
            }],
            "truth_rule": "Calendar facts may be extracted only from already verified first-party calendar text bound to a separately verified contest-session field. Bare month/day ranges remain raw text unless their year is explicit in the supporting excerpt; this gate never promotes a FactKernel or article.",
        }

    candidates = [
        row for row in (context_report.get("rows") or [])
        if isinstance(row, dict)
        and row.get("document_role") == CALENDAR_ROLE
        and row.get("state") == "DOCUMENT_TEXT_EXTRACTED_SHADOW"
        and row.get("contest_session_year") == expected_year
        and row.get("document_text_evidence_id")
        and row.get("contest_session_field_evidence_id")
    ]
    rows: list[dict[str, Any]] = []
    if len(candidates) != 1:
        rows.append({
            "state": "BLOCKED",
            "reason": "expected_exactly_one_verified_calendar_document",
            "observed_calendar_document_count": len(candidates),
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        })
    else:
        source_row = candidates[0]
        base = {
            "document_role": CALENDAR_ROLE,
            "document_label": source_row.get("document_label"),
            "document_content_evidence_id": source_row.get("document_content_evidence_id"),
            "document_text_evidence_id": source_row.get("document_text_evidence_id"),
            "document_text_sha256": source_row.get("normalized_text_sha256"),
            "contest_session_year": source_row.get("contest_session_year"),
            "contest_session_field_evidence_id": source_row.get("contest_session_field_evidence_id"),
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        try:
            fields = _calendar_fields(source_row)
            rows.append({
                **base,
                "state": "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW",
                "field_evidence_count": len(fields),
                "fields": fields,
                "reason": "exact_calendar_fields_bound_to_verified_pdf_text_non_authorizing",
            })
        except Exception as exc:
            rows.append({
                **base,
                "state": "BLOCKED",
                "field_evidence_count": 0,
                "fields": [],
                "reason": "calendar_field_evidence_extraction_or_provenance_validation_failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    all_fields = [field for row in rows if row.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW" for field in row.get("fields") or []]
    return {
        "schema_version": "1.0",
        "mode": "ISJ_CALENDAR_FIELD_EVIDENCE_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "expected_contest_session_year": expected_year,
        "verified_calendar_document_count": sum(row.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW" for row in rows),
        "field_evidence_count": len(all_fields),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "material_candidate_shadow_count": 1 if all_fields else 0,
        "rows": rows,
        "truth_rule": "Calendar facts may be extracted only from already verified first-party calendar text bound to a separately verified contest-session field. Bare month/day ranges remain raw text unless their year is explicit in the supporting excerpt; this gate never promotes a FactKernel or article.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract exact ISJ calendar field evidence from verified context-document text")
    parser.add_argument("--context", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    result = extract_calendar_field_evidence(context, expected_year=args.year)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verified_calendar_document_count": result["verified_calendar_document_count"],
        "field_evidence_count": result["field_evidence_count"],
        "blocked_count": result["blocked_count"],
        "material_candidate_shadow_count": result["material_candidate_shadow_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
