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


def _contract_id(parts: dict[str, Any]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"promoted-claim-{digest[:24]}"


def build_promoted_claim_contract(
    *,
    story_id: str,
    source_kind: str,
    claim_key: str,
    value: str,
    claim_text: str,
    claim_evidence_ids: list[str],
    supporting_evidence_ids: list[str],
    materiality_promotion_evidence_id: str,
    fact_kernel_promotion_evidence_id: str,
    writer_projection_evidence_id: str,
    writer_consumption_evidence_id: str,
    article_claim_evidence_id: str,
    document_evidence_id: str,
    document_page: int,
    document_page_sha256: str,
    document_excerpt: str,
    source_identity: dict[str, Any],
) -> dict[str, Any]:
    """Build one reusable truth-bound promoted-claim envelope.

    This contract only carries a claim that has already crossed source-specific
    materiality/FactKernel/writer/article gates. It never grants publication,
    distribution, merge, deployment, or acceptance authority.
    """
    story_id = _norm(story_id)
    source_kind = _norm(source_kind)
    claim_key = _norm(claim_key)
    value = _norm(value)
    claim_text = _norm(claim_text)
    claim_ids = _norm_list(claim_evidence_ids)
    support_ids = _norm_list(supporting_evidence_ids)
    materiality_id = _norm(materiality_promotion_evidence_id)
    fact_id = _norm(fact_kernel_promotion_evidence_id)
    projection_id = _norm(writer_projection_evidence_id)
    consumption_id = _norm(writer_consumption_evidence_id)
    article_id = _norm(article_claim_evidence_id)
    document_id = _norm(document_evidence_id)
    excerpt = _norm(document_excerpt)
    page_hash = _norm(document_page_sha256).lower()
    source_map = _canonical_map(source_identity)

    required = {
        "story_id": story_id,
        "source_kind": source_kind,
        "claim_key": claim_key,
        "value": value,
        "claim_text": claim_text,
        "materiality_promotion_evidence_id": materiality_id,
        "fact_kernel_promotion_evidence_id": fact_id,
        "writer_projection_evidence_id": projection_id,
        "writer_consumption_evidence_id": consumption_id,
        "article_claim_evidence_id": article_id,
        "document_evidence_id": document_id,
        "document_excerpt": excerpt,
    }
    missing = [key for key, item in required.items() if not item]
    if missing:
        raise ValueError(f"missing_required:{','.join(missing)}")
    if not claim_ids or len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim_evidence_ids_missing_or_duplicate")
    if not support_ids or len(support_ids) != len(set(support_ids)):
        raise ValueError("supporting_evidence_ids_missing_or_duplicate")
    if int(document_page) <= 0:
        raise ValueError("document_page_invalid")
    if not SHA256_RE.fullmatch(page_hash):
        raise ValueError("document_page_sha256_invalid")
    if not source_map:
        raise ValueError("source_identity_missing")

    identity = {
        **required,
        "claim_evidence_ids": claim_ids,
        "supporting_evidence_ids": support_ids,
        "document_page": int(document_page),
        "document_page_sha256": page_hash,
        "source_identity": source_map,
    }
    contract_id = _contract_id(identity)
    return {
        "schema_version": "1.0",
        "mode": "CORE_V2_PROMOTED_CLAIM_SHADOW",
        "state": "PROMOTED_CLAIM_CONTRACT_VERIFIED_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_article_mutation_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "production_write_authority": False,
        "lineage_complete": True,
        "promoted_claim_contract_id": contract_id,
        **identity,
        "truth_rule": (
            "A promoted claim may cross this reusable interface only when every evidence, "
            "promotion, writer, article and document identity is present and identity-bound. "
            "This shadow contract grants no publication or distribution authority."
        ),
    }
