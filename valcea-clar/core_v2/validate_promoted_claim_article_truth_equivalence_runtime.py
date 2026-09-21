from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from isj_article_deadline_claim_gate import (
    build_article_deadline_claim_gate as build_retained_gate,
)
from isj_article_integrity import verify_isj_article_integrity
from promoted_claim_article_truth import (
    RETAINED_GATE_IMPLEMENTATION,
    RETAINED_VALIDATOR_IMPLEMENTATION,
    RUNTIME_FACADE_MODE,
    build_promoted_claim_article_truth_gate,
    project_promoted_claim_article_shadow,
    prove_promoted_claim_article_truth_tamper_regressions,
    prove_promoted_claim_projected_tamper_regressions,
    validate_promoted_claim_article_truth_gate,
    validate_promoted_claim_projected_article,
)
from promoted_claim_writer import compose_promoted_claim_article
from validate_isj_article_deadline_claim_gate import (
    project_validated_deadline_claim as project_retained_claim,
    prove_projected_tamper_regressions as prove_retained_projected_tamper,
    prove_tamper_regressions as prove_retained_tamper,
    validate as validate_retained_gate,
    validate_projected_article as validate_retained_projected,
)


def _semantic_bytes(doc: Any) -> bytes:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _semantic_sha256(doc: Any) -> str:
    return hashlib.sha256(_semantic_bytes(doc)).hexdigest()


def _assert_semantic_equal(label: str, left: Any, right: Any) -> None:
    if _semantic_bytes(left) != _semantic_bytes(right):
        raise AssertionError(
            f"{label}_json_semantic_mismatch:{_semantic_sha256(left)}!={_semantic_sha256(right)}"
        )


