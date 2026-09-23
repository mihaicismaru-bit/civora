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
    return f"isj-fact-kernel-deadline-promotion-{digest[:24]}"


def _require_upstream_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("fact_kernel_promotion_allowed") is False, f"{label}:fact_kernel_promotion_allowed"
    assert doc.get("writer_allowed") is False, f"{label}:writer_allowed"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def validate(
    materiality: dict[str, Any],
    materiality_promotion: dict[str, Any],
    materiality_promotion_validation: dict[str, Any],
    fact_promotion: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    _require_upstream_boundary(materiality, "materiality")
    _require_upstream_boundary(materiality_promotion, "materiality_promotion")
    _require_upstream_boundary(materiality_promotion_validation, "materiality_promotion_validation")

    assert fact_promotion.get("publication_authority") == "NONE"
    assert fact_promotion.get("acceptance_ready") is False
    assert fact_promotion.get("state") == "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW"
    assert fact_promotion.get("material_fact_use") is True
    assert fact_promotion.get("fact_kernel_promotion_allowed") is True
    assert fact_promotion.get("writer_allowed") is False
    assert fact_promotion.get("site_publish_allowed") is False
    assert fact_promotion.get("social_publish_allowed") is False
    assert int(fact_promotion.get("promotion_candidate_count") or 0) == 1
    assert int(fact_promotion.get("fabricated_claim_count") or 0) == 0

    assert materiality.get("state") == "MATERIALITY_CANDIDATE_SHADOW"
    assert materiality.get("registration_deadline_materiality_consumed") is True
    materiality_candidates = materiality.get("materiality_candidates") or []
    assert len(materiality_candidates) == 1
    materiality_candidate = materiality_candidates[0]
    assert materiality_candidate.get("category") == "LOCAL_EDUCATION_LEADERSHIP"
    assert materiality_candidate.get("fact_kernel_status") == "NOT_PROMOTED"
    existing_ids = [str(v) for v in materiality_candidate.get("field_evidence_ids") or []]
    assert len(existing_ids) == 4 and len(set(existing_ids)) == 4
    assert "registration_deadline" in [
        str(v) for v in materiality_candidate.get("excluded_unverified_or_non_normalized_fields") or []
    ]

    promoted = (materiality_candidate.get("materiality_only_promoted_fields") or {}).get("registration_deadline")
    assert isinstance(promoted, dict)
    deadline = str(materiality.get("registration_deadline") or "")
    assert deadline and deadline.startswith(f"{expected_year}-")
    assert materiality_candidate.get("registration_deadline") == deadline
    assert promoted.get("value") == deadline

    promotion_candidates = materiality_promotion.get("promotion_candidates") or []
    assert materiality_promotion.get("state") == "MATERIALITY_PROMOTION_VERIFIED_SHADOW"
    assert materiality_promotion.get("materiality_promotion_allowed") is True
    assert len(promotion_candidates) == 1
    upstream = promotion_candidates[0]
    assert upstream.get("field") == "registration_deadline"
    assert upstream.get("value") == deadline
    assert materiality_promotion_validation.get("status") == "PASS_SHADOW"
    assert materiality_promotion_validation.get("materiality_promotion_allowed") is True
    assert materiality_promotion_validation.get("registration_deadline") == deadline

    upstream_promotion_id = str(materiality.get("registration_deadline_promotion_evidence_id") or "")
    assert upstream_promotion_id
    assert upstream_promotion_id == materiality_promotion.get("promotion_evidence_id")
    assert upstream_promotion_id == materiality_promotion_validation.get("promotion_evidence_id")
    assert upstream_promotion_id == promoted.get("promotion_evidence_id")
    assert upstream_promotion_id == upstream.get("promotion_evidence_id")

    field_evidence_id = str(promoted.get("field_evidence_id") or "")
    scope_id = str(promoted.get("scope_field_evidence_id") or "")
    raw_id = str(promoted.get("source_registration_window_field_evidence_id") or "")
    document_id = str(promoted.get("document_text_evidence_id") or "")
    page_hash = str(promoted.get("page_text_sha256") or "")
    excerpt = _norm(promoted.get("excerpt"))
    page_number = int(promoted.get("page_number") or 0)
    supporting = list(promoted.get("supporting_field_evidence_ids") or [])
    assert all((field_evidence_id, scope_id, raw_id, document_id, page_hash, excerpt))
    assert page_number > 0
    assert supporting == [scope_id, raw_id]
    assert field_evidence_id not in existing_ids

    for key, value in (
        ("field_evidence_id", field_evidence_id),
        ("scope_field_evidence_id", scope_id),
        ("source_registration_window_field_evidence_id", raw_id),
        ("document_text_evidence_id", document_id),
        ("page_text_sha256", page_hash),
    ):
        assert upstream.get(key) == value
        validation_key = "registration_deadline_field_evidence_id" if key == "field_evidence_id" else key
        assert materiality_promotion_validation.get(validation_key) == value
    assert upstream.get("supporting_field_evidence_ids") == supporting
    assert materiality_promotion_validation.get("supporting_field_evidence_ids") == supporting
    assert _norm(upstream.get("excerpt")) == excerpt
    assert _norm(materiality_promotion_validation.get("excerpt")) == excerpt
    assert int(upstream.get("page_number") or 0) == page_number
    assert int(materiality_promotion_validation.get("page_number") or 0) == page_number

    expected_fact_promotion_id = _promotion_id(
        str(expected_year),
        deadline,
        upstream_promotion_id,
        field_evidence_id,
        scope_id,
        raw_id,
        document_id,
        page_hash,
        str(materiality_candidate.get("category") or ""),
        ",".join(existing_ids),
        excerpt,
    )
    assert fact_promotion.get("registration_deadline") == deadline
    assert fact_promotion.get("registration_deadline_field_evidence_id") == field_evidence_id
    assert fact_promotion.get("upstream_materiality_promotion_evidence_id") == upstream_promotion_id
    assert fact_promotion.get("fact_kernel_promotion_evidence_id") == expected_fact_promotion_id

    candidates = fact_promotion.get("promotion_candidates") or []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.get("field") == "registration_deadline"
    assert candidate.get("state") == "FACT_KERNEL_FIELD_PROMOTION_VERIFIED_SHADOW"
    assert candidate.get("value") == deadline
    assert candidate.get("field_evidence_id") == field_evidence_id
    assert candidate.get("upstream_materiality_promotion_evidence_id") == upstream_promotion_id
    assert candidate.get("fact_kernel_promotion_evidence_id") == expected_fact_promotion_id
    assert candidate.get("scope_field_evidence_id") == scope_id
    assert candidate.get("source_registration_window_field_evidence_id") == raw_id
    assert candidate.get("supporting_field_evidence_ids") == supporting
    assert candidate.get("document_text_evidence_id") == document_id
    assert int(candidate.get("page_number") or 0) == page_number
    assert candidate.get("page_text_sha256") == page_hash
    assert _norm(candidate.get("excerpt")) == excerpt
    assert candidate.get("materiality_category") == "LOCAL_EDUCATION_LEADERSHIP"
    assert candidate.get("existing_fact_kernel_field_evidence_ids") == existing_ids
    assert candidate.get("material_fact_use") is True
    assert candidate.get("fact_kernel_promotion_allowed") is True
    assert candidate.get("writer_allowed") is False
    assert candidate.get("site_publish_allowed") is False
    assert candidate.get("social_publish_allowed") is False

    return {
        "status": "PASS_SHADOW",
        "registration_deadline": deadline,
        "registration_deadline_field_evidence_id": field_evidence_id,
        "upstream_materiality_promotion_evidence_id": upstream_promotion_id,
        "fact_kernel_promotion_evidence_id": expected_fact_promotion_id,
        "scope_field_evidence_id": scope_id,
        "source_registration_window_field_evidence_id": raw_id,
        "supporting_field_evidence_ids": supporting,
        "document_text_evidence_id": document_id,
        "page_number": page_number,
        "page_text_sha256": page_hash,
        "excerpt": excerpt,
        "material_fact_use": True,
        "fact_kernel_promotion_allowed": True,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    materiality: dict[str, Any],
    materiality_promotion: dict[str, Any],
    materiality_promotion_validation: dict[str, Any],
    fact_promotion: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> int:
    cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    changed_deadline_materiality = copy.deepcopy(materiality)
    changed_deadline_materiality["registration_deadline"] = f"{expected_year}-10-03"
    cases.append(("materiality deadline changed without evidence", changed_deadline_materiality, copy.deepcopy(fact_promotion)))

    detached_upstream = copy.deepcopy(fact_promotion)
    detached_upstream["promotion_candidates"][0]["upstream_materiality_promotion_evidence_id"] = "isj-deadline-promotion-tampered"
    cases.append(("upstream promotion evidence id detached", copy.deepcopy(materiality), detached_upstream))

    page_hash_tamper = copy.deepcopy(fact_promotion)
    page_hash_tamper["promotion_candidates"][0]["page_text_sha256"] = "0" * 64
    cases.append(("page hash detached", copy.deepcopy(materiality), page_hash_tamper))

    passed = 0
    for label, materiality_case, promotion_case in cases:
        try:
            validate(
                materiality_case,
                materiality_promotion,
                materiality_promotion_validation,
                promotion_case,
                expected_year=expected_year,
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"FactKernel deadline promotion validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate ISJ materiality-to-FactKernel registration-deadline promotion")
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--materiality-promotion", required=True)
    parser.add_argument("--materiality-promotion-validation", required=True)
    parser.add_argument("--fact-promotion", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    materiality = json.loads(Path(args.materiality).read_text(encoding="utf-8"))
    materiality_promotion = json.loads(Path(args.materiality_promotion).read_text(encoding="utf-8"))
    materiality_promotion_validation = json.loads(Path(args.materiality_promotion_validation).read_text(encoding="utf-8"))
    fact_promotion = json.loads(Path(args.fact_promotion).read_text(encoding="utf-8"))
    summary = validate(
        materiality,
        materiality_promotion,
        materiality_promotion_validation,
        fact_promotion,
        expected_year=args.year,
    )
    tamper_passed = prove_tamper_regressions(
        materiality,
        materiality_promotion,
        materiality_promotion_validation,
        fact_promotion,
        expected_year=args.year,
    ) if args.prove_tamper else 0
    report = {
        "schema_version": "1.0",
        "mode": "ISJ_FACT_KERNEL_DEADLINE_PROMOTION_VALIDATION",
        **summary,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": tamper_passed,
        "truth_rule": (
            "FactKernel composition may consume the deadline only if this independent validator reproduces the exact materiality value, upstream promotion evidence ID, supporting evidence identities and deterministic FactKernel promotion evidence ID. "
            "This validator grants no writer, article, publication, delivery or acceptance authority."
        ),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "registration_deadline": report["registration_deadline"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "fact_kernel_promotion_allowed": True,
        "writer_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
