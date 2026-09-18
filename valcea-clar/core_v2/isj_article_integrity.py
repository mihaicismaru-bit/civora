from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel
from isj_writer_shadow_lane import SCOPE_NOTE

EXPECTED_SOURCE_URL = "https://www.isjvalcea.ro/management/concurs-directori-2026"
FORBIDDEN_UNVERIFIED_TERMS = (
    "termenul de înscriere este",
    "înscrierile se încheie",
    "12-27 noiembrie 2026",
    "16 decembrie 2026",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _kernel(data: dict[str, Any]) -> FactKernel:
    kernel = FactKernel(
        what=_norm(data.get("what")),
        who=_norm(data.get("who")),
        where=_norm(data.get("where")),
        when=_norm(data.get("when")),
        why_it_matters=_norm(data.get("why_it_matters")),
        source=_norm(data.get("source")),
        source_url=_norm(data.get("source_url")),
        claims=tuple(_norm(v) for v in data.get("claims") or [] if _norm(v)),
        evidence_ids=tuple(_norm(v) for v in data.get("evidence_ids") or [] if _norm(v)),
    )
    kernel.validate()
    return kernel


def verify_isj_article_integrity(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
    article_report: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "mode": "ISJ_ARTICLE_INTEGRITY_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    failures: list[str] = []
    fabricated = 0
    verified_claim_count = 0
    evidence_binding_count = 0

    if fact_kernel_report.get("publication_authority") != "NONE":
        failures.append("fact_kernel_publication_boundary_violation")
    if fact_integrity.get("publication_authority") != "NONE":
        failures.append("fact_integrity_publication_boundary_violation")
    if article_report.get("publication_authority") != "NONE":
        failures.append("article_report_publication_boundary_violation")
    if fact_integrity.get("status") != "PASS_SHADOW" or fact_integrity.get("fact_kernel_integrity_verified") is not True:
        failures.append("upstream_fact_kernel_integrity_not_passed")
    if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
        failures.append("upstream_fact_kernel_has_fabricated_claims")
    if article_report.get("state") != "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY":
        failures.append("article_not_pending_independent_integrity")
    if article_report.get("shadow_writer_executed") is not True:
        failures.append("shadow_writer_execution_missing")

    kernels = fact_kernel_report.get("kernels") or []
    articles = article_report.get("articles") or []
    if len(kernels) != 1:
        failures.append("expected_exactly_one_fact_kernel")
    if len(articles) != 1:
        failures.append("expected_exactly_one_article")

    if len(kernels) == 1 and len(articles) == 1 and isinstance(kernels[0], dict) and isinstance(articles[0], dict):
        kernel_record = kernels[0]
        article_row = articles[0]
        try:
            kernel = _kernel(kernel_record.get("fact_kernel") or {})
        except ContractViolation as exc:
            failures.append(f"fact_kernel_contract:{exc}")
            kernel = None

        if kernel is not None:
            if kernel.source_url != EXPECTED_SOURCE_URL:
                failures.append("unexpected_source_url")
            package = article_row.get("article_package") or {}
            if package.get("writer_id") != "isj_shadow_editorial_v1":
                failures.append("unexpected_writer_id")
            if package.get("publication_authority") != "NONE":
                failures.append("article_package_publication_boundary_violation")
            if package.get("production_writer_ready") is not False or package.get("site_publish_allowed") is not False or package.get("social_publish_allowed") is not False:
                failures.append("article_package_authority_boundary_violation")
            if _norm(package.get("headline")) != _norm(kernel.what):
                failures.append("headline_not_exact_kernel_what")
                fabricated += 1
            if _norm(package.get("dek")) != _norm(kernel.why_it_matters):
                failures.append("dek_not_exact_kernel_why_it_matters")
                fabricated += 1

            binding_by_claim: dict[str, list[str]] = {}
            for row in kernel_record.get("claim_evidence") or []:
                if not isinstance(row, dict):
                    continue
                claim = _norm(row.get("claim"))
                ids = [_norm(v) for v in row.get("field_evidence_ids") or [] if _norm(v)]
                if claim and ids:
                    binding_by_claim[claim] = ids

            evidence_universe = set(kernel.evidence_ids)
            claim_rows = package.get("claims") or []
            if len(claim_rows) != len(kernel.claims):
                failures.append("article_claim_count_mismatch")
                fabricated += abs(len(claim_rows) - len(kernel.claims)) or 1
            for index, claim in enumerate(kernel.claims):
                if index >= len(claim_rows) or not isinstance(claim_rows[index], dict):
                    continue
                row = claim_rows[index]
                if _norm(row.get("text")) != _norm(claim):
                    failures.append(f"article_claim_{index}_not_exact_kernel_claim")
                    fabricated += 1
                    continue
                if row.get("kernel_claim_index") != index:
                    failures.append(f"article_claim_{index}_index_mismatch")
                    fabricated += 1
                expected_ids = binding_by_claim.get(claim) or []
                actual_ids = [_norm(v) for v in row.get("field_evidence_ids") or [] if _norm(v)]
                if not expected_ids or actual_ids != expected_ids or any(eid not in evidence_universe for eid in actual_ids):
                    failures.append(f"article_claim_{index}_evidence_binding_mismatch")
                    fabricated += 1
                    continue
                verified_claim_count += 1
                evidence_binding_count += len(actual_ids)

            expected_segments: list[dict[str, Any]] = []
            for index, claim in enumerate(kernel.claims):
                expected_segments.append(
                    {
                        "kind": "kernel_claim",
                        "kernel_claim_index": index,
                        "text": claim,
                        "field_evidence_ids": binding_by_claim.get(claim) or [],
                    }
                )
            expected_segments.extend(
                [
                    {"kind": "kernel_when", "text": f"Momentul documentat: {kernel.when}.", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "kernel_why_it_matters", "text": f"De ce contează: {kernel.why_it_matters}", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "kernel_source", "text": f"Sursa: {kernel.source} — {kernel.source_url}", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "scope_note", "text": SCOPE_NOTE, "evidence_ids": []},
                ]
            )
            segments = package.get("body_segments") or []
            if len(segments) != len(expected_segments):
                failures.append("body_segment_count_mismatch")
                fabricated += abs(len(segments) - len(expected_segments)) or 1
            for index, expected in enumerate(expected_segments):
                if index >= len(segments) or not isinstance(segments[index], dict):
                    continue
                actual = segments[index]
                if actual.get("kind") != expected["kind"]:
                    failures.append(f"body_segment_{index}_kind_mismatch")
                    fabricated += 1
                if _norm(actual.get("text")) != _norm(expected["text"]):
                    failures.append(f"body_segment_{index}_text_mismatch")
                    fabricated += 1
                if expected["kind"] == "kernel_claim":
                    if actual.get("kernel_claim_index") != expected["kernel_claim_index"]:
                        failures.append(f"body_segment_{index}_claim_index_mismatch")
                        fabricated += 1
                    if [_norm(v) for v in actual.get("field_evidence_ids") or [] if _norm(v)] != expected["field_evidence_ids"]:
                        failures.append(f"body_segment_{index}_claim_evidence_mismatch")
                        fabricated += 1
                else:
                    actual_ids = [_norm(v) for v in actual.get("evidence_ids") or [] if _norm(v)]
                    if actual_ids != expected["evidence_ids"]:
                        failures.append(f"body_segment_{index}_evidence_mismatch")
                        fabricated += 1

            expected_body = "\n\n".join(_norm(segment["text"]) for segment in expected_segments)
            body = _norm(package.get("body"))
            if body != _norm(expected_body):
                failures.append("body_contains_uncontrolled_or_missing_text")
                fabricated += 1
            folded_body = body.casefold()
            if any(term.casefold() in folded_body for term in FORBIDDEN_UNVERIFIED_TERMS):
                failures.append("body_contains_unverified_schedule_or_registration_fact")
                fabricated += 1

            excluded = set(_norm(v) for v in package.get("excluded_unverified_or_non_normalized_fields") or [] if _norm(v))
            if not {"registration_deadline", "interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded):
                failures.append("article_does_not_preserve_unverified_field_exclusions")

    failures = list(dict.fromkeys(failures))
    status = "PASS_SHADOW" if not failures and fabricated == 0 else "BLOCKED"
    return {
        **base,
        "status": status,
        "article_truth_state": "VERIFIED_WRITTEN_SHADOW" if status == "PASS_SHADOW" else "BLOCKED",
        "verified_article_count": 1 if status == "PASS_SHADOW" else 0,
        "verified_claim_count": verified_claim_count,
        "evidence_binding_count": evidence_binding_count,
        "fabricated_claim_count": fabricated,
        "failures": failures,
        "article_integrity_verified": status == "PASS_SHADOW",
        "photo_gate_status": "ELIGIBLE_FOR_SEPARATE_PHOTO_TRUTH_GATE" if status == "PASS_SHADOW" else "BLOCKED",
        "truth_rule": (
            "This independent gate reconstructs the complete allowed ISJ article from the verified FactKernel and exact claim evidence bindings. "
            "Any extra or modified factual prose fails closed. PASS_SHADOW does not authorize a visual, site publication, social delivery, acceptance, merge or deployment."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify the complete ISJ shadow article against its FactKernel")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = verify_isj_article_integrity(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        json.loads(Path(args.article).read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "article_truth_state": result["article_truth_state"],
        "verified_article_count": result["verified_article_count"],
        "verified_claim_count": result["verified_claim_count"],
        "fabricated_claim_count": result["fabricated_claim_count"],
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
