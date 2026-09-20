from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm_list(values: Any) -> list[str]:
    return [_norm(v) for v in values or [] if _norm(v)]


def _canonical_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("source_identity_must_be_mapping")
    out: dict[str, str] = {}
    for key in sorted(value):
        nk = _norm(key)
        nv = _norm(value[key])
        if not nk or not nv:
            raise ValueError("source_identity_empty_key_or_value")
        out[nk] = nv
    if not out:
        raise ValueError("source_identity_missing")
    return out


def _canonical_claim(doc: dict[str, Any]) -> dict[str, Any]:
    scalar_keys = (
        "story_id",
        "source_kind",
        "claim_key",
        "value",
        "claim_text",
        "materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "writer_projection_evidence_id",
        "writer_consumption_evidence_id",
        "article_claim_evidence_id",
        "document_evidence_id",
        "document_excerpt",
    )
    values: dict[str, str] = {}
    for key in scalar_keys:
        value = _norm(doc.get(key))
        if not value:
            raise ValueError(f"missing_required:{key}")
        values[key] = value

    claim_ids = _norm_list(doc.get("claim_evidence_ids"))
    support_ids = _norm_list(doc.get("supporting_evidence_ids"))
    if not claim_ids or len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim_evidence_ids_missing_or_duplicate")
    if not support_ids or len(support_ids) != len(set(support_ids)):
        raise ValueError("supporting_evidence_ids_missing_or_duplicate")

    page = int(doc.get("document_page") or 0)
    page_hash = _norm(doc.get("document_page_sha256")).lower()
    if page <= 0:
        raise ValueError("document_page_invalid")
    if not SHA256_RE.fullmatch(page_hash):
        raise ValueError("document_page_sha256_invalid")

    return {
        **values,
        "claim_evidence_ids": claim_ids,
        "supporting_evidence_ids": support_ids,
        "document_page": page,
        "document_page_sha256": page_hash,
        "source_identity": _canonical_map(doc.get("source_identity")),
    }