def _require_no_authority(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"
    assert int(doc.get("fabricated_claim_count") or 0) == 0, f"{label}:fabricated_claim_count"


def validate_equivalence(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    canonical_gate: dict[str, Any],
    canonical_validation: dict[str, Any],
    canonical_article: dict[str, Any],
    canonical_integrity: dict[str, Any],
) -> dict[str, Any]:
    # Recreate the pre-gate writer boundary from the same canonical Core v2 inputs.
    preprojection_article = compose_promoted_claim_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
    )
    _require_no_authority(preprojection_article, "preprojection_article")
    assert preprojection_article.get("article_contains_registration_deadline") is False
    assert int(preprojection_article.get("rendered_promoted_claim_count") or 0) == 1

    retained_gate = build_retained_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
    )
    facade_gate = build_promoted_claim_article_truth_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
    )
    _require_no_authority(retained_gate, "retained_gate")
    _require_no_authority(facade_gate, "facade_gate")
    _assert_semantic_equal("facade_vs_retained_gate", facade_gate, retained_gate)
    _assert_semantic_equal("facade_vs_canonical_gate", facade_gate, canonical_gate)

    gate_id = str(facade_gate.get("article_deadline_claim_evidence_id") or "").strip()
    assert gate_id.startswith("isj-article-deadline-claim-")
    assert len(gate_id) > len("isj-article-deadline-claim-")

    retained_summary = validate_retained_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
        retained_gate,
    )
    facade_summary = validate_promoted_claim_article_truth_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
        facade_gate,
    )
    _require_no_authority(retained_summary, "retained_validation")
    _require_no_authority(facade_summary, "facade_validation")
    _assert_semantic_equal("facade_vs_retained_validation", facade_summary, retained_summary)
    assert facade_summary.get("article_deadline_claim_evidence_id") == gate_id
    assert int(facade_summary.get("verified_claim_candidate_count") or 0) == 1

    retained_tamper = prove_retained_tamper(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
        retained_gate,
    )
    facade_tamper = prove_promoted_claim_article_truth_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        preprojection_article,
        facade_gate,
    )
    assert retained_tamper == 5, f"retained_tamper_expected_5_got_{retained_tamper}"
    assert facade_tamper == 5, f"facade_tamper_expected_5_got_{facade_tamper}"

    retained_projected = project_retained_claim(preprojection_article, retained_gate, retained_summary)
    facade_projected = project_promoted_claim_article_shadow(
        preprojection_article,
        facade_gate,
        facade_summary,
    )
    _require_no_authority(retained_projected, "retained_projected_article")
    _require_no_authority(facade_projected, "facade_projected_article")
    _assert_semantic_equal("facade_vs_retained_projected_article", facade_projected, retained_projected)
    _assert_semantic_equal("facade_vs_canonical_projected_article", facade_projected, canonical_article)
    assert facade_projected.get("article_deadline_claim_evidence_id") == gate_id
    assert facade_projected.get("article_contains_registration_deadline") is True
    assert int(facade_projected.get("canonical_promoted_claim_count") or 0) == 1

    retained_projected_summary = validate_retained_projected(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        retained_projected,
        retained_gate,
    )
    facade_projected_summary = validate_promoted_claim_projected_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        facade_projected,
        facade_gate,
    )
    _require_no_authority(retained_projected_summary, "retained_projected_validation")
    _require_no_authority(facade_projected_summary, "facade_projected_validation")
    _assert_semantic_equal(
        "facade_vs_retained_projected_validation",
        facade_projected_summary,
        retained_projected_summary,
    )
    assert facade_projected_summary.get("article_deadline_claim_evidence_id") == gate_id
    assert int(facade_projected_summary.get("canonical_claim_count") or 0) == 3

    retained_projected_tamper = prove_retained_projected_tamper(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        retained_projected,
        retained_gate,
    )
    facade_projected_tamper = prove_promoted_claim_projected_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        facade_projected,
        facade_gate,
    )
    assert retained_projected_tamper == 3
    assert facade_projected_tamper == 3

    # Bind the facade proof to the actual canonical runtime outputs, not only to
    # generated in-memory documents from the same wrapper.
    _require_no_authority(canonical_validation, "canonical_validation")
    assert canonical_validation.get("status") == "PASS_SHADOW"
    assert canonical_validation.get("article_deadline_claim_evidence_id") == gate_id
    assert int(canonical_validation.get("tamper_regressions_passed") or 0) == 5
    assert int(canonical_validation.get("projected_tamper_regressions_passed") or 0) == 3
    assert int(canonical_validation.get("canonical_claim_count") or 0) == 3
    assert canonical_validation.get("article_contains_registration_deadline") is True

    expected_integrity = verify_isj_article_integrity(
        fact_kernel,
        fact_integrity,
        facade_projected,
    )
    _require_no_authority(expected_integrity, "facade_downstream_integrity")
    _require_no_authority(canonical_integrity, "canonical_downstream_integrity")
    _assert_semantic_equal("facade_vs_canonical_downstream_integrity", expected_integrity, canonical_integrity)
    assert canonical_integrity.get("status") == "PASS_SHADOW"
    assert canonical_integrity.get("article_integrity_verified") is True
    assert canonical_integrity.get("projected_deadline_verified") is True
    assert canonical_integrity.get("article_deadline_claim_evidence_id") == gate_id
    assert int(canonical_integrity.get("verified_claim_count") or 0) == 3
    assert int(canonical_integrity.get("fabricated_claim_count") or 0) == 0

    return {
        "schema_version": "core-v2-promoted-claim-article-truth-facade-equivalence-shadow.v1",
        "status": "PASS_SHADOW",
        "facade_mode": RUNTIME_FACADE_MODE,
        "retained_gate_implementation": RETAINED_GATE_IMPLEMENTATION,
        "retained_validator_implementation": RETAINED_VALIDATOR_IMPLEMENTATION,
        "facade_gate_json_semantic_sha256": _semantic_sha256(facade_gate),
        "retained_gate_json_semantic_sha256": _semantic_sha256(retained_gate),
        "canonical_gate_json_semantic_sha256": _semantic_sha256(canonical_gate),
        "facade_projected_article_json_semantic_sha256": _semantic_sha256(facade_projected),
        "canonical_projected_article_json_semantic_sha256": _semantic_sha256(canonical_article),
        "article_deadline_claim_evidence_id": gate_id,
        "verified_claim_candidate_count": 1,
        "tamper_regressions_passed": 5,
        "projected_tamper_regressions_passed": 3,
        "downstream_verified_claim_count": 3,
        "downstream_fabricated_claim_count": 0,
        "canonical_runtime_switched": False,
        "retained_implementations_retirement_eligible": False,
        "retirement_authority": "NONE",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": (
            "The source-neutral promoted-claim article-truth facade is JSON-semantically identical to the retained "
            "ISJ gate and validator on the same canonical inputs, preserves the exact article-claim evidence identity, "
            "passes all 5/5 preprojection and 3/3 projected tamper regressions, and reproduces the canonical downstream "
            "3-verified/0-fabricated article integrity result. This proof is parallel CI evidence only: canonical runtime "
            "is not switched and no publication, acceptance, deployment, merge or retirement authority is granted."
        ),
    }


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"expected_json_object:{path}")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove source-neutral promoted-claim article-truth facade equivalence without switching canonical runtime"
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--canonical-gate", required=True)
    parser.add_argument("--canonical-validation", required=True)
    parser.add_argument("--canonical-article", required=True)
    parser.add_argument("--canonical-integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = validate_equivalence(
        _load(args.fact_kernel),
        _load(args.fact_kernel_integrity),
        _load(args.writer_consumption),
        _load(args.writer_consumption_validation),
        _load(args.canonical_gate),
        _load(args.canonical_validation),
        _load(args.canonical_article),
        _load(args.canonical_integrity),
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "article_deadline_claim_evidence_id": report["article_deadline_claim_evidence_id"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "projected_tamper_regressions_passed": report["projected_tamper_regressions_passed"],
        "downstream_verified_claim_count": report["downstream_verified_claim_count"],
        "downstream_fabricated_claim_count": report["downstream_fabricated_claim_count"],
        "canonical_runtime_switched": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
