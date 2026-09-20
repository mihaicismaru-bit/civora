from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from promoted_claim_contract import build_promoted_claim_contract


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm_list(values: Any) -> list[str]:
    return [_norm(v) for v in values or [] if _norm(v)]


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise RuntimeError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise RuntimeError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise RuntimeError(f"{label}_publication_path_boundary_violation")


def _require_pass(doc: dict[str, Any], label: str, *, flag: str | None = None, count_key: str | None = None) -> None:
    _require_shadow_boundary(doc, label)
    if doc.get("status") != "PASS_SHADOW":
        raise RuntimeError(f"{label}_not_pass_shadow")
    if flag and doc.get(flag) is not True:
        raise RuntimeError(f"{label}_{flag}_not_true")
    if count_key and int(doc.get(count_key) or 0) != 1:
        raise RuntimeError(f"{label}_{count_key}_mismatch")
    if int(doc.get("fabricated_claim_count") or 0) != 0:
        raise RuntimeError(f"{label}_fabricated_claims_nonzero")


def _single_dict(rows: Any, label: str) -> dict[str, Any]:
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"{label}_expected_one")
    return rows[0]


def derive_isj_expected_lineage(
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
    """Derive reusable-contract truth only from already independently validated ISJ artifacts."""
    _require_pass(deadline_promotion_validation, "deadline_promotion_validation", flag="materiality_promotion_allowed")
    _require_pass(fact_promotion_validation, "fact_promotion_validation", flag="fact_kernel_promotion_allowed")
    _require_shadow_boundary(fact_kernel, "fact_kernel")
    if fact_kernel.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        raise RuntimeError("fact_kernel_not_verified_shadow")
    if fact_kernel.get("writer_allowed") is not False:
        raise RuntimeError("fact_kernel_writer_boundary_violation")
    _require_pass(fact_integrity, "fact_integrity", flag="fact_kernel_integrity_verified")
    if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
        raise RuntimeError("fact_integrity_promoted_fact_count_mismatch")
    _require_pass(writer_projection_validation, "writer_projection_validation", flag="writer_deadline_projection_allowed", count_key="verified_projection_candidate_count")
    _require_pass(writer_consumption_validation, "writer_consumption_validation", flag="shadow_writer_consumption_allowed", count_key="verified_consumption_candidate_count")
    _require_shadow_boundary(article_claim_gate, "article_claim_gate")
    if article_claim_gate.get("state") != "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW":
        raise RuntimeError("article_claim_gate_not_verified_shadow")
    if article_claim_gate.get("shadow_article_claim_integrity_passed") is not True:
        raise RuntimeError("article_claim_gate_integrity_not_passed")
    if int(article_claim_gate.get("claim_candidate_count") or 0) != 1:
        raise RuntimeError("article_claim_gate_candidate_count_mismatch")
    _require_pass(article_claim_validation, "article_claim_validation", flag="shadow_article_claim_integrity_passed", count_key="verified_claim_candidate_count")
    if article_claim_validation.get("article_contains_registration_deadline") is not True:
        raise RuntimeError("article_claim_validation_deadline_not_projected")
    _require_pass(article_integrity, "article_integrity", flag="article_integrity_verified")
    if article_integrity.get("projected_deadline_verified") is not True:
        raise RuntimeError("article_integrity_deadline_not_verified")
    if article_integrity.get("article_contains_registration_deadline") is not True:
        raise RuntimeError("article_integrity_deadline_not_present")
    if int(article_integrity.get("verified_claim_count") or 0) < 3:
        raise RuntimeError("article_integrity_claim_count_too_low")

    kernel_row = _single_dict(fact_kernel.get("kernels"), "fact_kernel")
    fact = kernel_row.get("fact_kernel") or {}
    if not isinstance(fact, dict):
        raise RuntimeError("fact_kernel_payload_missing")
    promoted = _single_dict(kernel_row.get("promoted_fact_claims"), "promoted_fact_claim")
    candidate = _single_dict(article_claim_gate.get("claim_candidates"), "article_claim_candidate")
    verified = _single_dict(article_integrity.get("verified_candidates"), "article_integrity_candidate")

    if candidate.get("field") != "registration_deadline" or promoted.get("field") != "registration_deadline":
        raise RuntimeError("registration_deadline_claim_missing")

    cross_checks = {
        "value": (
            candidate.get("value"), promoted.get("value"), deadline_promotion_validation.get("registration_deadline"),
            fact_promotion_validation.get("registration_deadline"), writer_projection_validation.get("registration_deadline"),
            writer_consumption_validation.get("registration_deadline"), article_claim_validation.get("registration_deadline"),
            verified.get("registration_deadline"),
        ),
        "materiality_promotion_evidence_id": (
            candidate.get("upstream_materiality_promotion_evidence_id"),
            deadline_promotion_validation.get("promotion_evidence_id"),
            fact_promotion_validation.get("upstream_materiality_promotion_evidence_id"),
        ),
        "fact_kernel_promotion_evidence_id": (
            candidate.get("fact_kernel_promotion_evidence_id"),
            promoted.get("fact_kernel_promotion_evidence_id"),
            fact_promotion_validation.get("fact_kernel_promotion_evidence_id"),
        ),
        "writer_projection_evidence_id": (
            candidate.get("writer_projection_evidence_id"),
            writer_projection_validation.get("writer_projection_evidence_id"),
            writer_consumption_validation.get("writer_projection_evidence_id"),
            article_claim_validation.get("writer_projection_evidence_id"),
        ),
        "writer_consumption_evidence_id": (
            candidate.get("writer_consumption_evidence_id"),
            writer_consumption_validation.get("writer_consumption_evidence_id"),
            article_claim_validation.get("writer_consumption_evidence_id"),
        ),
        "article_claim_evidence_id": (
            candidate.get("article_deadline_claim_evidence_id"),
            article_claim_gate.get("article_deadline_claim_evidence_id"),
            article_claim_validation.get("article_deadline_claim_evidence_id"),
            article_integrity.get("article_deadline_claim_evidence_id"),
        ),
        "document_evidence_id": (
            candidate.get("document_text_evidence_id"),
            promoted.get("document_text_evidence_id"),
            deadline_promotion_validation.get("document_text_evidence_id"),
            fact_promotion_validation.get("document_text_evidence_id"),
        ),
        "document_page": (
            candidate.get("page_number"), promoted.get("page_number"), deadline_promotion_validation.get("page_number"), fact_promotion_validation.get("page_number"),
        ),
        "document_page_sha256": (
            candidate.get("page_text_sha256"), promoted.get("page_text_sha256"), deadline_promotion_validation.get("page_text_sha256"), fact_promotion_validation.get("page_text_sha256"),
        ),
        "document_excerpt": (
            candidate.get("excerpt"), promoted.get("excerpt"), deadline_promotion_validation.get("excerpt"), fact_promotion_validation.get("excerpt"),
        ),
    }
    normalized: dict[str, str] = {}
    for key, values in cross_checks.items():
        normed = [_norm(v) for v in values]
        if not normed[0] or len(set(normed)) != 1:
            raise RuntimeError(f"upstream_identity_mismatch:{key}")
        normalized[key] = normed[0]

    claim_text = _norm(candidate.get("claim"))
    if not claim_text or claim_text != _norm(promoted.get("claim")):
        raise RuntimeError("claim_text_mismatch")
    claim_ids = _norm_list(candidate.get("claim_evidence_ids"))
    support_ids = _norm_list(candidate.get("supporting_field_evidence_ids"))
    if not claim_ids or claim_ids != _norm_list(promoted.get("claim_evidence_ids")):
        raise RuntimeError("claim_evidence_ids_mismatch")
    if not support_ids or support_ids != _norm_list(promoted.get("supporting_field_evidence_ids")):
        raise RuntimeError("supporting_evidence_ids_mismatch")

    source_url = _norm(fact.get("source_url"))
    source_name = _norm(fact.get("source"))
    article_id = _norm(candidate.get("article_id"))
    source_kind = _norm(fact_kernel.get("source_kind"))
    if not source_url or not source_name or not article_id or not source_kind:
        raise RuntimeError("source_identity_incomplete")
    if article_id != _norm(article_claim_validation.get("article_id")):
        raise RuntimeError("article_id_validation_mismatch")
    if _norm(verified.get("article_id")) != article_id or _norm(verified.get("source_url")) != source_url:
        raise RuntimeError("article_integrity_source_identity_mismatch")

    return {
        "story_id": article_id,
        "source_kind": source_kind,
        "claim_key": "registration_deadline",
        "value": normalized["value"],
        "claim_text": claim_text,
        "claim_evidence_ids": claim_ids,
        "supporting_evidence_ids": support_ids,
        "materiality_promotion_evidence_id": normalized["materiality_promotion_evidence_id"],
        "fact_kernel_promotion_evidence_id": normalized["fact_kernel_promotion_evidence_id"],
        "writer_projection_evidence_id": normalized["writer_projection_evidence_id"],
        "writer_consumption_evidence_id": normalized["writer_consumption_evidence_id"],
        "article_claim_evidence_id": normalized["article_claim_evidence_id"],
        "document_evidence_id": normalized["document_evidence_id"],
        "document_page": int(normalized["document_page"]),
        "document_page_sha256": normalized["document_page_sha256"].lower(),
        "document_excerpt": normalized["document_excerpt"],
        "source_identity": {
            "official_source_name": source_name,
            "official_source_url": source_url,
            "article_id": article_id,
        },
    }


def build_isj_promoted_claim_contract(**docs: dict[str, Any]) -> dict[str, Any]:
    try:
        lineage = derive_isj_expected_lineage(**docs)
        return build_promoted_claim_contract(**lineage)
    except Exception as exc:
        return {
            "schema_version": "1.0",
            "mode": "CORE_V2_PROMOTED_CLAIM_SHADOW",
            "state": "BLOCKED",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "canonical_article_mutation_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "production_write_authority": False,
            "lineage_complete": False,
            "reason": "isj_promoted_claim_contract_adapter_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
        }


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise RuntimeError(f"expected_object:{path}")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reusable promoted-claim contract from independently validated ISJ shadow truth")
    for name in (
        "deadline-promotion-validation", "fact-promotion-validation", "fact-kernel", "fact-integrity",
        "writer-projection-validation", "writer-consumption-validation", "article-claim-gate",
        "article-claim-validation", "article-integrity",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_isj_promoted_claim_contract(
        deadline_promotion_validation=_load(args.deadline_promotion_validation),
        fact_promotion_validation=_load(args.fact_promotion_validation),
        fact_kernel=_load(args.fact_kernel),
        fact_integrity=_load(args.fact_integrity),
        writer_projection_validation=_load(args.writer_projection_validation),
        writer_consumption_validation=_load(args.writer_consumption_validation),
        article_claim_gate=_load(args.article_claim_gate),
        article_claim_validation=_load(args.article_claim_validation),
        article_integrity=_load(args.article_integrity),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "promoted_claim_contract_id": result.get("promoted_claim_contract_id"),
        "lineage_complete": result.get("lineage_complete"),
        "publication_authority": result.get("publication_authority"),
        "acceptance_ready": result.get("acceptance_ready"),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") == "PROMOTED_CLAIM_CONTRACT_VERIFIED_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
