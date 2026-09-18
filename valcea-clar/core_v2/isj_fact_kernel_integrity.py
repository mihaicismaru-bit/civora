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


def verify_fact_kernel_integrity(report: dict[str, Any]) -> dict[str, Any]:
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
            failures.append("expected_exactly_two_material_claims")
        if len(evidence_ids) != 4 or len(set(evidence_ids)) != 4:
            failures.append("fact_kernel_evidence_id_set_invalid")
        if not {"registration_deadline", "interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded):
            failures.append("unverified_fields_not_explicitly_excluded")

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
                failures.append("claim_contains_unverified_schedule_or_registration_fact")

        if set(binding_by_claim) != set(claims):
            failures.append("claim_binding_set_mismatch")
        if str(row.get("integrity_status") or "") != "PENDING_SEPARATE_GATE":
            failures.append("upstream_integrity_status_not_pending")
        if "writer" in row or "article" in row:
            failures.append("writer_or_article_present_before_integrity_gate")

    status = "PASS_SHADOW" if not failures and fabricated_claims == 0 else "BLOCKED"
    return {
        **base,
        "status": status,
        "verified_claim_count": verified_claim_count,
        "evidence_binding_count": evidence_binding_count,
        "fabricated_claim_count": fabricated_claims,
        "failures": failures,
        "fact_kernel_integrity_verified": status == "PASS_SHADOW",
        "writer_gate_status": "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION" if status == "PASS_SHADOW" else "BLOCKED",
        "truth_rule": "This independent gate verifies only the FactKernel's material claims and field-evidence bindings. It does not create or authorize article prose, visuals, site publication, social delivery, acceptance, merge or deployment.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify ISJ shadow FactKernel claim integrity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    result = verify_fact_kernel_integrity(report)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "verified_claim_count": result["verified_claim_count"], "fabricated_claim_count": result["fabricated_claim_count"], "publication_authority": "NONE", "writer_allowed": False, "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
