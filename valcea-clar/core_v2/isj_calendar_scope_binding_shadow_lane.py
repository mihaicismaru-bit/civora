from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

CALENDAR_ROLE = "CONTEST_CALENDAR"
REGISTRATION_WINDOW = "14 septembrie-2 octombrie"
MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def _evidence_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-calendar-scope-{digest[:24]}"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_CALENDAR_SCOPE_BINDING_SHADOW",
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


def _blocked(reason: str, *, expected_year: int, detail: str | None = None) -> dict[str, Any]:
    row = {
        "state": "BLOCKED",
        "reason": reason,
        "publication_authority": "NONE",
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    if detail:
        row["detail"] = detail[:500]
    return {
        **_base(),
        "expected_contest_session_year": expected_year,
        "same_document_year_scope_verified": False,
        "registration_window_normalized": False,
        "registration_deadline_normalized": False,
        "field_evidence_count": 0,
        "blocked_count": 1,
        "rows": [row],
    }


def _calendar_context_row(context_report: dict[str, Any], *, expected_year: int) -> dict[str, Any]:
    rows = [
        row
        for row in context_report.get("rows") or []
        if isinstance(row, dict)
        and row.get("state") == "DOCUMENT_TEXT_EXTRACTED_SHADOW"
        and row.get("document_role") == CALENDAR_ROLE
        and row.get("contest_session_year") == expected_year
        and row.get("document_text_evidence_id")
        and row.get("contest_session_field_evidence_id")
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected_one_calendar_context_row:observed={len(rows)}")
    return rows[0]


def _calendar_fields(calendar_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [
        row
        for row in calendar_report.get("rows") or []
        if isinstance(row, dict) and row.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW"
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected_one_calendar_field_row:observed={len(rows)}")
    fields: dict[str, dict[str, Any]] = {}
    for field in rows[0].get("fields") or []:
        if not isinstance(field, dict) or field.get("state") != "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW":
            continue
        name = str(field.get("field") or "")
        if name in fields:
            raise RuntimeError(f"duplicate_calendar_field:{name}")
        fields[name] = field
    return fields


def _explicit_scope_heading(row: dict[str, Any], *, expected_year: int) -> tuple[dict[str, Any], str]:
    pattern = re.compile(
        r"\bCALENDARUL\s+pentru organizarea și desfășurarea concursului pentru ocuparea funcțiilor vacante de director și director adjunct\s+din unitățile de învățământ preuniversitar de stat, sesiunea august-decembrie\s+(20\d{2})\b",
        re.IGNORECASE,
    )
    matches: list[tuple[dict[str, Any], str, int]] = []
    for page in row.get("pages") or []:
        text = _norm(page.get("text"))
        for match in pattern.finditer(text):
            matches.append((page, match.group(0), int(match.group(1))))
    if len(matches) != 1:
        raise RuntimeError(f"expected_one_explicit_calendar_scope_heading:observed={len(matches)}")
    page, excerpt, observed_year = matches[0]
    if observed_year != expected_year:
        raise RuntimeError(f"calendar_scope_year_mismatch:observed={observed_year}:expected={expected_year}")
    if int(page.get("page_number") or 0) <= 0 or not str(page.get("text_sha256") or ""):
        raise RuntimeError("calendar_scope_page_provenance_incomplete")
    return page, excerpt


def _parse_registration_window(raw: str, *, year: int) -> tuple[date, date]:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-zăâîșț]+)-(?:(\d{1,2})\s+)?([A-Za-zăâîșț]+)", _norm(raw), re.IGNORECASE)
    if not match:
        raise RuntimeError("registration_window_text_unparseable")
    start_day = int(match.group(1))
    start_month_name = match.group(2).lower()
    end_day = int(match.group(3) or 0)
    end_month_name = match.group(4).lower()
    if start_month_name not in MONTHS or end_month_name not in MONTHS or end_day <= 0:
        raise RuntimeError("registration_window_month_or_day_invalid")
    return date(year, MONTHS[start_month_name], start_day), date(year, MONTHS[end_month_name], end_day)


def derive_registration_calendar_scope(
    context_report: dict[str, Any],
    calendar_report: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    for label, report in (("context", context_report), ("calendar", calendar_report)):
        if report.get("publication_authority") != "NONE":
            raise ValueError(f"{label}_publication_boundary_violation")
        if report.get("fact_kernel_promotion_allowed") is True or report.get("writer_allowed") is True:
            raise ValueError(f"{label}_promotion_boundary_violation")

    if context_report.get("contest_context_verified") is not True or context_report.get("contest_session_year") != expected_year:
        return _blocked("verified_contest_context_missing_or_wrong_year", expected_year=expected_year)

    try:
        row = _calendar_context_row(context_report, expected_year=expected_year)
        fields = _calendar_fields(calendar_report)
        required = {"calendar_order_date", "registration_window_text", "appointment_effective_date"}
        missing = sorted(required - set(fields))
        if missing:
            raise RuntimeError(f"required_calendar_fields_missing:{','.join(missing)}")

        registration = fields["registration_window_text"]
        order = fields["calendar_order_date"]
        appointment = fields["appointment_effective_date"]
        if registration.get("value") != REGISTRATION_WINDOW or registration.get("normalized_date") is not False:
            raise RuntimeError("registration_window_source_field_unexpected")
        if order.get("value") != f"{expected_year}-08-06" or order.get("normalized_date") is not True:
            raise RuntimeError("calendar_order_date_unexpected")
        if appointment.get("value") != f"{expected_year + 1}-01-01" or appointment.get("normalized_date") is not True:
            raise RuntimeError("appointment_effective_date_unexpected")

        text_id = str(row.get("document_text_evidence_id") or "")
        session_id = str(row.get("contest_session_field_evidence_id") or "")
        if registration.get("document_text_evidence_id") != text_id:
            raise RuntimeError("registration_field_cross_document_mismatch")
        if registration.get("contest_session_field_evidence_id") != session_id:
            raise RuntimeError("registration_field_session_evidence_mismatch")

        registration_page_number = int(registration.get("page_number") or 0)
        registration_page_hash = str(registration.get("page_text_sha256") or "")
        registration_excerpt = _norm(registration.get("excerpt"))
        page_matches = [
            page for page in row.get("pages") or []
            if int(page.get("page_number") or 0) == registration_page_number
            and str(page.get("text_sha256") or "") == registration_page_hash
            and registration_excerpt
            and registration_excerpt in _norm(page.get("text"))
        ]
        if len(page_matches) != 1:
            raise RuntimeError(f"registration_page_provenance_mismatch:observed={len(page_matches)}")

        scope_page, scope_excerpt = _explicit_scope_heading(row, expected_year=expected_year)
        scope_page_number = int(scope_page.get("page_number") or 0)
        scope_page_hash = str(scope_page.get("text_sha256") or "")
        scope_id = _evidence_id(text_id, session_id, "calendar_scope_session_year", str(expected_year), str(scope_page_number), scope_page_hash, scope_excerpt)

        start_date, end_date = _parse_registration_window(REGISTRATION_WINDOW, year=expected_year)
        order_date = date.fromisoformat(str(order.get("value")))
        appointment_date = date.fromisoformat(str(appointment.get("value")))
        if not (order_date <= start_date <= end_date < appointment_date):
            raise RuntimeError("registration_window_temporal_bounds_invalid")
        if start_date.month < 8 or end_date.month > 12:
            raise RuntimeError("registration_window_outside_explicit_session_scope")

        raw_id = str(registration.get("field_evidence_id") or "")
        if not raw_id:
            raise RuntimeError("registration_window_source_evidence_id_missing")
        common = {
            "state": "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW",
            "document_text_evidence_id": text_id,
            "document_text_sha256": row.get("normalized_text_sha256"),
            "contest_session_year": expected_year,
            "contest_session_field_evidence_id": session_id,
            "scope_field_evidence_id": scope_id,
            "source_registration_window_field_evidence_id": raw_id,
            "supporting_field_evidence_ids": [scope_id, raw_id],
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
        }
        scope_field = {
            "field": "calendar_scope_session_year",
            "value": expected_year,
            "field_evidence_id": scope_id,
            "state": "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW",
            "document_text_evidence_id": text_id,
            "document_text_sha256": row.get("normalized_text_sha256"),
            "contest_session_year": expected_year,
            "contest_session_field_evidence_id": session_id,
            "page_number": scope_page_number,
            "page_text_sha256": scope_page_hash,
            "excerpt": scope_excerpt,
            "derivation": "explicit_annex_calendar_heading_session_year",
            "normalized_date": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
        }
        start_field = {
            **common,
            "field": "registration_window_start_date",
            "value": start_date.isoformat(),
            "field_evidence_id": _evidence_id(scope_id, raw_id, "registration_window_start_date", start_date.isoformat()),
            "page_number": registration_page_number,
            "page_text_sha256": registration_page_hash,
            "excerpt": registration_excerpt,
            "derivation": "explicit_same_document_session_year_plus_exact_registration_window_text",
            "normalized_date": True,
        }
        deadline_field = {
            **common,
            "field": "registration_deadline",
            "value": end_date.isoformat(),
            "field_evidence_id": _evidence_id(scope_id, raw_id, "registration_deadline", end_date.isoformat()),
            "page_number": registration_page_number,
            "page_text_sha256": registration_page_hash,
            "excerpt": registration_excerpt,
            "derivation": "explicit_same_document_session_year_plus_exact_registration_window_text",
            "normalized_date": True,
        }
        return {
            **_base(),
            "expected_contest_session_year": expected_year,
            "same_document_year_scope_verified": True,
            "registration_window_normalized": True,
            "registration_window_start_date": start_date.isoformat(),
            "registration_deadline": end_date.isoformat(),
            "registration_deadline_normalized": True,
            "calendar_scope_session_year_field_evidence_id": scope_id,
            "registration_source_field_evidence_id": raw_id,
            "field_evidence_count": 3,
            "blocked_count": 0,
            "rows": [{
                "state": "CALENDAR_SCOPE_BINDING_VERIFIED_SHADOW",
                "document_role": CALENDAR_ROLE,
                "document_label": row.get("document_label"),
                "document_text_evidence_id": text_id,
                "contest_session_year": expected_year,
                "publication_authority": "NONE",
                "material_fact_use": False,
                "fact_kernel_promotion_allowed": False,
                "writer_allowed": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
                "fields": [scope_field, start_field, deadline_field],
                "reason": "same_calendar_document_explicit_session_heading_binds_year_to_exact_registration_window_non_authorizing",
            }],
            "truth_rule": (
                "A month/day registration range is normalized only when the exact registration line is already evidence-bound to the verified calendar PDF, "
                "the same document contains exactly one explicit Annex 1 calendar heading naming the same contest session year, and temporal bounds are internally consistent. "
                "Filename semantics and parent-page labels are insufficient on their own. This gate creates evidence only; it does not promote materiality, a FactKernel, an article, publication or delivery."
            ),
        }
    except Exception as exc:
        return _blocked(
            "same_document_calendar_scope_binding_failed",
            expected_year=expected_year,
            detail=f"{type(exc).__name__}:{exc}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind an explicit ISJ calendar session year to the exact registration window in shadow mode")
    parser.add_argument("--context", required=True)
    parser.add_argument("--calendar-fields", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = derive_registration_calendar_scope(
        json.loads(Path(args.context).read_text(encoding="utf-8")),
        json.loads(Path(args.calendar_fields).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "same_document_year_scope_verified": result.get("same_document_year_scope_verified", False),
        "registration_window_normalized": result.get("registration_window_normalized", False),
        "registration_deadline": result.get("registration_deadline"),
        "blocked_count": result.get("blocked_count", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
