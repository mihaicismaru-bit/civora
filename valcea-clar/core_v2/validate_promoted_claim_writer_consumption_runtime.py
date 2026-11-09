from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

COMPATIBILITY_IDENTITY_PREFIX = "isj-writer-deadline-consumption"
IDENTITY_KEYS = (
    "field_evidence_id",
    "scope_field_evidence_id",
    "source_registration_window_field_evidence_id",
    "document_text_evidence_id",
    "upstream_materiality_promotion_evidence_id",
    "fact_kernel_promotion_evidence_id",
    "page_text_sha256",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _consumption_id(*parts: str, identity_prefix: str = COMPATIBILITY_IDENTITY_PREFIX) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{identity_prefix}-{digest[:24]}"


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("production_writer_ready") is False, f"{label}:production_writer_ready"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def validate_promoted_claim_writer_consumption(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    consumption: dict[str, Any],
    *,
    expected_year: int = 2026,
    identity_prefix: str = COMPATIBILITY_IDENTITY_PREFIX,
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

    assert fact_integrity.get("status") == "PASS_SHADOW"
    assert fact_integrity.get("fact_kernel_integrity_verified") is True
    assert int(fact_integrity.get("promoted_fact_verified_count") or 0) == 1
    assert int(fact_integrity.get("fabricated_claim_count") or 0) == 0

    assert projection.get("state") == "WRITER_PROJECTION_VERIFIED_SHADOW"
    assert int(projection.get("projection_candidate_count") or 0) == 1
    assert projection.get("writer_allowed") is False
    assert projection.get("article_projection_allowed") is False
    projection_id = _norm(projection.get("writer_projection_evidence_id"))
    assert projection_id

    assert projection_validation.get("status") == "PASS_SHADOW"
    assert _norm(projection_validation.get("writer_projection_evidence_id")) == projection_id
    assert int(projection_validation.get("verified_projection_candidate_count") or 0) == 1
    assert int(projection_validation.get("fabricated_claim_count") or 0) == 0
    assert int(projection_validation.get("tamper_regressions_passed") or 0) >= 4

    candidates = projection.get("projection_candidates") or []
    assert len(candidates) == 1 and isinstance(candidates[0], dict)
    candidate = candidates[0]
    assert _norm(candidate.get("writer_projection_evidence_id")) == projection_id
    claim_field = _norm(candidate.get("field"))
    claim_value = _norm(candidate.get("value"))
    claim = _norm(candidate.get("claim"))
    assert claim_field and claim_value and claim
    assert claim_field == _norm(source.get("field"))
    assert claim_value == _norm(source.get("value"))
    assert claim == _norm(source.get("claim"))

    identities = {key: _norm(candidate.get(key)) for key in IDENTITY_KEYS}
    assert all(identities.values())
    for key, value in identities.items():
        assert _norm(source.get(key)) == value, key
    claim_evidence_ids = [_norm(v) for v in candidate.get("claim_evidence_ids") or [] if _norm(v)]
    supporting = [_norm(v) for v in candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]
    assert claim_evidence_ids == [_norm(v) for v in source.get("claim_evidence_ids") or [] if _norm(v)]
    assert supporting == [_norm(v) for v in source.get("supporting_field_evidence_ids") or [] if _norm(v)]
    page_number = int(candidate.get("page_number") or 0)
    excerpt = _norm(candidate.get("excerpt"))
    assert page_number > 0 and excerpt
    assert int(source.get("page_number") or 0) == page_number
    assert _norm(source.get("excerpt")) == excerpt

    expected_consumption_id = _consumption_id(
        projection_id,
        str(expected_year),
        claim_value,
        claim,
        *claim_evidence_ids,
        identities["upstream_materiality_promotion_evidence_id"],
        identities["page_text_sha256"],
        str(page_number),
        excerpt,
        identity_prefix=identity_prefix,
    )

    assert consumption.get("schema_version") == "core-v2-promoted-claim-writer-consumption-shadow.v1"
    assert consumption.get("mode") == "PROMOTED_CLAIM_WRITER_CONSUMPTION_SHADOW"
    assert consumption.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert consumption.get("claim_field") == claim_field
    assert _norm(consumption.get("claim_value")) == claim_value
    assert _norm(consumption.get("writer_projection_evidence_id")) == projection_id
    assert _norm(consumption.get("writer_consumption_evidence_id")) == expected_consumption_id
    assert consumption.get("shadow_writer_consumption_allowed") is True
    assert consumption.get("writer_allowed") is False
    assert consumption.get("article_projection_allowed") is False
    assert int(consumption.get("consumption_candidate_count") or 0) == 1
    assert int(consumption.get("fabricated_claim_count") or 0) == 0
    assert consumption.get("builder_source_neutral") is True
    assert consumption.get("consumption_lineage_verified") is True
    assert consumption.get("writer_used_only_validated_projection") is True
    assert consumption.get("canonical_writer_consumption_builder_path") == "SOURCE_NEUTRAL_MODULE"
    assert consumption.get("legacy_module_path_required_for_canonical_runtime") is False
    assert consumption.get("source_specific_builder_canonical_producer") is False
    assert consumption.get("source_specific_comparator_runtime_dependency") is False

    rows = consumption.get("consumption_candidates") or []
    assert len(rows) == 1 and isinstance(rows[0], dict)
    out = rows[0]
    assert _norm(out.get("field")) == claim_field
    assert _norm(out.get("value")) == claim_value
    assert _norm(out.get("claim")) == claim
    assert _norm(out.get("writer_projection_evidence_id")) == projection_id
    assert _norm(out.get("writer_consumption_evidence_id")) == expected_consumption_id
    for key, value in identities.items():
        assert _norm(out.get(key)) == value, key
    assert [_norm(v) for v in out.get("claim_evidence_ids") or [] if _norm(v)] == claim_evidence_ids
    assert [_norm(v) for v in out.get("supporting_field_evidence_ids") or [] if _norm(v)] == supporting
    assert int(out.get("page_number") or 0) == page_number
    assert _norm(out.get("excerpt")) == excerpt

    return {
        "schema_version": "core-v2-promoted-claim-writer-consumption-validation-shadow.v1",
        "mode": "PROMOTED_CLAIM_WRITER_CONSUMPTION_VALIDATION_SHADOW",
        "status": "PASS_SHADOW",
        "claim_field": claim_field,
        "claim_value": claim_value,
        "registration_deadline": claim_value if claim_field == "registration_deadline" else None,
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
        "validator_source_neutral": True,
        "canonical_writer_consumption_validation_path": "SOURCE_NEUTRAL_RUNTIME",
        "legacy_validator_required_for_canonical_runtime": False,
        "source_specific_comparator_runtime_dependency": False,
    }


def prove_consumption_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    consumption: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> int:
    cases: list[tuple[str, dict[str, Any]]] = []
    projection_id = copy.deepcopy(consumption)
    projection_id["writer_projection_evidence_id"] = "tampered-projection-id"
    cases.append(("projection identity", projection_id))

    evidence = copy.deepcopy(consumption)
    evidence["consumption_candidates"][0]["claim_evidence_ids"] = ["tampered-evidence"]
    cases.append(("claim evidence", evidence))

    consumption_id = copy.deepcopy(consumption)
    consumption_id["writer_consumption_evidence_id"] = "tampered-consumption-id"
    cases.append(("consumption identity", consumption_id))

    lineage = copy.deepcopy(consumption)
    lineage["consumption_candidates"][0]["page_text_sha256"] = "tampered-page-hash"
    cases.append(("lineage hash", lineage))

    passed = 0
    for label, candidate in cases:
        try:
            validate_promoted_claim_writer_consumption(
                fact_kernel, fact_integrity, projection, projection_validation, candidate, expected_year=expected_year
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"source-neutral writer consumption validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate source-neutral promoted-claim writer consumption")
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
    report = validate_promoted_claim_writer_consumption(
        fact_kernel, fact_integrity, projection, projection_validation, consumption, expected_year=args.year
    )
    tamper_passed = prove_consumption_tamper_regressions(
        fact_kernel, fact_integrity, projection, projection_validation, consumption, expected_year=args.year
    ) if args.prove_tamper else 0
    report["tamper_regressions_requested"] = bool(args.prove_tamper)
    report["tamper_regressions_passed"] = tamper_passed
    report["truth_rule"] = (
        "This independent source-neutral validator proves the deterministic writer-consumption identity, promoted-claim lineage and fail-closed authority boundary. "
        "It grants no article, site, social, delivery or acceptance authority."
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "writer_consumption_evidence_id": report["writer_consumption_evidence_id"],
        "tamper_regressions_passed": tamper_passed,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
