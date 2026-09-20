from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from promoted_claim_contract import build_promoted_claim_contract
from validate_promoted_claim_contract import validate_promoted_claim_contract


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm_list(values: Any) -> list[str]:
    return [_norm(v) for v in values or [] if _norm(v)]


def _require_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE" or doc.get("acceptance_ready") is not False:
        raise RuntimeError(f"{label}_authority_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise RuntimeError(f"{label}_publication_path_boundary_violation")


def _require_pass(doc: dict[str, Any], label: str) -> None:
    _require_boundary(doc, label)
    if doc.get("status") != "PASS_SHADOW":
        raise RuntimeError(f"{label}_not_pass_shadow")
    if int(doc.get("fabricated_claim_count") or 0) != 0:
        raise RuntimeError(f"{label}_fabricated_claims_nonzero")


def _one(rows: Any, label: str) -> dict[str, Any]:
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"{label}_expected_one")
    return rows[0]


def derive_expected_lineage_independently(
    *,
    deadline_promotion_validation: dict[str, Any],
    fact_promotion_validation: dict[str, Any],
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_projection_validation: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_claim_gate: dict[str, Any],
    article_claim_validation: dict[str, Any],
    article_integrity: dict[str, Any],
) -> dict[str, Any]:
    _require_pass(deadline_promotion_validation, "deadline_promotion_validation")
    if deadline_promotion_validation.get("materiality_promotion_allowed") is not True:
        raise RuntimeError("deadline_promotion_not_allowed")
    _require_pass(fact_promotion_validation, "fact_promotion_validation")
    if fact_promotion_validation.get("fact_kernel_promotion_allowed") is not True:
        raise RuntimeError("fact_kernel_promotion_not_allowed")
    _require_boundary(fact_kernel, "fact_kernel")
    if fact_kernel.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        raise RuntimeError("fact_kernel_not_verified_shadow")
    _require_pass(fact_integrity, "fact_integrity")
    if fact_integrity.get("fact_kernel_integrity_verified") is not True or int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
        raise RuntimeError("fact_kernel_integrity_missing_promoted_fact")
    _require_pass(writer_projection_validation, "writer_projection_validation")
    if writer_projection_validation.get("writer_deadline_projection_allowed") is not True or int(writer_projection_validation.get("verified_projection_candidate_count") or 0) != 1:
        raise RuntimeError("writer_projection_not_independently_verified")
    _require_pass(writer_consumption_validation, "writer_consumption_validation")
    if writer_consumption_validation.get("shadow_writer_consumption_allowed") is not True or int(writer_consumption_validation.get("verified_consumption_candidate_count") or 0) != 1:
        raise RuntimeError("writer_consumption_not_independently_verified")
    _require_boundary(article_claim_gate, "article_claim_gate")
    if article_claim_gate.get("state") != "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW" or article_claim_gate.get("shadow_article_claim_integrity_passed") is not True:
        raise RuntimeError("article_claim_gate_not_verified_shadow")
    _require_pass(article_claim_validation, "article_claim_validation")
    if article_claim_validation.get("shadow_article_claim_integrity_passed") is not True or int(article_claim_validation.get("verified_claim_candidate_count") or 0) != 1:
        raise RuntimeError("article_claim_not_independently_verified")
    _require_pass(article_integrity, "article_integrity")
    if article_integrity.get("article_integrity_verified") is not True or article_integrity.get("projected_deadline_verified") is not True:
        raise RuntimeError("article_integrity_deadline_not_verified")

    kernel = _one(fact_kernel.get("kernels"), "fact_kernel")
    fact = kernel.get("fact_kernel") or {}
    promoted = _one(kernel.get("promoted_fact_claims"), "promoted_fact_claim")
    candidate = _one(article_claim_gate.get("claim_candidates"), "article_claim_candidate")
    verified_article = _one(article_integrity.get("verified_candidates"), "verified_article")

    story_id = _norm(candidate.get("article_id"))
    source_kind = _norm(fact_kernel.get("source_kind"))
    source_url = _norm(fact.get("source_url"))
    source_name = _norm(fact.get("source"))
    if not story_id or not source_kind or not source_url or not source_name:
        raise RuntimeError("source_identity_incomplete")
    if story_id != _norm(article_claim_validation.get("article_id")) or story_id != _norm(verified_article.get("article_id")):
        raise RuntimeError("story_id_mismatch")
    if source_url != _norm(verified_article.get("source_url")):
        raise RuntimeError("source_url_mismatch")

    value = _norm(candidate.get("value"))
    claim_text = _norm(candidate.get("claim"))
    if candidate.get("field") != "registration_deadline" or promoted.get("field") != "registration_deadline":
        raise RuntimeError("claim_key_mismatch")
    if not value or value != _norm(promoted.get("value")):
        raise RuntimeError("claim_value_mismatch")
    if not claim_text or claim_text != _norm(promoted.get("claim")):
        raise RuntimeError("claim_text_mismatch")

    claim_ids = _norm_list(candidate.get("claim_evidence_ids"))
    support_ids = _norm_list(candidate.get("supporting_field_evidence_ids"))
    if not claim_ids or claim_ids != _norm_list(promoted.get("claim_evidence_ids")):
        raise RuntimeError("claim_evidence_ids_mismatch")
    if not support_ids or support_ids != _norm_list(promoted.get("supporting_field_evidence_ids")):
        raise RuntimeError("supporting_evidence_ids_mismatch")

    values = {
        "materiality_promotion_evidence_id": [candidate.get("upstream_materiality_promotion_evidence_id"), deadline_promotion_validation.get("promotion_evidence_id"), fact_promotion_validation.get("upstream_materiality_promotion_evidence_id")],
        "fact_kernel_promotion_evidence_id": [candidate.get("fact_kernel_promotion_evidence_id"), promoted.get("fact_kernel_promotion_evidence_id"), fact_promotion_validation.get("fact_kernel_promotion_evidence_id")],
        "writer_projection_evidence_id": [candidate.get("writer_projection_evidence_id"), writer_projection_validation.get("writer_projection_evidence_id"), writer_consumption_validation.get("writer_projection_evidence_id"), article_claim_validation.get("writer_projection_evidence_id")],
        "writer_consumption_evidence_id": [candidate.get("writer_consumption_evidence_id"), writer_consumption_validation.get("writer_consumption_evidence_id"), article_claim_validation.get("writer_consumption_evidence_id")],
        "article_claim_evidence_id": [candidate.get("article_deadline_claim_evidence_id"), article_claim_gate.get("article_deadline_claim_evidence_id"), article_claim_validation.get("article_deadline_claim_evidence_id"), article_integrity.get("article_deadline_claim_evidence_id")],
        "document_evidence_id": [candidate.get("document_text_evidence_id"), promoted.get("document_text_evidence_id"), deadline_promotion_validation.get("document_text_evidence_id"), fact_promotion_validation.get("document_text_evidence_id")],
        "document_page": [candidate.get("page_number"), promoted.get("page_number"), deadline_promotion_validation.get("page_number"), fact_promotion_validation.get("page_number")],
        "document_page_sha256": [candidate.get("page_text_sha256"), promoted.get("page_text_sha256"), deadline_promotion_validation.get("page_text_sha256"), fact_promotion_validation.get("page_text_sha256")],
        "document_excerpt": [candidate.get("excerpt"), promoted.get("excerpt"), deadline_promotion_validation.get("excerpt"), fact_promotion_validation.get("excerpt")],
    }
    bound: dict[str, str] = {}
    for key, raw in values.items():
        normed = [_norm(v) for v in raw]
        if not normed[0] or len(set(normed)) != 1:
            raise RuntimeError(f"upstream_identity_mismatch:{key}")
        bound[key] = normed[0]

    if value != _norm(deadline_promotion_validation.get("registration_deadline")) or value != _norm(fact_promotion_validation.get("registration_deadline")):
        raise RuntimeError("deadline_validation_mismatch")
    if value != _norm(writer_projection_validation.get("registration_deadline")) or value != _norm(writer_consumption_validation.get("registration_deadline")):
        raise RuntimeError("writer_deadline_validation_mismatch")
    if value != _norm(article_claim_validation.get("registration_deadline")) or value != _norm(verified_article.get("registration_deadline")):
        raise RuntimeError("article_deadline_validation_mismatch")

    return {
        "story_id": story_id,
        "source_kind": source_kind,
        "claim_key": "registration_deadline",
        "value": value,
        "claim_text": claim_text,
        "claim_evidence_ids": claim_ids,
        "supporting_evidence_ids": support_ids,
        "materiality_promotion_evidence_id": bound["materiality_promotion_evidence_id"],
        "fact_kernel_promotion_evidence_id": bound["fact_kernel_promotion_evidence_id"],
        "writer_projection_evidence_id": bound["writer_projection_evidence_id"],
        "writer_consumption_evidence_id": bound["writer_consumption_evidence_id"],
        "article_claim_evidence_id": bound["article_claim_evidence_id"],
        "document_evidence_id": bound["document_evidence_id"],
        "document_page": int(bound["document_page"]),
        "document_page_sha256": bound["document_page_sha256"].lower(),
        "document_excerpt": bound["document_excerpt"],
        "source_identity": {
            "official_source_name": source_name,
            "official_source_url": source_url,
            "article_id": story_id,
        },
    }


