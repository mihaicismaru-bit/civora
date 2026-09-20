from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from promoted_claim_projection_validation import (
    prove_projection_tamper_regressions,
    validate_source_neutral_projection,
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _romanian_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = (
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    )
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"


def _projection_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-writer-deadline-projection-{digest[:24]}"


def validate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    for label, doc in (("fact_kernel", fact_kernel), ("fact_integrity", fact_integrity), ("projection", projection)):
        assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
        assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
        assert doc.get("production_writer_ready") is False, f"{label}:production_writer_ready"
        assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
        assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"

    assert fact_kernel.get("state") == "FACT_KERNEL_VERIFIED_SHADOW"
    assert fact_kernel.get("writer_allowed") is False
    assert fact_kernel.get("fact_kernel_deadline_composition_consumed") is True
    assert int(fact_kernel.get("promoted_fact_claim_count") or 0) == 1

    assert fact_integrity.get("status") == "PASS_SHADOW"
    assert fact_integrity.get("fact_kernel_integrity_verified") is True
    assert fact_integrity.get("writer_allowed") is False
    assert fact_integrity.get("writer_deadline_projection_allowed") is False
    assert fact_integrity.get("writer_gate_status") == "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION"
    assert int(fact_integrity.get("promoted_fact_verified_count") or 0) == 1
    assert int(fact_integrity.get("fabricated_claim_count") or 0) == 0

    kernels = fact_kernel.get("kernels") or []
    assert len(kernels) == 1 and isinstance(kernels[0], dict)
    row = kernels[0]
    assert row.get("integrity_status") == "PENDING_SEPARATE_GATE"
    assert "registration_deadline" in [str(v) for v in row.get("writer_projection_excluded_fields") or []]
    promoted = row.get("promoted_fact_claims") or []
    assert len(promoted) == 1 and isinstance(promoted[0], dict)
    source = promoted[0]
    assert source.get("field") == "registration_deadline"
    assert source.get("state") == "FACT_KERNEL_COMPOSED_SHADOW_PENDING_WRITER_PROJECTION_GATE"
    assert source.get("writer_projection_allowed") is False
    assert source.get("article_projection_allowed") is False

    deadline = str(source.get("value") or "")
    parsed = date.fromisoformat(deadline)
    assert parsed.year == expected_year
    claim = _norm(source.get("claim"))
    assert claim == (
        f"Calendarul oficial verificat pentru sesiunea {expected_year} indică data de "
        f"{_romanian_date(deadline)} ca termen-limită al perioadei de înscriere."
    )

    keys = (
        "field_evidence_id",
        "scope_field_evidence_id",
        "source_registration_window_field_evidence_id",
        "document_text_evidence_id",
        "upstream_materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "page_text_sha256",
    )
    identities = {key: str(source.get(key) or "") for key in keys}
    assert all(identities.values())
    supporting = [str(v) for v in source.get("supporting_field_evidence_ids") or []]
    assert supporting == [identities["scope_field_evidence_id"], identities["source_registration_window_field_evidence_id"]]
    claim_evidence = [
        identities["field_evidence_id"], identities["scope_field_evidence_id"],
        identities["source_registration_window_field_evidence_id"], identities["document_text_evidence_id"],
        identities["fact_kernel_promotion_evidence_id"],
    ]
    assert [str(v) for v in source.get("claim_evidence_ids") or []] == claim_evidence
    page_number = int(source.get("page_number") or 0)
    excerpt = _norm(source.get("excerpt"))
    assert page_number > 0 and excerpt

    base_kernel = row.get("fact_kernel") or {}
    assert claim not in [_norm(v) for v in base_kernel.get("claims") or []]
    base_evidence = [str(v) for v in base_kernel.get("evidence_ids") or []]
    assert len(base_evidence) == 4 and len(set(base_evidence)) == 4
    assert identities["field_evidence_id"] not in base_evidence

    expected_id = _projection_id(
        str(expected_year), deadline, claim, *claim_evidence,
        identities["upstream_materiality_promotion_evidence_id"], identities["page_text_sha256"],
        str(page_number), excerpt,
    )
    assert projection.get("state") == "WRITER_PROJECTION_VERIFIED_SHADOW"
    assert projection.get("registration_deadline") == deadline
    assert projection.get("writer_projection_evidence_id") == expected_id
    assert projection.get("writer_deadline_projection_allowed") is True
    assert projection.get("writer_allowed") is False
    assert projection.get("article_projection_allowed") is False
    assert int(projection.get("projection_candidate_count") or 0) == 1
    assert int(projection.get("fabricated_claim_count") or 0) == 0

    candidates = projection.get("projection_candidates") or []
    assert len(candidates) == 1 and isinstance(candidates[0], dict)
    candidate = candidates[0]
    assert candidate.get("field") == "registration_deadline"
    assert candidate.get("value") == deadline
    assert _norm(candidate.get("claim")) == claim
    assert candidate.get("state") == "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW"
    assert candidate.get("writer_projection_evidence_id") == expected_id
    assert candidate.get("writer_deadline_projection_allowed") is True
    assert candidate.get("writer_allowed") is False
    assert candidate.get("article_projection_allowed") is False
    for key, value in identities.items():
        assert str(candidate.get(key) or "") == value, key
    assert [str(v) for v in candidate.get("supporting_field_evidence_ids") or []] == supporting
    assert [str(v) for v in candidate.get("claim_evidence_ids") or []] == claim_evidence
    assert int(candidate.get("page_number") or 0) == page_number
    assert _norm(candidate.get("excerpt")) == excerpt

    return {
        "status": "PASS_SHADOW",
        "registration_deadline": deadline,
        "writer_projection_evidence_id": expected_id,
        "writer_deadline_projection_allowed": True,
        "article_projection_allowed": False,
        "verified_projection_candidate_count": 1,
        "fabricated_claim_count": 0,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> int:
    cases: list[tuple[str, dict[str, Any]]] = []

    detached_claim_evidence = copy.deepcopy(projection)
    detached_claim_evidence["projection_candidates"][0]["claim_evidence_ids"] = ["tampered-evidence-id"]
    cases.append(("claim evidence detached", detached_claim_evidence))

    page_hash_tamper = copy.deepcopy(projection)
    page_hash_tamper["projection_candidates"][0]["page_text_sha256"] = "0" * 64
    cases.append(("page hash detached", page_hash_tamper))

    projection_id_tamper = copy.deepcopy(projection)
    projection_id_tamper["writer_projection_evidence_id"] = "isj-writer-deadline-projection-tampered"
    cases.append(("projection evidence id detached", projection_id_tamper))

    passed = 0
    for label, projection_case in cases:
        try:
            validate(
                fact_kernel,
                fact_integrity,
                projection_case,
                expected_year=expected_year,
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"ISJ writer deadline projection validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate writer projection with source-neutral canonical dependency and retained legacy equivalence proof")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))

    legacy_summary = validate(
        fact_kernel,
        fact_integrity,
        projection,
        expected_year=args.year,
    )
    legacy_tamper_passed = prove_tamper_regressions(
        fact_kernel,
        fact_integrity,
        projection,
        expected_year=args.year,
    ) if args.prove_tamper else 0

    generic_summary = validate_source_neutral_projection(fact_kernel, fact_integrity, projection)
    assert generic_summary.get("status") == "PASS_SHADOW"
    assert generic_summary.get("field") == "registration_deadline"
    assert generic_summary.get("value") == legacy_summary.get("registration_deadline")
    assert generic_summary.get("writer_projection_evidence_id") == legacy_summary.get("writer_projection_evidence_id")
    assert generic_summary.get("writer_projection_allowed") is True
    assert int(generic_summary.get("verified_projection_candidate_count") or 0) == 1
    assert int(generic_summary.get("fabricated_claim_count") or 0) == 0

    generic_tamper_passed = prove_projection_tamper_regressions(
        fact_kernel,
        fact_integrity,
        projection,
    ) if args.prove_tamper else 0
    if args.prove_tamper:
        assert legacy_tamper_passed >= 3
        assert generic_tamper_passed >= 4

    for key in (
        "publication_authority",
        "acceptance_ready",
        "production_writer_ready",
        "site_publish_allowed",
        "social_publish_allowed",
        "fabricated_claim_count",
    ):
        assert generic_summary.get(key) == legacy_summary.get(key), key

    report = {
        "schema_version": "1.1",
        **generic_summary,
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_PROJECTION_VALIDATION_RUNTIME",
        "registration_deadline": generic_summary.get("value"),
        "writer_deadline_projection_allowed": generic_summary.get("writer_projection_allowed") is True,
        "article_projection_allowed": False,
        "writer_allowed": False,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": generic_tamper_passed,
        "legacy_projection_validator_status": legacy_summary.get("status"),
        "legacy_projection_tamper_regressions_passed": legacy_tamper_passed,
        "legacy_projection_validator_retained": True,
        "legacy_projection_validator_parallel_comparison": True,
        "legacy_and_generic_projection_identity_equivalent": True,
        "legacy_and_generic_authority_flags_equivalent": True,
        "canonical_projection_validation_path": "SOURCE_NEUTRAL",
        "source_neutral_projection_validation_used_downstream": True,
        "replacement_path_enabled": True,
        "retirement_performed": False,
        "truth_rule": (
            "The runtime projection-validation artifact consumed by downstream writer-consumption is now source-neutral and is derived independently from the promoted FactKernel lineage. "
            "The legacy ISJ validator still runs in parallel inside this boundary and must reproduce the same projection identity, authority flags and PASS_SHADOW result. "
            "Both validators must fail closed under their tamper suites. No legacy validator is retired here, and this switch grants no article, publication, delivery or acceptance authority."
        ),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "canonical_projection_validation_path": report["canonical_projection_validation_path"],
        "registration_deadline": report["registration_deadline"],
        "writer_projection_evidence_id": report["writer_projection_evidence_id"],
        "writer_deadline_projection_allowed": report["writer_deadline_projection_allowed"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "legacy_projection_validator_retained": True,
        "retirement_performed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
