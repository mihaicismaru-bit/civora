from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

ISO_DATE_RE = re.compile(r"^(\d{4})-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm_list(values: Any) -> list[str]:
    return [_norm(v) for v in values or [] if _norm(v)]


def _one(rows: Any, label: str) -> dict[str, Any]:
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"{label}_expected_one")
    return rows[0]


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_authority_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")
    if "production_writer_ready" in doc and doc.get("production_writer_ready") is not False:
        raise ValueError(f"{label}_production_writer_boundary_violation")


def _canonical_promoted_claim(fact_kernel: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if fact_kernel.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        raise ValueError("fact_kernel_not_verified_shadow")
    if fact_kernel.get("writer_allowed") is not False:
        raise ValueError("fact_kernel_writer_boundary_violation")
    kernel_row = _one(fact_kernel.get("kernels"), "fact_kernel")
    promoted = _one(kernel_row.get("promoted_fact_claims"), "promoted_fact_claim")
    if int(fact_kernel.get("promoted_fact_claim_count") or 0) != 1:
        raise ValueError("promoted_fact_claim_count_mismatch")
    if promoted.get("writer_projection_allowed") is not False or promoted.get("article_projection_allowed") is not False:
        raise ValueError("promoted_fact_upstream_projection_boundary_violation")

    field = _norm(promoted.get("field"))
    value = _norm(promoted.get("value"))
    claim = _norm(promoted.get("claim"))
    if not field or not value or not claim:
        raise ValueError("promoted_fact_identity_missing")

    identity_keys = (
        "field_evidence_id",
        "scope_field_evidence_id",
        "source_registration_window_field_evidence_id",
        "document_text_evidence_id",
        "upstream_materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "page_text_sha256",
    )
    identities = {key: _norm(promoted.get(key)) for key in identity_keys}
    if any(not value for value in identities.values()):
        raise ValueError("promoted_fact_evidence_identity_missing")
    if not SHA256_RE.fullmatch(identities["page_text_sha256"].lower()):
        raise ValueError("promoted_fact_page_hash_invalid")

    claim_ids = _norm_list(promoted.get("claim_evidence_ids"))
    support_ids = _norm_list(promoted.get("supporting_field_evidence_ids"))
    if not claim_ids or len(claim_ids) != len(set(claim_ids)):
        raise ValueError("promoted_fact_claim_evidence_invalid")
    if not support_ids or len(support_ids) != len(set(support_ids)):
        raise ValueError("promoted_fact_supporting_evidence_invalid")

    page = int(promoted.get("page_number") or 0)
    excerpt = _norm(promoted.get("excerpt"))
    if page <= 0 or not excerpt:
        raise ValueError("promoted_fact_document_location_missing")

    base_kernel = kernel_row.get("fact_kernel") or {}
    if claim in [_norm(v) for v in base_kernel.get("claims") or []]:
        raise ValueError("promoted_fact_leaked_into_writer_visible_claims")
    if identities["field_evidence_id"] in _norm_list(base_kernel.get("evidence_ids")):
        raise ValueError("promoted_fact_evidence_leaked_into_writer_visible_universe")

    excluded = _norm_list(kernel_row.get("writer_projection_excluded_fields"))
    if excluded and field not in excluded:
        raise ValueError("promoted_fact_missing_from_writer_projection_exclusions")

    canonical = {
        "field": field,
        "value": value,
        "claim": claim,
        **identities,
        "claim_evidence_ids": claim_ids,
        "supporting_field_evidence_ids": support_ids,
        "page_number": page,
        "excerpt": excerpt,
    }
    return kernel_row, canonical


def _scope_token(value: str) -> str:
    match = ISO_DATE_RE.fullmatch(value)
    if not match:
        raise ValueError("generic_projection_scope_token_unavailable")
    return match.group(1)


def _lineage_fingerprint(canonical: dict[str, Any]) -> str:
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _legacy_digest_suffix(canonical: dict[str, Any]) -> str:
    parts = [
        _scope_token(str(canonical["value"])),
        str(canonical["value"]),
        str(canonical["claim"]),
        *[str(v) for v in canonical["claim_evidence_ids"]],
        str(canonical["upstream_materiality_promotion_evidence_id"]),
        str(canonical["page_text_sha256"]),
        str(canonical["page_number"]),
        str(canonical["excerpt"]),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:24]


def build_source_neutral_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    *,
    identity_prefix: str,
) -> dict[str, Any]:
    """Build one promoted-claim writer projection without source-specific semantics.

    ``identity_prefix`` is an external compatibility namespace.  It is deliberately
    not interpreted by this builder; preserving an existing namespace lets a
    source-specific producer be replaced without changing receipt/evidence identity.
    """
    base = {
        "schema_version": "1.0",
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_WRITER_PROJECTION_SHADOW",
        "source_neutral_writer_projection_builder": True,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "writer_allowed": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }
    try:
        _require_shadow_boundary(fact_kernel, "fact_kernel")
        _require_shadow_boundary(fact_integrity, "fact_integrity")
        if fact_integrity.get("status") != "PASS_SHADOW":
            raise ValueError("fact_kernel_integrity_not_pass_shadow")
        if fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise ValueError("fact_kernel_integrity_not_verified")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise ValueError("promoted_fact_not_independently_verified")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("fact_kernel_integrity_fabricated_claims_nonzero")

        _, canonical = _canonical_promoted_claim(fact_kernel)
        prefix = _norm(identity_prefix)
        if not prefix or any(ch.isspace() for ch in prefix):
            raise ValueError("projection_identity_prefix_invalid")
        suffix = _legacy_digest_suffix(canonical)
        projection_id = f"{prefix}-{suffix}"

        field = str(canonical["field"])
        deadline_compat = field == "registration_deadline"
        candidate = {
            **canonical,
            "state": "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW" if deadline_compat else "PROMOTED_CLAIM_WRITER_PROJECTION_VERIFIED_SHADOW",
            "writer_projection_evidence_id": projection_id,
            "promoted_claim_projection_allowed": True,
            "writer_deadline_projection_allowed": deadline_compat,
            "writer_allowed": False,
            "production_writer_ready": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        return {
            **base,
            "state": "WRITER_PROJECTION_VERIFIED_SHADOW",
            "field": field,
            "value": canonical["value"],
            "claim": canonical["claim"],
            "writer_projection_evidence_id": projection_id,
            "promoted_claim_projection_allowed": True,
            "writer_deadline_projection_allowed": deadline_compat,
            "registration_deadline": canonical["value"] if deadline_compat else None,
            "projection_candidate_count": 1,
            "projection_candidates": [candidate],
            "lineage_fingerprint_sha256": _lineage_fingerprint(canonical),
            "deterministic_projection_digest_suffix": suffix,
            "identity_namespace_compatibility_only": prefix,
            "truth_rule": (
                "This source-neutral builder projects exactly one independently verified promoted FactKernel claim while preserving its evidence lineage and a caller-supplied compatibility identity namespace. "
                "It grants no article, site, social, delivery, or acceptance authority."
            ),
        }
    except Exception as exc:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "source_neutral_writer_projection_build_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "promoted_claim_projection_allowed": False,
            "writer_deadline_projection_allowed": False,
            "projection_candidate_count": 0,
            "projection_candidates": [],
        }


