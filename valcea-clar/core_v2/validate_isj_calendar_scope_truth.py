from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CALENDAR_ROLE = "CONTEST_CALENDAR"
REGISTRATION_WINDOW = "14 septembrie-2 octombrie"
SCOPE_HEADING_RE = re.compile(
    r"\bCALENDARUL\s+pentru organizarea și desfășurarea concursului pentru ocuparea funcțiilor vacante de director și director adjunct\s+din unitățile de învățământ preuniversitar de stat, sesiunea august-decembrie\s+(20\d{2})\b",
    re.IGNORECASE,
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _evidence_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-calendar-scope-{digest[:24]}"


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}: publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}: acceptance_ready"
    assert doc.get("material_fact_use") is False, f"{label}: material_fact_use"
    assert doc.get("fact_kernel_promotion_allowed") is False, f"{label}: fact_kernel_promotion_allowed"
    assert doc.get("writer_allowed") is False, f"{label}: writer_allowed"
    assert doc.get("site_publish_allowed") is False, f"{label}: site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}: social_publish_allowed"


def _calendar_context_row(context: dict[str, Any], year: int) -> dict[str, Any]:
    rows = [
        row for row in (context.get("rows") or [])
        if isinstance(row, dict)
        and row.get("state") == "DOCUMENT_TEXT_EXTRACTED_SHADOW"
        and row.get("document_role") == CALENDAR_ROLE
        and row.get("contest_session_year") == year
        and row.get("document_text_evidence_id")
        and row.get("contest_session_field_evidence_id")
    ]
    assert len(rows) == 1, f"context calendar row cardinality={len(rows)}"
    return rows[0]


def _calendar_field_row(calendar: dict[str, Any], year: int) -> dict[str, Any]:
    rows = [
        row for row in (calendar.get("rows") or [])
        if isinstance(row, dict)
        and row.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW"
        and row.get("contest_session_year") == year
    ]
    assert len(rows) == 1, f"calendar field row cardinality={len(rows)}"
    return rows[0]


