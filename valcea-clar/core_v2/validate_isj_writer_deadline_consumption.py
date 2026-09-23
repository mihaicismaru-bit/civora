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


def _consumption_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-writer-deadline-consumption-{digest[:24]}"


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("production_writer_ready") is False, f"{label}:production_writer_ready"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def _source_neutral_compatibility_view(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    """Return a temporary compatibility view for the legacy-shaped downstream consumer.

    The source-neutral validator remains authoritative for this view. The aliases below
    exist only so the still-ISJ-specific consumption validator can be exercised without
    changing or removing the legacy projection validator in the same increment.
    """
    generic = validate_source_neutral_projection(fact_kernel, fact_integrity, projection)
    assert generic.get("status") == "PASS_SHADOW"
    assert generic.get("field") == "registration_deadline"
    assert generic.get("writer_projection_allowed") is True
    assert generic.get("publication_authority") == "NONE"
    assert generic.get("acceptance_ready") is False
    assert generic.get("site_publish_allowed") is False
    assert generic.get("social_publish_allowed") is False
    assert int(generic.get("verified_projection_candidate_count") or 0) == 1
    assert int(generic.get("fabricated_claim_count") or 0) == 0

    tamper_passed = prove_projection_tamper_regressions(fact_kernel, fact_integrity, projection)
    assert tamper_passed >= 4

    view = dict(generic)
    view.update({
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROJECTION_COMPATIBILITY_VIEW_SHADOW",
        "source_neutral_projection_validation_used_downstream": True,
        "registration_deadline": generic.get("value"),
        "writer_deadline_projection_allowed": generic.get("writer_projection_allowed") is True,
        "article_projection_allowed": False,
        "writer_allowed": False,
        "tamper_regressions_requested": True,
        "tamper_regressions_passed": tamper_passed,
        "legacy_projection_validator_retained": True,
        "retirement_performed": False,
    })
    return view


def validate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    consumption: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    for label, doc in (
        ("fact_kernel", fact_kernel),
        ("fact_integrity", fact_integrity),
        ("projection", projection),
        ("projection_validation", projection_validation),
        ("consumption", consumption),
    ):
        _require_shadow_boundary(doc, label)

    assert fact_kernel.get("state") == "FACT_KERNEL_VERIFIED_SHADOW"
    assert fact_kernel.get("writer_allowed") is False
    assert int(fact_kernel.get("promoted_fact_claim_count") or 0) == 1
    kernels = fact_kernel.get("kernels") or []
    assert len(kernels) == 1 and isinstance(kernels[0], dict)
    promoted = kernels[0].get("promoted_fact_claims") or []
    assert len(promoted) == 1 and isinstance(promoted[0], dict)
    source = promoted[0]
    assert source.get("field") == "registration_deadline"

    assert fact_integrity.get("status") == "PASS_SHADOW"
    assert fact_integrity.get("fact_kernel_integrity_verified") is True
    assert int(fact_integrity.get("promoted_fact_verified_count") or 0) == 1
    assert int(fact_integrity.get("fabricated_claim_count") or 0) == 0

    assert projection.get("state") == "WRITER_PROJECTION_VERIFIED_SHADOW"
    assert projection.get("writer_deadline_projection_allowed") is True
    assert projection.get("writer_allowed") is False
    assert projection.get("article_projection_allowed") is False
    assert int(projection.get("projection_candidate_count") or 0) == 1
    projection_id = str(projection.get("writer_projection_evidence_id") or "")
    assert projection_id

    assert projection_validation.get("status") == "PASS_SHADOW"
    assert projection_validation.get("writer_projection_evidence_id") == projection_id
    assert projection_validation.get("writer_deadline_projection_allowed") is True
    assert projection_validation.get("article_projection_allowed") is False
    assert int(projection_validation.get("verified_projection_candidate_count") or 0) == 1
    assert int(projection_validation.get("fabricated_claim_count") or 0) == 0
    assert int(projection_validation.get("tamper_regressions_passed") or 0) >= 3

    projection_candidates = projection.get("projection_candidates") or []
    assert len(projection_candidates) == 1 and isinstance(projection_candidates[0], dict)
    candidate = projection_candidates[0]
    assert candidate.get("writer_projection_evidence_id") == projection_id
    assert candidate.get("state") == "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW"
    assert candidate.get("writer_deadline_projection_allowed") is True
    assert candidate.get("writer_allowed") is False
    assert candidate.get("article_projection_allowed") is False

    deadline = str(candidate.get("value") or "")
    assert date.fromisoformat(deadline).year == expected_year
    assert projection.get("registration_deadline") == deadline
    assert projection_validation.get("registration_deadline") == deadline
    assert source.get("value") == deadline
    claim = _norm(candidate.get("claim"))
    assert claim and claim == _norm(source.get("claim"))
    assert candidate.get("field") == "registration_deadline"

    identity_keys = (
        "field_evidence_id",
        "scope_field_evidence_id",
        "source_registration_window_field_evidence_id",
        "document_text_evidence_id",
        "upstream_materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "page_text_sha256",
    )
    identities = {key: str(candidate.get(key) or "") for key in identity_keys}
    assert all(identities.values())
    for key, value in identities.items():
        assert str(source.get(key) or "") == value, key

    claim_evidence_ids = [str(v) for v in candidate.get("claim_evidence_ids") or []]
    assert claim_evidence_ids and claim_evidence_ids == [str(v) for v in source.get("claim_evidence_ids") or []]
    supporting = [str(v) for v in candidate.get("supporting_field_evidence_ids") or []]
    assert supporting == [str(v) for v in source.get("supporting_field_evidence_ids") or []]
    page_number = int(candidate.get("page_number") or 0)
    excerpt = _norm(candidate.get("excerpt"))
    assert page_number > 0 and excerpt
    assert int(source.get("page_number") or 0) == page_number
    assert _norm(source.get("excerpt")) == excerpt

    expected_consumption_id = _consumption_id(
        projection_id,
        str(expected_year),
        deadline,
        claim,
        *claim_evidence_ids,
        identities["upstream_materiality_promotion_evidence_id"],
        identities["page_text_sha256"],
        str(page_number),
        excerpt,
    )
    assert consumption.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert consumption.get("registration_deadline") == deadline
    assert consumption.get("writer_projection_evidence_id") == projection_id
    assert consumption.get("writer_consumption_evidence_id") == expected_consumption_id
    assert consumption.get("shadow_writer_consumption_allowed") is True
    assert consumption.get("writer_allowed") is False
    assert consumption.get("article_projection_allowed") is False
    assert int(consumption.get("consumption_candidate_count") or 0) == 1
    assert int(consumption.get("fabricated_claim_count") or 0) == 0

    consumption_candidates = consumption.get("consumption_candidates") or []
    assert len(consumption_candidates) == 1 and isinstance(consumption_candidates[0], dict)
    out = consumption_candidates[0]
    assert out.get("field") == "registration_deadline"
    assert out.get("value") == deadline
    assert _norm(out.get("claim")) == claim
    assert out.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert out.get("writer_projection_evidence_id") == projection_id
    assert out.get("writer_consumption_evidence_id") == expected_consumption_id
    assert out.get("shadow_writer_consumption_allowed") is True
    assert out.get("writer_allowed") is False
    assert out.get("article_projection_allowed") is False
    for key, value in identities.items():
        assert str(out.get(key) or "") == value, key
    assert [str(v) for v in out.get("claim_evidence_ids") or []] == claim_evidence_ids
    assert [str(v) for v in out.get("supporting_field_evidence_ids") or []] == supporting
    assert int(out.get("page_number") or 0) == page_number
    assert _norm(out.get("excerpt")) == excerpt

    return {
        "status": "PASS_SHADOW",
        "registration_deadline": deadline,
        "writer_projection_evidence_id": projection_id,
        "writer_consumption_evidence_id": expected_consumption_id,
        "shadow_writer_consumption_allowed": True,
        "verified_consumption_candidate_count": 1,
        "fabricated_claim_count": 0,
        "writer_allowed": False,
        "production_writer_ready": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    consumption: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> int:
    cases: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    projection_detached = copy.deepcopy(projection)
    projection_detached["writer_projection_evidence_id"] = "isj-writer-deadline-projection-tampered"
    cases.append(("projection identity detached", projection_detached, projection_validation, consumption))

    validation_detached = copy.deepcopy(projection_validation)
    validation_detached["writer_projection_evidence_id"] = "isj-writer-deadline-projection-tampered"
    cases.append(("projection validation identity detached", projection, validation_detached, consumption))

    evidence_detached = copy.deepcopy(consumption)
    evidence_detached["consumption_candidates"][0]["claim_evidence_ids"] = ["tampered-evidence-id"]
    cases.append(("consumption claim evidence detached", projection, projection_validation, evidence_detached))

    consumption_id_detached = copy.deepcopy(consumption)
    consumption_id_detached["writer_consumption_evidence_id"] = "isj-writer-deadline-consumption-tampered"
    cases.append(("consumption identity detached", projection, projection_validation, consumption_id_detached))

    passed = 0
    for label, projection_case, validation_case, consumption_case in cases:
        try:
            validate(
                fact_kernel,
                fact_integrity,
                projection_case,
                validation_case,
                consumption_case,
                expected_year=expected_year,
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"ISJ writer deadline consumption validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate ISJ writer-deadline consumption identity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--projection-validation", required=True)
    parser.add_argument("--consumption", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))
    projection_validation = json.loads(Path(args.projection_validation).read_text(encoding="utf-8"))
    consumption = json.loads(Path(args.consumption).read_text(encoding="utf-8"))

    summary = validate(
        fact_kernel,
        fact_integrity,
        projection,
        projection_validation,
        consumption,
        expected_year=args.year,
    )
    tamper_passed = prove_tamper_regressions(
        fact_kernel,
        fact_integrity,
        projection,
        projection_validation,
        consumption,
        expected_year=args.year,
    ) if args.prove_tamper else 0

    generic_view = _source_neutral_compatibility_view(fact_kernel, fact_integrity, projection)
    generic_summary = validate(
        fact_kernel,
        fact_integrity,
        projection,
        generic_view,
        consumption,
        expected_year=args.year,
    )
    assert generic_summary["writer_projection_evidence_id"] == summary["writer_projection_evidence_id"]
    assert generic_summary["writer_consumption_evidence_id"] == summary["writer_consumption_evidence_id"]
    assert generic_summary["registration_deadline"] == summary["registration_deadline"]
    assert generic_summary["fabricated_claim_count"] == 0
    assert projection_validation.get("writer_projection_evidence_id") == generic_view.get("writer_projection_evidence_id")
    for key in ("publication_authority", "acceptance_ready", "production_writer_ready", "site_publish_allowed", "social_publish_allowed"):
        assert projection_validation.get(key) == generic_view.get(key), key

    report = {
        "schema_version": "1.1",
        "mode": "ISJ_WRITER_DEADLINE_CONSUMPTION_VALIDATION",
        **summary,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": tamper_passed,
        "source_neutral_projection_compatibility_status": "PASS_SHADOW",
        "source_neutral_projection_validation_used_downstream": True,
        "source_neutral_projection_validation_mode": generic_view.get("mode"),
        "source_neutral_projection_tamper_regressions_passed": int(generic_view.get("tamper_regressions_passed") or 0),
        "legacy_projection_validator_retained": True,
        "legacy_and_generic_projection_identity_equivalent": True,
        "legacy_and_generic_authority_flags_equivalent": True,
        "legacy_and_generic_consumption_identity_equivalent": True,
        "replacement_path_enabled": True,
        "retirement_performed": False,
        "truth_rule": (
            "The shadow writer-consumption validator now proves that the same deterministic consumption identity is accepted when its projection-validation dependency is supplied by the source-neutral validator through a bounded compatibility view. "
            "The legacy ISJ projection validator remains active in parallel for comparison, and no validator is retired in this increment. "
            "This compatibility proof grants no article, publication, delivery or acceptance authority."
        ),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "registration_deadline": report["registration_deadline"],
        "shadow_writer_consumption_allowed": report["shadow_writer_consumption_allowed"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "source_neutral_projection_compatibility_status": report["source_neutral_projection_compatibility_status"],
        "source_neutral_projection_tamper_regressions_passed": report["source_neutral_projection_tamper_regressions_passed"],
        "replacement_path_enabled": True,
        "legacy_projection_validator_retained": True,
        "retirement_performed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
