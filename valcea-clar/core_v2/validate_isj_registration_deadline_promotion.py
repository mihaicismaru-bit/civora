from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _promotion_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-deadline-promotion-{digest[:24]}"


def _require_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("fact_kernel_promotion_allowed") is False, f"{label}:fact_kernel_promotion_allowed"
    assert doc.get("writer_allowed") is False, f"{label}:writer_allowed"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def _deadline_field(scope: dict[str, Any], expected_year: int) -> dict[str, Any]:
    rows = [
        row for row in (scope.get("rows") or [])
        if isinstance(row, dict)
        and row.get("state") == "CALENDAR_SCOPE_BINDING_VERIFIED_SHADOW"
        and row.get("contest_session_year") == expected_year
    ]
    assert len(rows) == 1, f"scope row cardinality={len(rows)}"
    fields = [
        field for field in (rows[0].get("fields") or [])
        if isinstance(field, dict) and field.get("field") == "registration_deadline"
    ]
    assert len(fields) == 1, f"deadline field cardinality={len(fields)}"
    return fields[0]


def validate(
    scope: dict[str, Any],
    scope_validation: dict[str, Any],
    promotion: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    _require_boundary(scope, "scope")
    _require_boundary(scope_validation, "scope_validation")
    _require_boundary(promotion, "promotion")

    assert scope.get("same_document_year_scope_verified") is True
    assert scope.get("registration_deadline_normalized") is True
    assert scope.get("expected_contest_session_year") == expected_year
    assert scope_validation.get("status") == "PASS_SHADOW"
    assert scope_validation.get("same_document_year_scope_verified") is True
    assert promotion.get("state") == "MATERIALITY_PROMOTION_VERIFIED_SHADOW"
    assert promotion.get("materiality_promotion_allowed") is True
    assert int(promotion.get("promotion_candidate_count") or 0) == 1
    assert int(promotion.get("fabricated_claim_count") or 0) == 0

    deadline = str(scope.get("registration_deadline") or "")
    assert deadline and deadline == scope_validation.get("registration_deadline") == promotion.get("registration_deadline")
    assert deadline.startswith(f"{expected_year}-")

    source_field = _deadline_field(scope, expected_year)
    assert source_field.get("state") == "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW"
    assert source_field.get("normalized_date") is True
    assert source_field.get("value") == deadline
    assert source_field.get("material_fact_use") is False
    assert source_field.get("fact_kernel_promotion_allowed") is False
    assert source_field.get("writer_allowed") is False

    deadline_evidence_id = str(source_field.get("field_evidence_id") or "")
    scope_evidence_id = str(source_field.get("scope_field_evidence_id") or "")
    raw_evidence_id = str(source_field.get("source_registration_window_field_evidence_id") or "")
    document_text_evidence_id = str(source_field.get("document_text_evidence_id") or "")
    page_hash = str(source_field.get("page_text_sha256") or "")
    excerpt = _norm(source_field.get("excerpt"))
    assert all((deadline_evidence_id, scope_evidence_id, raw_evidence_id, document_text_evidence_id, page_hash, excerpt))
    assert source_field.get("supporting_field_evidence_ids") == [scope_evidence_id, raw_evidence_id]
    assert scope.get("calendar_scope_session_year_field_evidence_id") == scope_evidence_id
    assert scope.get("registration_source_field_evidence_id") == raw_evidence_id
    assert scope_validation.get("scope_field_evidence_id") == scope_evidence_id
    assert scope_validation.get("source_registration_window_field_evidence_id") == raw_evidence_id

    candidates = promotion.get("promotion_candidates") or []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.get("field") == "registration_deadline"
    assert candidate.get("state") == "MATERIALITY_FIELD_PROMOTION_VERIFIED_SHADOW"
    assert candidate.get("value") == deadline
    assert candidate.get("normalized_date") is True
    assert candidate.get("field_evidence_id") == deadline_evidence_id
    assert candidate.get("scope_field_evidence_id") == scope_evidence_id
    assert candidate.get("source_registration_window_field_evidence_id") == raw_evidence_id
    assert candidate.get("supporting_field_evidence_ids") == [scope_evidence_id, raw_evidence_id]
    assert candidate.get("document_text_evidence_id") == document_text_evidence_id
    assert candidate.get("page_text_sha256") == page_hash
    assert _norm(candidate.get("excerpt")) == excerpt
    assert candidate.get("contest_session_year") == expected_year
    assert candidate.get("material_fact_use") is False
    assert candidate.get("materiality_promotion_allowed") is True
    assert candidate.get("fact_kernel_promotion_allowed") is False
    assert candidate.get("writer_allowed") is False
    assert candidate.get("site_publish_allowed") is False
    assert candidate.get("social_publish_allowed") is False

    expected_promotion_id = _promotion_id(
        str(expected_year),
        deadline,
        deadline_evidence_id,
        scope_evidence_id,
        raw_evidence_id,
        document_text_evidence_id,
        page_hash,
        excerpt,
    )
    assert promotion.get("promotion_evidence_id") == expected_promotion_id
    assert promotion.get("registration_deadline_field_evidence_id") == deadline_evidence_id
    assert candidate.get("promotion_evidence_id") == expected_promotion_id

    return {
        "status": "PASS_SHADOW",
        "registration_deadline": deadline,
        "registration_deadline_field_evidence_id": deadline_evidence_id,
        "promotion_evidence_id": expected_promotion_id,
        "materiality_promotion_allowed": True,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    scope: dict[str, Any],
    scope_validation: dict[str, Any],
    promotion: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> int:
    cases: list[tuple[str, dict[str, Any]]] = []

    deadline_tamper = copy.deepcopy(promotion)
    deadline_tamper["promotion_candidates"][0]["value"] = f"{expected_year}-10-03"
    cases.append(("candidate deadline changed without evidence", deadline_tamper))

    evidence_tamper = copy.deepcopy(promotion)
    evidence_tamper["promotion_candidates"][0]["field_evidence_id"] = "isj-calendar-scope-tampered"
    cases.append(("deadline field evidence id detached", evidence_tamper))

    page_hash_tamper = copy.deepcopy(promotion)
    page_hash_tamper["promotion_candidates"][0]["page_text_sha256"] = "0" * 64
    cases.append(("deadline page hash detached", page_hash_tamper))

    passed = 0
    for label, tampered in cases:
        try:
            validate(scope, scope_validation, tampered, expected_year=expected_year)
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"deadline promotion validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate ISJ registration-deadline materiality-promotion evidence")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--scope-validation", required=True)
    parser.add_argument("--promotion", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scope = json.loads(Path(args.scope).read_text(encoding="utf-8"))
    scope_validation = json.loads(Path(args.scope_validation).read_text(encoding="utf-8"))
    promotion = json.loads(Path(args.promotion).read_text(encoding="utf-8"))
    summary = validate(scope, scope_validation, promotion, expected_year=args.year)
    tamper_passed = prove_tamper_regressions(scope, scope_validation, promotion, expected_year=args.year) if args.prove_tamper else 0
    report = {
        "schema_version": "1.0",
        "mode": "ISJ_REGISTRATION_DEADLINE_PROMOTION_VALIDATION",
        **summary,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": tamper_passed,
        "material_fact_use": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": "Materiality may consume the deadline promotion only if this independent validator reproduces the exact deadline, field evidence ID, scope evidence ID, raw registration evidence ID, document evidence ID, page hash and promotion evidence ID. This validator grants no FactKernel, writer, publication or delivery authority.",
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "registration_deadline": report["registration_deadline"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "materiality_promotion_allowed": True,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
