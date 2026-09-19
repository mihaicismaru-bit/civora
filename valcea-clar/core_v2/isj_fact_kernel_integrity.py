from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_SOURCE_URL = "https://www.isjvalcea.ro/management/concurs-directori-2026"
FORBIDDEN_UNVERIFIED_TERMS = (
    "termenul de înscriere este",
    "înscrierile se încheie",
    "12-27 noiembrie 2026",
    "16 decembrie 2026",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _verify_promoted_deadline(
    row: dict[str, Any],
    report: dict[str, Any],
    fact_promotion: dict[str, Any] | None,
    fact_promotion_validation: dict[str, Any] | None,
) -> tuple[list[str], int, int]:
    failures: list[str] = []
    promoted = row.get("promoted_fact_claims") or []
    declared_count = int(report.get("promoted_fact_claim_count") or 0)
    consumed = report.get("fact_kernel_deadline_composition_consumed") is True

    if not promoted and declared_count == 0 and not consumed:
        return failures, 0, 0
    if len(promoted) != 1 or declared_count != 1 or not consumed:
        return ["deadline_promoted_fact_cardinality_or_consumption_mismatch"], 0, 1
    if not isinstance(fact_promotion, dict) or not isinstance(fact_promotion_validation, dict):
        return ["deadline_promoted_fact_missing_independent_upstream_evidence"], 0, 1

    gate = fact_promotion
    validation = fact_promotion_validation
    if gate.get("publication_authority") != "NONE" or gate.get("acceptance_ready") is not False:
        failures.append("deadline_promotion_gate_authority_boundary_violation")
    if gate.get("state") != "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW" or gate.get("fact_kernel_promotion_allowed") is not True:
        failures.append("deadline_promotion_gate_not_verified")
    if gate.get("writer_allowed") is not False or gate.get("site_publish_allowed") is not False or gate.get("social_publish_allowed") is not False:
        failures.append("deadline_promotion_gate_downstream_authority_violation")
    if validation.get("publication_authority") != "NONE" or validation.get("acceptance_ready") is not False:
        failures.append("deadline_promotion_validation_authority_boundary_violation")
    if validation.get("status") != "PASS_SHADOW" or validation.get("fact_kernel_promotion_allowed") is not True:
        failures.append("deadline_promotion_independent_validation_not_passed")
    if validation.get("writer_allowed") is not False or validation.get("site_publish_allowed") is not False or validation.get("social_publish_allowed") is not False:
        failures.append("deadline_promotion_validation_downstream_authority_violation")

    gate_candidates = gate.get("promotion_candidates") or []
    if len(gate_candidates) != 1 or not isinstance(gate_candidates[0], dict):
        failures.append("deadline_promotion_gate_candidate_cardinality")
        return failures, 0, 1
    upstream = gate_candidates[0]
    item = promoted[0]
    if not isinstance(item, dict):
        failures.append("deadline_promoted_fact_invalid")
        return failures, 0, 1

    deadline = str(item.get("value") or "")
    claim = _norm(item.get("claim"))
    if item.get("field") != "registration_deadline":
        failures.append("deadline_promoted_fact_field_mismatch")
    if item.get("state") != "FACT_KERNEL_COMPOSED_SHADOW_PENDING_WRITER_PROJECTION_GATE":
        failures.append("deadline_promoted_fact_state_mismatch")
    if deadline != "2026-10-02":
        failures.append("deadline_promoted_fact_value_mismatch")
    if "2 octombrie 2026" not in claim or "termen-limită" not in claim:
        failures.append("deadline_promoted_fact_claim_text_mismatch")
    if item.get("writer_projection_allowed") is not False or item.get("article_projection_allowed") is not False:
        failures.append("deadline_promoted_fact_writer_projection_boundary_violation")
    if "registration_deadline" not in [str(v) for v in row.get("writer_projection_excluded_fields") or []]:
        failures.append("deadline_promoted_fact_writer_exclusion_missing")

    identity_pairs = (
        ("field_evidence_id", "registration_deadline_field_evidence_id"),
        ("scope_field_evidence_id", "scope_field_evidence_id"),
        ("source_registration_window_field_evidence_id", "source_registration_window_field_evidence_id"),
        ("document_text_evidence_id", "document_text_evidence_id"),
        ("page_text_sha256", "page_text_sha256"),
        ("fact_kernel_promotion_evidence_id", "fact_kernel_promotion_evidence_id"),
        ("upstream_materiality_promotion_evidence_id", "upstream_materiality_promotion_evidence_id"),
    )
    for item_key, validation_key in identity_pairs:
        actual = str(item.get(item_key) or "")
        gate_value = str(upstream.get(item_key) or "")
        if item_key in {"fact_kernel_promotion_evidence_id", "upstream_materiality_promotion_evidence_id"}:
            gate_value = str(gate.get(item_key) or gate_value)
        validation_value = str(validation.get(validation_key) or "")
        if not actual or actual != gate_value or actual != validation_value:
            failures.append(f"deadline_promoted_fact_identity_mismatch:{item_key}")

    supporting = [str(v) for v in item.get("supporting_field_evidence_ids") or []]
    if supporting != [str(v) for v in upstream.get("supporting_field_evidence_ids") or []] or supporting != [str(v) for v in validation.get("supporting_field_evidence_ids") or []]:
        failures.append("deadline_promoted_fact_supporting_identity_mismatch")
    if len(supporting) != 2 or len(set(supporting)) != 2:
        failures.append("deadline_promoted_fact_supporting_identity_invalid")

    if int(item.get("page_number") or 0) != int(upstream.get("page_number") or 0) or int(item.get("page_number") or 0) != int(validation.get("page_number") or 0):
        failures.append("deadline_promoted_fact_page_number_mismatch")
    if _norm(item.get("excerpt")) != _norm(upstream.get("excerpt")) or _norm(item.get("excerpt")) != _norm(validation.get("excerpt")):
        failures.append("deadline_promoted_fact_excerpt_mismatch")

    expected_claim_evidence = [
        str(item.get("field_evidence_id") or ""),
        str(item.get("scope_field_evidence_id") or ""),
        str(item.get("source_registration_window_field_evidence_id") or ""),
        str(item.get("document_text_evidence_id") or ""),
        str(item.get("fact_kernel_promotion_evidence_id") or ""),
    ]
    actual_claim_evidence = [str(v) for v in item.get("claim_evidence_ids") or []]
    if actual_claim_evidence != expected_claim_evidence or any(not value for value in expected_claim_evidence):
        failures.append("deadline_promoted_fact_claim_evidence_binding_mismatch")

    kernel = row.get("fact_kernel") or {}
    writer_claims = [_norm(v) for v in kernel.get("claims") or []]
    if claim in writer_claims:
        failures.append("deadline_promoted_fact_leaked_into_writer_visible_claims")
    writer_evidence_ids = [str(v) for v in kernel.get("evidence_ids") or []]
    if str(item.get("field_evidence_id") or "") in writer_evidence_ids:
        failures.append("deadline_promoted_fact_leaked_into_writer_visible_evidence_universe")

    verified = 1 if not failures else 0
    fabricated = 0 if not failures else 1
    return failures, verified, fabricated


def verify_fact_kernel_integrity(
    report: dict[str, Any],
    fact_promotion: dict[str, Any] | None = None,
    fact_promotion_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "mode": "ISJ_FACT_KERNEL_INTEGRITY_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    failures: list[str] = []
    if report.get("publication_authority") != "NONE":
        failures.append("fact_kernel_report_publication_boundary_violation")
    if report.get("writer_allowed") is True:
        failures.append("fact_kernel_report_writer_boundary_violation")
    if report.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        failures.append("fact_kernel_not_verified_shadow")

    kernels = report.get("kernels") or []
    if len(kernels) != 1:
        failures.append("expected_exactly_one_fact_kernel")
    fabricated_claims = 0
    verified_claim_count = 0
    evidence_binding_count = 0
    promoted_fact_verified_count = 0

    if len(kernels) == 1:
        row = kernels[0]
        kernel = row.get("fact_kernel") or {}
        claims = [str(v) for v in kernel.get("claims") or []]
        evidence_ids = [str(v) for v in kernel.get("evidence_ids") or []]
        bindings = row.get("claim_evidence") or []
        excluded = set(str(v) for v in row.get("excluded_unverified_or_non_normalized_fields") or [])

        if kernel.get("source_url") != EXPECTED_SOURCE_URL:
            failures.append("unexpected_source_url")
        if len(claims) != 2:
            failures.append("expected_exactly_two_writer_visible_material_claims")
        if len(evidence_ids) != 4 or len(set(evidence_ids)) != 4:
            failures.append("fact_kernel_writer_visible_evidence_id_set_invalid")
        if not {"registration_deadline", "interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded):
            failures.append("writer_projection_exclusions_not_preserved")

        binding_by_claim: dict[str, list[str]] = {}
        for item in bindings:
            claim = str(item.get("claim") or "")
            ids = [str(v) for v in item.get("field_evidence_ids") or []]
            if not claim or not ids:
                failures.append("claim_evidence_binding_empty")
                continue
            if claim in binding_by_claim:
                failures.append("duplicate_claim_evidence_binding")
                continue
            binding_by_claim[claim] = ids
        for claim in claims:
            bound = binding_by_claim.get(claim) or []
            if not bound:
                fabricated_claims += 1
                failures.append("material_claim_without_field_evidence")
                continue
            if any(eid not in evidence_ids for eid in bound):
                fabricated_claims += 1
                failures.append("claim_references_non_kernel_evidence")
                continue
            verified_claim_count += 1
            evidence_binding_count += len(bound)
            folded = claim.casefold()
            if any(term.casefold() in folded for term in FORBIDDEN_UNVERIFIED_TERMS):
                fabricated_claims += 1
                failures.append("writer_visible_claim_contains_unverified_schedule_or_registration_fact")

        if set(binding_by_claim) != set(claims):
            failures.append("claim_binding_set_mismatch")
        if str(row.get("integrity_status") or "") != "PENDING_SEPARATE_GATE":
            failures.append("upstream_integrity_status_not_pending")
        if "writer" in row or "article" in row:
            failures.append("writer_or_article_present_before_integrity_gate")

        promotion_failures, promoted_verified, promoted_fabricated = _verify_promoted_deadline(row, report, fact_promotion, fact_promotion_validation)
        failures.extend(promotion_failures)
        promoted_fact_verified_count += promoted_verified
        fabricated_claims += promoted_fabricated

    failures = list(dict.fromkeys(failures))
    status = "PASS_SHADOW" if not failures and fabricated_claims == 0 else "BLOCKED"
    return {
        **base,
        "status": status,
        "verified_claim_count": verified_claim_count,
        "promoted_fact_verified_count": promoted_fact_verified_count,
        "evidence_binding_count": evidence_binding_count,
        "fabricated_claim_count": fabricated_claims,
        "failures": failures,
        "fact_kernel_integrity_verified": status == "PASS_SHADOW",
        "writer_deadline_projection_allowed": False,
        "writer_gate_status": "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION" if status == "PASS_SHADOW" else "BLOCKED",
        "truth_rule": "This independent gate verifies the writer-visible FactKernel claims and, when present, independently re-binds the separately promoted registration-deadline fact to the exact upstream PASS_SHADOW promotion evidence. The deadline must remain absent from writer-visible claims/evidence until a later writer projection gate. This gate grants no article-deadline projection, publication, delivery, acceptance, merge or deployment authority.",
    }


def _load_runtime_promotion_pair(fact_kernel_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    workdir = fact_kernel_path.parent
    promotion_path = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion.json"
    validation_path = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion-validation.json"
    if not promotion_path.exists() and not validation_path.exists():
        return None, None
    if not promotion_path.exists() or not validation_path.exists():
        return None, None
    return json.loads(promotion_path.read_text(encoding="utf-8")), json.loads(validation_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify ISJ shadow FactKernel claim integrity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fact_kernel_path = Path(args.fact_kernel)
    promotion, promotion_validation = _load_runtime_promotion_pair(fact_kernel_path)
    report = json.loads(fact_kernel_path.read_text(encoding="utf-8"))
    result = verify_fact_kernel_integrity(report, promotion, promotion_validation)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "verified_claim_count": result["verified_claim_count"], "promoted_fact_verified_count": result.get("promoted_fact_verified_count", 0), "fabricated_claim_count": result["fabricated_claim_count"], "writer_deadline_projection_allowed": False, "publication_authority": "NONE", "writer_allowed": False, "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