def validate_runtime(contract: dict[str, Any], *, prove_tamper: bool = False, **docs: dict[str, Any]) -> dict[str, Any]:
    try:
        expected = derive_expected_lineage_independently(**docs)
        result = validate_promoted_claim_contract(contract, expected)
        if result.get("status") != "PASS_SHADOW":
            return result
        tamper_passed = 0
        if prove_tamper:
            cases: list[dict[str, Any]] = []
            for key, value in (
                ("article_claim_evidence_id", "detached-article-claim"),
                ("document_page_sha256", "f" * 64),
            ):
                row = deepcopy(contract)
                row[key] = value
                cases.append(row)
            row = deepcopy(contract)
            row["source_identity"] = dict(row.get("source_identity") or {})
            row["source_identity"]["official_source_url"] = "https://example.invalid/detached"
            cases.append(row)
            detached = deepcopy(expected)
            detached["document_page_sha256"] = "e" * 64
            cases.append(build_promoted_claim_contract(**detached))
            for row in cases:
                if validate_promoted_claim_contract(row, expected).get("status") != "BLOCKED":
                    raise RuntimeError("tamper_regression_did_not_fail_closed")
                tamper_passed += 1
        return {
            **result,
            "mode": "ISJ_PROMOTED_CLAIM_CONTRACT_RUNTIME_VALIDATION_SHADOW",
            "source_kind": "isj_valcea",
            "tamper_regressions_requested": bool(prove_tamper),
            "tamper_regressions_passed": tamper_passed,
            "truth_rule": (
                "This source-specific runtime validator independently reconstructs the reusable promoted-claim expected lineage from already "
                "PASS_SHADOW ISJ truth artifacts and then applies the source-neutral validator. It grants no article mutation, publication, "
                "distribution, merge, deployment or acceptance authority."
            ),
        }
    except Exception as exc:
        return {
            "schema_version": "1.0",
            "mode": "ISJ_PROMOTED_CLAIM_CONTRACT_RUNTIME_VALIDATION_SHADOW",
            "status": "BLOCKED",
            "state": "BLOCKED",
            "source_kind": "isj_valcea",
            "reason": "isj_promoted_claim_contract_runtime_validation_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "lineage_complete": False,
            "verified_claim_count": 0,
            "fabricated_claim_count": 0,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "production_write_authority": False,
            "tamper_regressions_requested": bool(prove_tamper),
            "tamper_regressions_passed": 0,
        }


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise RuntimeError(f"expected_object:{path}")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate reusable promoted-claim contract against ISJ upstream truth")
    for name in (
        "deadline-promotion-validation", "fact-promotion-validation", "fact-kernel", "fact-integrity",
        "writer-projection-validation", "writer-consumption-validation", "article-claim-gate",
        "article-claim-validation", "article-integrity", "contract",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate_runtime(
        _load(args.contract),
        deadline_promotion_validation=_load(args.deadline_promotion_validation),
        fact_promotion_validation=_load(args.fact_promotion_validation),
        fact_kernel=_load(args.fact_kernel),
        fact_integrity=_load(args.fact_integrity),
        writer_projection_validation=_load(args.writer_projection_validation),
        writer_consumption_validation=_load(args.writer_consumption_validation),
        article_claim_gate=_load(args.article_claim_gate),
        article_claim_validation=_load(args.article_claim_validation),
        article_integrity=_load(args.article_integrity),
        prove_tamper=args.prove_tamper,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "promoted_claim_contract_id": result.get("promoted_claim_contract_id"),
        "lineage_complete": result.get("lineage_complete"),
        "tamper_regressions_passed": result.get("tamper_regressions_passed"),
        "publication_authority": result.get("publication_authority"),
        "acceptance_ready": result.get("acceptance_ready"),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