def validate_source_neutral_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "1.1",
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_PROJECTION_VALIDATION_SHADOW",
        "source_neutral_projection_validation": True,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }
    try:
        for label, doc in (("fact_kernel", fact_kernel), ("fact_integrity", fact_integrity), ("projection", projection)):
            _require_shadow_boundary(doc, label)

        if fact_integrity.get("status") != "PASS_SHADOW":
            raise ValueError("fact_kernel_integrity_not_pass_shadow")
        if fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise ValueError("fact_kernel_integrity_not_verified")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise ValueError("promoted_fact_not_independently_verified")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("fact_kernel_integrity_fabricated_claims_nonzero")

        _, canonical = _canonical_promoted_claim(fact_kernel)

        if projection.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
            raise ValueError("projection_not_verified_shadow")
        if projection.get("writer_deadline_projection_allowed") is not True:
            raise ValueError("projection_not_allowed")
        if projection.get("writer_allowed") is not False or projection.get("article_projection_allowed") is not False:
            raise ValueError("projection_authority_boundary_violation")
        if int(projection.get("projection_candidate_count") or 0) != 1:
            raise ValueError("projection_candidate_count_mismatch")
        if int(projection.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("projection_fabricated_claims_nonzero")

        candidate = _one(projection.get("projection_candidates"), "projection_candidate")
        for key in (
            "field", "value", "claim", "field_evidence_id", "scope_field_evidence_id",
            "source_registration_window_field_evidence_id", "document_text_evidence_id",
            "upstream_materiality_promotion_evidence_id", "fact_kernel_promotion_evidence_id",
            "page_text_sha256", "page_number", "excerpt",
        ):
            actual = int(candidate.get(key) or 0) if key == "page_number" else _norm(candidate.get(key))
            expected = int(canonical[key]) if key == "page_number" else _norm(canonical[key])
            if actual != expected:
                raise ValueError(f"projection_lineage_mismatch:{key}")
        if _norm_list(candidate.get("claim_evidence_ids")) != canonical["claim_evidence_ids"]:
            raise ValueError("projection_claim_evidence_mismatch")
        if _norm_list(candidate.get("supporting_field_evidence_ids")) != canonical["supporting_field_evidence_ids"]:
            raise ValueError("projection_supporting_evidence_mismatch")

        projection_id = _norm(projection.get("writer_projection_evidence_id"))
        if not projection_id or _norm(candidate.get("writer_projection_evidence_id")) != projection_id:
            raise ValueError("projection_identity_mismatch")
        suffix = _legacy_digest_suffix(canonical)
        if not projection_id.endswith(suffix):
            raise ValueError("projection_deterministic_digest_mismatch")
        prefix = projection_id[: -(len(suffix) + 1)]
        if not prefix:
            raise ValueError("projection_identity_namespace_missing")
        if candidate.get("writer_deadline_projection_allowed") is not True:
            raise ValueError("projection_candidate_not_allowed")
        if candidate.get("writer_allowed") is not False or candidate.get("article_projection_allowed") is not False:
            raise ValueError("projection_candidate_authority_boundary_violation")

        generic_projection = build_source_neutral_projection(
            fact_kernel,
            fact_integrity,
            identity_prefix=prefix,
        )
        if generic_projection.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
            raise ValueError(f"source_neutral_builder_blocked:{generic_projection.get('detail')}")
        if generic_projection.get("writer_projection_evidence_id") != projection_id:
            raise ValueError("source_neutral_builder_projection_identity_mismatch")
        generic_candidate = _one(generic_projection.get("projection_candidates"), "source_neutral_projection_candidate")
        for key in (
            "field", "value", "claim", "field_evidence_id", "scope_field_evidence_id",
            "source_registration_window_field_evidence_id", "document_text_evidence_id",
            "upstream_materiality_promotion_evidence_id", "fact_kernel_promotion_evidence_id",
            "page_text_sha256", "page_number", "excerpt", "writer_projection_evidence_id",
        ):
            if generic_candidate.get(key) != candidate.get(key):
                raise ValueError(f"source_neutral_builder_equivalence_mismatch:{key}")
        if _norm_list(generic_candidate.get("claim_evidence_ids")) != _norm_list(candidate.get("claim_evidence_ids")):
            raise ValueError("source_neutral_builder_claim_evidence_mismatch")
        if _norm_list(generic_candidate.get("supporting_field_evidence_ids")) != _norm_list(candidate.get("supporting_field_evidence_ids")):
            raise ValueError("source_neutral_builder_supporting_evidence_mismatch")
        for flag in (
            "publication_authority", "acceptance_ready", "production_writer_ready",
            "writer_allowed", "article_projection_allowed", "site_publish_allowed", "social_publish_allowed",
        ):
            if generic_projection.get(flag) != projection.get(flag):
                raise ValueError(f"source_neutral_builder_authority_mismatch:{flag}")

        return {
            **base,
            "status": "PASS_SHADOW",
            "state": "SOURCE_NEUTRAL_PROJECTION_INDEPENDENTLY_VERIFIED_SHADOW",
            "field": canonical["field"],
            "value": canonical["value"],
            "claim": canonical["claim"],
            "writer_projection_evidence_id": projection_id,
            "writer_projection_allowed": True,
            "verified_projection_candidate_count": 1,
            "lineage_fingerprint_sha256": _lineage_fingerprint(canonical),
            "deterministic_projection_digest_suffix": suffix,
            "claim_evidence_ids": list(canonical["claim_evidence_ids"]),
            "supporting_field_evidence_ids": list(canonical["supporting_field_evidence_ids"]),
            "page_number": canonical["page_number"],
            "page_text_sha256": canonical["page_text_sha256"],
            "excerpt": canonical["excerpt"],
            "source_neutral_builder_status": "PASS_SHADOW",
            "source_neutral_builder_equivalent": True,
            "source_neutral_builder_projection_id": generic_projection["writer_projection_evidence_id"],
            "source_neutral_builder_lineage_fingerprint_sha256": generic_projection["lineage_fingerprint_sha256"],
            "source_neutral_builder_authority_flags_equivalent": True,
            "source_specific_builder_retirement_eligible": True,
            "source_specific_builder_retirement_performed": False,
        }
    except Exception as exc:
        return {
            **base,
            "status": "BLOCKED",
            "state": "BLOCKED",
            "reason": "source_neutral_projection_validation_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "writer_projection_allowed": False,
            "verified_projection_candidate_count": 0,
            "source_neutral_builder_equivalent": False,
            "source_specific_builder_retirement_eligible": False,
            "source_specific_builder_retirement_performed": False,
        }


def prove_projection_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
) -> int:
    cases: list[dict[str, Any]] = []

    row = deepcopy(projection)
    row["projection_candidates"][0]["claim_evidence_ids"] = ["detached-evidence"]
    cases.append(row)

    row = deepcopy(projection)
    row["projection_candidates"][0]["page_text_sha256"] = "0" * 64
    cases.append(row)

    row = deepcopy(projection)
    row["writer_projection_evidence_id"] = "legacy-prefix-detached"
    cases.append(row)

    row = deepcopy(projection)
    row["site_publish_allowed"] = True
    cases.append(row)

    passed = 0
    for case in cases:
        if validate_source_neutral_projection(fact_kernel, fact_integrity, case).get("status") != "BLOCKED":
            raise AssertionError("source-neutral projection validator accepted tamper")
        passed += 1
    return passed