def _consumer_id(contract_id: str, claim: dict[str, Any]) -> str:
    payload = {
        "promoted_claim_contract_id": _norm(contract_id),
        "claim": claim,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"promoted-claim-consumer-{digest[:24]}"


def _require_no_authority(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_authority_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    for flag in (
        "canonical_article_mutation_allowed",
        "site_publish_allowed",
        "social_publish_allowed",
        "production_write_authority",
    ):
        if flag in doc and doc.get(flag) is not False:
            raise ValueError(f"{label}_authority_flag_violation:{flag}")


def consume_promoted_claim_contract(
    contract: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    """Consume one already validated promoted-claim contract through a source-neutral boundary.

    The consumer intentionally knows nothing about ISJ, deadline semantics, source adapters,
    writers, publication, or social delivery. It emits only the canonical claim lineage
    proven by the reusable contract and its independent validator.
    """
    base = {
        "schema_version": "1.0",
        "mode": "CORE_V2_PROMOTED_CLAIM_CONSUMER_SHADOW",
        "source_neutral_consumer": True,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_article_mutation_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "production_write_authority": False,
    }
    try:
        _require_no_authority(contract, "contract")
        _require_no_authority(validation, "validation")
        if contract.get("schema_version") != "1.0":
            raise ValueError("contract_schema_version_mismatch")
        if contract.get("mode") != "CORE_V2_PROMOTED_CLAIM_SHADOW":
            raise ValueError("contract_mode_mismatch")
        if contract.get("state") != "PROMOTED_CLAIM_CONTRACT_VERIFIED_SHADOW":
            raise ValueError("contract_state_mismatch")
        if contract.get("lineage_complete") is not True:
            raise ValueError("contract_lineage_incomplete")
        if validation.get("status") != "PASS_SHADOW":
            raise ValueError("contract_validation_not_pass_shadow")
        if validation.get("state") != "PROMOTED_CLAIM_CONTRACT_INDEPENDENTLY_VERIFIED_SHADOW":
            raise ValueError("contract_validation_state_mismatch")
        if validation.get("lineage_complete") is not True:
            raise ValueError("contract_validation_lineage_incomplete")
        if int(validation.get("verified_claim_count") or 0) != 1:
            raise ValueError("contract_validation_verified_claim_count_mismatch")
        if int(validation.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("contract_validation_fabricated_claims_nonzero")

        contract_id = _norm(contract.get("promoted_claim_contract_id"))
        validation_id = _norm(validation.get("promoted_claim_contract_id"))
        if not contract_id or validation_id != contract_id:
            raise ValueError("contract_validation_identity_mismatch")

        claim = _canonical_claim(contract)
        for key in ("story_id", "source_kind", "claim_key"):
            validation_value = _norm(validation.get(key))
            if validation_value and validation_value != _norm(claim[key]):
                raise ValueError(f"contract_validation_claim_identity_mismatch:{key}")

        consumer_id = _consumer_id(contract_id, claim)
        return {
            **base,
            "status": "PASS_SHADOW",
            "state": "PROMOTED_CLAIM_CONSUMED_SHADOW",
            "promoted_claim_contract_id": contract_id,
            "promoted_claim_consumer_id": consumer_id,
            "lineage_complete": True,
            "verified_claim_count": 1,
            "fabricated_claim_count": 0,
            "claim": claim,
            "truth_rule": (
                "This source-neutral consumer can emit a promoted claim only from an independently PASS_SHADOW reusable contract. "
                "It grants no article mutation, publication, distribution, merge, deployment or acceptance authority."
            ),
        }
    except Exception as exc:
        return {
            **base,
            "status": "BLOCKED",
            "state": "BLOCKED",
            "reason": "promoted_claim_consumer_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "lineage_complete": False,
            "verified_claim_count": 0,
            "fabricated_claim_count": 0,
        }


def validate_consumer_identity(doc: dict[str, Any]) -> dict[str, Any]:
    """Recompute the consumer identity without source-specific knowledge."""
    base = {
        "schema_version": "1.0",
        "mode": "CORE_V2_PROMOTED_CLAIM_CONSUMER_IDENTITY_VALIDATION_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "production_write_authority": False,
    }
    try:
        _require_no_authority(doc, "consumer")
        if doc.get("status") != "PASS_SHADOW" or doc.get("state") != "PROMOTED_CLAIM_CONSUMED_SHADOW":
            raise ValueError("consumer_not_pass_shadow")
        if doc.get("source_neutral_consumer") is not True:
            raise ValueError("consumer_not_source_neutral")
        if doc.get("lineage_complete") is not True:
            raise ValueError("consumer_lineage_incomplete")
        if int(doc.get("verified_claim_count") or 0) != 1 or int(doc.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("consumer_claim_counts_invalid")
        contract_id = _norm(doc.get("promoted_claim_contract_id"))
        claim_doc = doc.get("claim")
        if not contract_id or not isinstance(claim_doc, dict):
            raise ValueError("consumer_identity_inputs_missing")
        claim = _canonical_claim(claim_doc)
        expected_id = _consumer_id(contract_id, claim)
        if _norm(doc.get("promoted_claim_consumer_id")) != expected_id:
            raise ValueError("promoted_claim_consumer_identity_mismatch")
        return {
            **base,
            "status": "PASS_SHADOW",
            "state": "PROMOTED_CLAIM_CONSUMER_IDENTITY_VERIFIED_SHADOW",
            "promoted_claim_contract_id": contract_id,
            "promoted_claim_consumer_id": expected_id,
            "lineage_complete": True,
            "verified_claim_count": 1,
            "fabricated_claim_count": 0,
        }
    except Exception as exc:
        return {
            **base,
            "status": "BLOCKED",
            "state": "BLOCKED",
            "reason": "promoted_claim_consumer_identity_validation_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "lineage_complete": False,
            "verified_claim_count": 0,
            "fabricated_claim_count": 0,
        }
