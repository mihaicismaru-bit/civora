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
    return out


def _canonical_lineage(data: dict[str, Any]) -> dict[str, Any]:
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
        value = _norm(data.get(key))
        if not value:
            raise ValueError(f"missing_required:{key}")
        values[key] = value

    claim_ids = _norm_list(data.get("claim_evidence_ids"))
    support_ids = _norm_list(data.get("supporting_evidence_ids"))
    if not claim_ids or len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim_evidence_ids_missing_or_duplicate")
    if not support_ids or len(support_ids) != len(set(support_ids)):
        raise ValueError("supporting_evidence_ids_missing_or_duplicate")

    page = int(data.get("document_page") or 0)
    page_hash = _norm(data.get("document_page_sha256")).lower()
    if page <= 0:
        raise ValueError("document_page_invalid")
    if not SHA256_RE.fullmatch(page_hash):
        raise ValueError("document_page_sha256_invalid")
    source_map = _canonical_map(data.get("source_identity"))
    if not source_map:
        raise ValueError("source_identity_missing")

    return {
        **values,
        "claim_evidence_ids": claim_ids,
        "supporting_evidence_ids": support_ids,
        "document_page": page,
        "document_page_sha256": page_hash,
        "source_identity": source_map,
    }


def _contract_id(parts: dict[str, Any]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"promoted-claim-{digest[:24]}"


def validate_promoted_claim_contract(
    doc: dict[str, Any],
    expected_lineage: dict[str, Any],
) -> dict[str, Any]:
    """Independently bind a reusable promoted-claim envelope to upstream truth.

    `expected_lineage` must come from the source-specific independently validated
    gates, not from fields copied out of `doc`.
    """
    base = {
        "schema_version": "1.0",
        "mode": "CORE_V2_PROMOTED_CLAIM_VALIDATION_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "production_write_authority": False,
    }
    try:
        expected = _canonical_lineage(expected_lineage)
        actual = _canonical_lineage(doc)

        if doc.get("schema_version") != "1.0":
            raise ValueError("schema_version_mismatch")
        if doc.get("mode") != "CORE_V2_PROMOTED_CLAIM_SHADOW":
            raise ValueError("mode_mismatch")
        if doc.get("state") != "PROMOTED_CLAIM_CONTRACT_VERIFIED_SHADOW":
            raise ValueError("state_mismatch")
        if doc.get("publication_authority") != "NONE":
            raise ValueError("publication_authority_violation")
        if doc.get("acceptance_ready") is not False:
            raise ValueError("acceptance_boundary_violation")
        for flag in (
            "canonical_article_mutation_allowed",
            "site_publish_allowed",
            "social_publish_allowed",
            "production_write_authority",
        ):
            if doc.get(flag) is not False:
                raise ValueError(f"authority_flag_violation:{flag}")
        if doc.get("lineage_complete") is not True:
            raise ValueError("lineage_incomplete")

        if actual != expected:
            differing = sorted(key for key in expected if actual.get(key) != expected.get(key))
            raise ValueError(f"upstream_lineage_mismatch:{','.join(differing)}")

        expected_id = _contract_id(expected)
        actual_id = _norm(doc.get("promoted_claim_contract_id"))
        if not actual_id or actual_id != expected_id:
            raise ValueError("promoted_claim_contract_identity_mismatch")

        return {
            **base,
            "status": "PASS_SHADOW",
            "state": "PROMOTED_CLAIM_CONTRACT_INDEPENDENTLY_VERIFIED_SHADOW",
            "promoted_claim_contract_id": expected_id,
            "story_id": expected["story_id"],
            "source_kind": expected["source_kind"],
            "claim_key": expected["claim_key"],
            "lineage_complete": True,
            "verified_claim_count": 1,
            "fabricated_claim_count": 0,
        }
    except Exception as exc:
        return {
            **base,
            "status": "BLOCKED",
            "state": "BLOCKED",
            "reason": "promoted_claim_contract_validation_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "lineage_complete": False,
            "verified_claim_count": 0,
            "fabricated_claim_count": 0,
        }