def validate(
    context: dict[str, Any],
    calendar: dict[str, Any],
    scope: dict[str, Any],
    *,
    expected_year: int,
) -> dict[str, Any]:
    _require_shadow_boundary(context, "context")
    _require_shadow_boundary(calendar, "calendar")
    _require_shadow_boundary(scope, "scope")

    assert context.get("contest_context_verified") is True
    assert context.get("contest_session_year") == expected_year
    assert scope.get("expected_contest_session_year") == expected_year
    assert scope.get("same_document_year_scope_verified") is True
    assert scope.get("registration_window_normalized") is True
    assert scope.get("registration_deadline_normalized") is True
    assert scope.get("registration_window_start_date") == f"{expected_year}-09-14"
    assert scope.get("registration_deadline") == f"{expected_year}-10-02"
    assert int(scope.get("field_evidence_count") or 0) == 3
    assert int(scope.get("blocked_count") or 0) == 0

    context_row = _calendar_context_row(context, expected_year)
    calendar_row = _calendar_field_row(calendar, expected_year)
    text_id = str(context_row.get("document_text_evidence_id") or "")
    session_id = str(context_row.get("contest_session_field_evidence_id") or "")
    assert calendar_row.get("document_text_evidence_id") == text_id
    assert calendar_row.get("contest_session_field_evidence_id") == session_id

    raw_fields = {
        str(field.get("field") or ""): field
        for field in (calendar_row.get("fields") or [])
        if isinstance(field, dict)
    }
    registration = raw_fields.get("registration_window_text") or {}
    assert registration.get("state") == "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW"
    assert registration.get("value") == REGISTRATION_WINDOW
    assert registration.get("normalized_date") is False
    raw_id = str(registration.get("field_evidence_id") or "")
    assert raw_id and raw_id == scope.get("registration_source_field_evidence_id")
    assert registration.get("document_text_evidence_id") == text_id
    assert registration.get("contest_session_field_evidence_id") == session_id

    registration_page = int(registration.get("page_number") or 0)
    registration_hash = str(registration.get("page_text_sha256") or "")
    registration_excerpt = _norm(registration.get("excerpt"))
    assert registration_page > 0 and registration_hash and registration_excerpt
    registration_matches = [
        page for page in (context_row.get("pages") or [])
        if int(page.get("page_number") or 0) == registration_page
        and str(page.get("text_sha256") or "") == registration_hash
        and registration_excerpt in _norm(page.get("text"))
    ]
    assert len(registration_matches) == 1, "registration provenance is not bound to the verified calendar page"

    heading_matches: list[tuple[dict[str, Any], str, int]] = []
    for page in context_row.get("pages") or []:
        text = _norm(page.get("text"))
        for match in SCOPE_HEADING_RE.finditer(text):
            heading_matches.append((page, match.group(0), int(match.group(1))))
    assert len(heading_matches) == 1, f"explicit scope heading cardinality={len(heading_matches)}"
    scope_page, scope_excerpt, observed_year = heading_matches[0]
    assert observed_year == expected_year
    scope_page_number = int(scope_page.get("page_number") or 0)
    scope_page_hash = str(scope_page.get("text_sha256") or "")
    assert scope_page_number > 0 and scope_page_hash
    expected_scope_id = _evidence_id(
        text_id,
        session_id,
        "calendar_scope_session_year",
        str(expected_year),
        str(scope_page_number),
        scope_page_hash,
        scope_excerpt,
    )
    assert scope.get("calendar_scope_session_year_field_evidence_id") == expected_scope_id

    scope_rows = [
        row for row in (scope.get("rows") or [])
        if isinstance(row, dict) and row.get("state") == "CALENDAR_SCOPE_BINDING_VERIFIED_SHADOW"
    ]
    assert len(scope_rows) == 1
    scope_row = scope_rows[0]
    assert scope_row.get("document_role") == CALENDAR_ROLE
    assert scope_row.get("document_text_evidence_id") == text_id
    assert scope_row.get("contest_session_year") == expected_year
    assert scope_row.get("publication_authority") == "NONE"
    assert scope_row.get("material_fact_use") is False
    assert scope_row.get("fact_kernel_promotion_allowed") is False
    assert scope_row.get("writer_allowed") is False
    assert scope_row.get("site_publish_allowed") is False
    assert scope_row.get("social_publish_allowed") is False

    scope_fields = {
        str(field.get("field") or ""): field
        for field in (scope_row.get("fields") or [])
        if isinstance(field, dict)
    }
    assert set(scope_fields) == {"calendar_scope_session_year", "registration_window_start_date", "registration_deadline"}
    year_field = scope_fields["calendar_scope_session_year"]
    assert year_field.get("value") == expected_year
    assert year_field.get("field_evidence_id") == expected_scope_id
    assert int(year_field.get("page_number") or 0) == scope_page_number
    assert year_field.get("page_text_sha256") == scope_page_hash
    assert _norm(year_field.get("excerpt")) == _norm(scope_excerpt)
    assert year_field.get("material_fact_use") is False
    assert year_field.get("fact_kernel_promotion_allowed") is False
    assert year_field.get("writer_allowed") is False

    normalized_values = {
        "registration_window_start_date": f"{expected_year}-09-14",
        "registration_deadline": f"{expected_year}-10-02",
    }
    for name, expected_value in normalized_values.items():
        field = scope_fields[name]
        assert field.get("state") == "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW"
        assert field.get("value") == expected_value
        assert field.get("normalized_date") is True
        assert field.get("document_text_evidence_id") == text_id
        assert field.get("contest_session_field_evidence_id") == session_id
        assert field.get("scope_field_evidence_id") == expected_scope_id
        assert field.get("source_registration_window_field_evidence_id") == raw_id
        assert field.get("supporting_field_evidence_ids") == [expected_scope_id, raw_id]
        assert int(field.get("page_number") or 0) == registration_page
        assert field.get("page_text_sha256") == registration_hash
        assert _norm(field.get("excerpt")) == registration_excerpt
        assert field.get("material_fact_use") is False
        assert field.get("fact_kernel_promotion_allowed") is False
        assert field.get("writer_allowed") is False
        expected_id = _evidence_id(expected_scope_id, raw_id, name, expected_value)
        assert field.get("field_evidence_id") == expected_id

    return {
        "status": "PASS_SHADOW",
        "same_document_year_scope_verified": True,
        "registration_window_normalized": True,
        "registration_window_start_date": f"{expected_year}-09-14",
        "registration_deadline": f"{expected_year}-10-02",
        "scope_field_evidence_id": expected_scope_id,
        "source_registration_window_field_evidence_id": raw_id,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    context: dict[str, Any],
    calendar: dict[str, Any],
    scope: dict[str, Any],
    *,
    expected_year: int,
) -> int:
    cases: list[tuple[str, dict[str, Any]]] = []

    deadline_tamper = copy.deepcopy(scope)
    deadline_tamper["registration_deadline"] = f"{expected_year}-10-03"
    cases.append(("top-level deadline changed without evidence", deadline_tamper))

    page_hash_tamper = copy.deepcopy(scope)
    rows = page_hash_tamper.get("rows") or []
    assert rows and isinstance(rows[0], dict)
    fields = rows[0].get("fields") or []
    deadline_fields = [field for field in fields if isinstance(field, dict) and field.get("field") == "registration_deadline"]
    assert len(deadline_fields) == 1
    deadline_fields[0]["page_text_sha256"] = "0" * 64
    cases.append(("normalized deadline page hash detached from source page", page_hash_tamper))

    passed = 0
    for label, tampered in cases:
        try:
            validate(context, calendar, tampered, expected_year=expected_year)
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"calendar scope runtime validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate ISJ calendar scope runtime evidence and fail-closed tamper behavior")
    parser.add_argument("--context", required=True)
    parser.add_argument("--calendar-fields", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    context = _load(Path(args.context))
    calendar = _load(Path(args.calendar_fields))
    scope = _load(Path(args.scope))
    summary = validate(context, calendar, scope, expected_year=args.year)
    tamper_passed = prove_tamper_regressions(context, calendar, scope, expected_year=args.year) if args.prove_tamper else 0
    report = {
        "schema_version": "1.0",
        "mode": "ISJ_CALENDAR_SCOPE_RUNTIME_VALIDATION",
        **summary,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": tamper_passed,
        "materiality_promotion_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": "The normalized ISJ registration window is accepted as runtime evidence only when independently rebound to the same verified calendar document, explicit 2026 session heading, exact raw registration field and source page hash. This validation does not promote materiality, FactKernel, writer or publication authority.",
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "registration_deadline": report["registration_deadline"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
