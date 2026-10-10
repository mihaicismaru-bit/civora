from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _promotion_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-deadline-promotion-{digest[:24]}"


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_REGISTRATION_DEADLINE_PROMOTION_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "materiality_promotion_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }


def _blocked(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    out = {
        **_base(),
        "state": "BLOCKED",
        "reason": reason,
        "promotion_candidate_count": 0,
        "promotion_candidates": [],
        "fabricated_claim_count": 0,
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _require_non_authorizing_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("fact_kernel_promotion_allowed") is True:
        raise ValueError(f"{label}_fact_kernel_boundary_violation")
    if doc.get("writer_allowed") is True:
        raise ValueError(f"{label}_writer_boundary_violation")
    if doc.get("site_publish_allowed") is True or doc.get("social_publish_allowed") is True:
        raise ValueError(f"{label}_publication_path_boundary_violation")


def _scope_deadline_field(scope: dict[str, Any], expected_year: int) -> dict[str, Any]:
    rows = [
        row for row in (scope.get("rows") or [])
        if isinstance(row, dict)
        and row.get("state") == "CALENDAR_SCOPE_BINDING_VERIFIED_SHADOW"
        and row.get("contest_session_year") == expected_year
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected_one_scope_row:observed={len(rows)}")
    fields = [
        field for field in (rows[0].get("fields") or [])
        if isinstance(field, dict) and field.get("field") == "registration_deadline"
    ]
    if len(fields) != 1:
        raise RuntimeError(f"expected_one_deadline_field:observed={len(fields)}")
    return fields[0]


def build_deadline_promotion(
    scope: dict[str, Any],
    scope_validation: dict[str, Any],
    *,
    expected_year: int = 2026,
    as_of: date | None = None,
) -> dict[str, Any]:
    current = as_of or date.today()
    try:
        _require_non_authorizing_boundary(scope, "scope")
        _require_non_authorizing_boundary(scope_validation, "scope_validation")

        if scope.get("same_document_year_scope_verified") is not True:
            raise RuntimeError("same_document_year_scope_not_verified")
        if scope.get("registration_deadline_normalized") is not True:
            raise RuntimeError("scope_deadline_not_normalized")
        if scope.get("expected_contest_session_year") != expected_year:
            raise RuntimeError("scope_expected_year_mismatch")
        if scope_validation.get("status") != "PASS_SHADOW":
            raise RuntimeError("independent_scope_validation_not_passed")
        if scope_validation.get("same_document_year_scope_verified") is not True:
            raise RuntimeError("validator_same_document_scope_not_verified")

        scope_deadline = str(scope.get("registration_deadline") or "")
        validation_deadline = str(scope_validation.get("registration_deadline") or "")
        if not scope_deadline or scope_deadline != validation_deadline:
            raise RuntimeError("deadline_disagrees_with_independent_validation")
        parsed_deadline = date.fromisoformat(scope_deadline)
        if parsed_deadline.year != expected_year:
            raise RuntimeError("deadline_year_mismatch")
        if parsed_deadline < current:
            raise RuntimeError("registration_deadline_already_elapsed")

        field = _scope_deadline_field(scope, expected_year)
        if field.get("state") != "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW":
            raise RuntimeError("deadline_scope_field_not_verified")
        if field.get("normalized_date") is not True:
            raise RuntimeError("deadline_scope_field_not_normalized")
        if str(field.get("value") or "") != scope_deadline:
            raise RuntimeError("deadline_scope_field_value_mismatch")
        if field.get("material_fact_use") is not False:
            raise RuntimeError("deadline_scope_field_material_boundary_violation")
        if field.get("fact_kernel_promotion_allowed") is not False or field.get("writer_allowed") is not False:
            raise RuntimeError("deadline_scope_field_downstream_boundary_violation")

        deadline_evidence_id = str(field.get("field_evidence_id") or "")
        scope_evidence_id = str(field.get("scope_field_evidence_id") or "")
        raw_evidence_id = str(field.get("source_registration_window_field_evidence_id") or "")
        document_text_evidence_id = str(field.get("document_text_evidence_id") or "")
        page_hash = str(field.get("page_text_sha256") or "")
        excerpt = _norm(field.get("excerpt"))
        if not all((deadline_evidence_id, scope_evidence_id, raw_evidence_id, document_text_evidence_id, page_hash, excerpt)):
            raise RuntimeError("deadline_evidence_identity_incomplete")
        if field.get("supporting_field_evidence_ids") != [scope_evidence_id, raw_evidence_id]:
            raise RuntimeError("deadline_supporting_evidence_order_or_identity_mismatch")
        if scope.get("calendar_scope_session_year_field_evidence_id") != scope_evidence_id:
            raise RuntimeError("scope_evidence_id_top_level_mismatch")
        if scope.get("registration_source_field_evidence_id") != raw_evidence_id:
            raise RuntimeError("raw_registration_evidence_id_top_level_mismatch")
        if scope_validation.get("scope_field_evidence_id") != scope_evidence_id:
            raise RuntimeError("validator_scope_evidence_id_mismatch")
        if scope_validation.get("source_registration_window_field_evidence_id") != raw_evidence_id:
            raise RuntimeError("validator_raw_registration_evidence_id_mismatch")

        promotion_evidence_id = _promotion_id(
            str(expected_year),
            scope_deadline,
            deadline_evidence_id,
            scope_evidence_id,
            raw_evidence_id,
            document_text_evidence_id,
            page_hash,
            excerpt,
        )
        candidate = {
            "field": "registration_deadline",
            "value": scope_deadline,
            "normalized_date": True,
            "state": "MATERIALITY_FIELD_PROMOTION_VERIFIED_SHADOW",
            "field_evidence_id": deadline_evidence_id,
            "promotion_evidence_id": promotion_evidence_id,
            "scope_field_evidence_id": scope_evidence_id,
            "source_registration_window_field_evidence_id": raw_evidence_id,
            "supporting_field_evidence_ids": [scope_evidence_id, raw_evidence_id],
            "document_text_evidence_id": document_text_evidence_id,
            "page_number": int(field.get("page_number") or 0),
            "page_text_sha256": page_hash,
            "excerpt": excerpt,
            "contest_session_year": expected_year,
            "material_fact_use": False,
            "materiality_promotion_allowed": True,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        return {
            **_base(),
            "state": "MATERIALITY_PROMOTION_VERIFIED_SHADOW",
            "reason": "independently_validated_same_document_calendar_scope_preserves_exact_deadline_evidence_identity",
            "as_of_date": current.isoformat(),
            "expected_contest_session_year": expected_year,
            "registration_deadline": scope_deadline,
            "registration_deadline_field_evidence_id": deadline_evidence_id,
            "promotion_evidence_id": promotion_evidence_id,
            "materiality_promotion_allowed": True,
            "promotion_candidate_count": 1,
            "promotion_candidates": [candidate],
            "fabricated_claim_count": 0,
            "truth_rule": (
                "This gate may expose the normalized registration_deadline to the separate materiality adjudicator only when the exact deadline field, scope evidence ID, raw registration evidence ID, document evidence ID, page hash and independent scope-validation identities all agree. It does not itself make the deadline a material fact, FactKernel claim, article claim, publication or delivery receipt."
            ),
        }
    except Exception as exc:
        return _blocked("registration_deadline_promotion_gate_failed", detail=f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed ISJ registration-deadline promotion gate for materiality only")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--scope-validation", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    current = date.fromisoformat(args.as_of) if args.as_of else date.today()
    result = build_deadline_promotion(
        json.loads(Path(args.scope).read_text(encoding="utf-8")),
        json.loads(Path(args.scope_validation).read_text(encoding="utf-8")),
        expected_year=args.year,
        as_of=current,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "materiality_promotion_allowed": result.get("materiality_promotion_allowed", False),
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
