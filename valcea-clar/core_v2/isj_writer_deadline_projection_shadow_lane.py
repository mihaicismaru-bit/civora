from __future__ import annotations

import argparse
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


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_WRITER_DEADLINE_PROJECTION_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "writer_deadline_projection_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }


def _blocked(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    out = {
        **_base(),
        "state": "BLOCKED",
        "reason": reason,
        "projection_candidate_count": 0,
        "projection_candidates": [],
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("production_writer_ready") is not False:
        raise ValueError(f"{label}_production_writer_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")


def _single_promoted_deadline(fact_kernel: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if fact_kernel.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        raise RuntimeError("fact_kernel_not_verified_shadow")
    if fact_kernel.get("writer_allowed") is not False:
        raise RuntimeError("fact_kernel_writer_boundary_violation")
    kernels = fact_kernel.get("kernels") or []
    if len(kernels) != 1 or not isinstance(kernels[0], dict):
        raise RuntimeError("expected_one_fact_kernel")
    row = kernels[0]
    if row.get("integrity_status") != "PENDING_SEPARATE_GATE":
        raise RuntimeError("fact_kernel_integrity_status_not_pending")
    promoted = row.get("promoted_fact_claims") or []
    if len(promoted) != 1 or int(fact_kernel.get("promoted_fact_claim_count") or 0) != 1:
        raise RuntimeError("expected_one_promoted_fact_claim")
    item = promoted[0]
    if not isinstance(item, dict):
        raise RuntimeError("promoted_fact_claim_invalid")
    if item.get("field") != "registration_deadline":
        raise RuntimeError("promoted_fact_field_mismatch")
    return row, item


def build_writer_deadline_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    try:
        _require_shadow_boundary(fact_kernel, "fact_kernel")
        _require_shadow_boundary(fact_integrity, "fact_integrity")
        if fact_integrity.get("status") != "PASS_SHADOW":
            raise RuntimeError("fact_kernel_integrity_not_passed")
        if fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise RuntimeError("fact_kernel_integrity_not_verified")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("fact_kernel_integrity_fabricated_claims_nonzero")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise RuntimeError("promoted_fact_not_independently_verified")
        if fact_integrity.get("writer_deadline_projection_allowed") is not False:
            raise RuntimeError("upstream_integrity_must_not_self_authorize_writer_projection")
        if fact_integrity.get("writer_gate_status") != "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION":
            raise RuntimeError("upstream_writer_gate_status_not_eligible")

        row, promoted = _single_promoted_deadline(fact_kernel)
        deadline = str(promoted.get("value") or "")
        parsed = date.fromisoformat(deadline)
        if parsed.year != expected_year:
            raise RuntimeError("deadline_year_mismatch")
        expected_claim = (
            f"Calendarul oficial verificat pentru sesiunea {expected_year} indică data de "
            f"{_romanian_date(deadline)} ca termen-limită al perioadei de înscriere."
        )
        claim = _norm(promoted.get("claim"))
        if claim != expected_claim:
            raise RuntimeError("promoted_fact_claim_text_mismatch")
        if promoted.get("state") != "FACT_KERNEL_COMPOSED_SHADOW_PENDING_WRITER_PROJECTION_GATE":
            raise RuntimeError("promoted_fact_state_mismatch")
        if promoted.get("writer_projection_allowed") is not False or promoted.get("article_projection_allowed") is not False:
            raise RuntimeError("promoted_fact_upstream_projection_boundary_violation")
        if "registration_deadline" not in [str(v) for v in row.get("writer_projection_excluded_fields") or []]:
            raise RuntimeError("deadline_writer_exclusion_missing")

        kernel = row.get("fact_kernel") or {}
        base_claims = [_norm(v) for v in kernel.get("claims") or []]
        base_evidence = [str(v) for v in kernel.get("evidence_ids") or []]
        if len(base_claims) != 2 or len(base_evidence) != 4 or len(set(base_evidence)) != 4:
            raise RuntimeError("writer_visible_fact_kernel_universe_invalid")
        if claim in base_claims:
            raise RuntimeError("deadline_already_leaked_into_writer_visible_claims")

        identity_keys = (
            "field_evidence_id",
            "scope_field_evidence_id",
            "source_registration_window_field_evidence_id",
            "document_text_evidence_id",
            "upstream_materiality_promotion_evidence_id",
            "fact_kernel_promotion_evidence_id",
            "page_text_sha256",
        )
        identities = {key: str(promoted.get(key) or "") for key in identity_keys}
        if any(not value for value in identities.values()):
            raise RuntimeError("promoted_fact_identity_missing")
        if identities["field_evidence_id"] in base_evidence:
            raise RuntimeError("deadline_evidence_already_in_writer_visible_universe")

        supporting = [str(v) for v in promoted.get("supporting_field_evidence_ids") or []]
        if supporting != [identities["scope_field_evidence_id"], identities["source_registration_window_field_evidence_id"]]:
            raise RuntimeError("supporting_evidence_identity_mismatch")
        claim_evidence_ids = [str(v) for v in promoted.get("claim_evidence_ids") or []]
        expected_claim_evidence = [
            identities["field_evidence_id"],
            identities["scope_field_evidence_id"],
            identities["source_registration_window_field_evidence_id"],
            identities["document_text_evidence_id"],
            identities["fact_kernel_promotion_evidence_id"],
        ]
        if claim_evidence_ids != expected_claim_evidence:
            raise RuntimeError("claim_evidence_binding_mismatch")

        excerpt = _norm(promoted.get("excerpt"))
        page_number = int(promoted.get("page_number") or 0)
        if not excerpt or page_number <= 0:
            raise RuntimeError("document_evidence_location_missing")

        projection_id = _projection_id(
            str(expected_year), deadline, claim, *expected_claim_evidence,
            identities["upstream_materiality_promotion_evidence_id"], identities["page_text_sha256"],
            str(page_number), excerpt,
        )
        candidate = {
            "field": "registration_deadline",
            "value": deadline,
            "claim": claim,
            "state": "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW",
            **identities,
            "supporting_field_evidence_ids": supporting,
            "claim_evidence_ids": expected_claim_evidence,
            "page_number": page_number,
            "excerpt": excerpt,
            "writer_projection_evidence_id": projection_id,
            "writer_deadline_projection_allowed": True,
            "writer_allowed": False,
            "production_writer_ready": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        result = {
            **_base(),
            "state": "WRITER_PROJECTION_VERIFIED_SHADOW",
            "reason": "independently_verified_factkernel_deadline_preserves_exact_identity_for_separate_shadow_writer_projection",
            "registration_deadline": deadline,
            "writer_projection_evidence_id": projection_id,
            "writer_deadline_projection_allowed": True,
            "projection_candidate_count": 1,
            "projection_candidates": [candidate],
            "truth_rule": (
                "This gate may make one already independently verified FactKernel registration-deadline claim eligible for a later deterministic shadow-writer projection only when all claim and evidence identities remain exact. "
                "It does not alter article prose, self-certify article integrity, authorize publication/distribution, or satisfy acceptance."
            ),
        }

        # Bounded dependency/retirement proof: execute the source-neutral
        # replacement validator beside the source-specific path, but keep the
        # legacy validator and every downstream gate authoritative for this run.
        generic = validate_source_neutral_projection(fact_kernel, fact_integrity, result)
        if generic.get("status") != "PASS_SHADOW":
            raise RuntimeError(f"source_neutral_projection_validator_failed:{generic.get('detail')}")
        if generic.get("writer_projection_evidence_id") != projection_id:
            raise RuntimeError("source_neutral_projection_identity_mismatch")
        tamper_passed = prove_projection_tamper_regressions(fact_kernel, fact_integrity, result)
        if tamper_passed != 4:
            raise RuntimeError("source_neutral_projection_tamper_proof_incomplete")
        result.update({
            "source_neutral_replacement_validator_status": "PASS_SHADOW",
            "source_neutral_replacement_projection_id": generic.get("writer_projection_evidence_id"),
            "source_neutral_replacement_lineage_fingerprint_sha256": generic.get("lineage_fingerprint_sha256"),
            "source_neutral_replacement_authority_flags_equivalent": True,
            "source_neutral_replacement_tamper_regressions_passed": tamper_passed,
            "retirement_candidate": "isj_writer_deadline_projection_validation",
            "retirement_candidate_proof_only": True,
            "retirement_performed": False,
            "replacement_path_enabled": False,
            "source_neutral_replacement_proof": generic,
        })
        result["truth_rule"] += (
            " A source-neutral replacement validator also ran beside this source-specific projection in shadow mode, reproduced the exact projection identity and authority boundary, and failed closed under four tamper regressions. The legacy validator remains active and no retirement occurs in this proof increment."
        )
        return result
    except Exception as exc:
        return _blocked("writer_deadline_projection_gate_failed", detail=f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed ISJ FactKernel-to-writer deadline projection gate")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_writer_deadline_projection(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "writer_deadline_projection_allowed": result.get("writer_deadline_projection_allowed", False),
        "source_neutral_replacement_validator_status": result.get("source_neutral_replacement_validator_status"),
        "source_neutral_replacement_tamper_regressions_passed": result.get("source_neutral_replacement_tamper_regressions_passed", 0),
        "retirement_candidate": result.get("retirement_candidate"),
        "retirement_performed": result.get("retirement_performed", False),
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
