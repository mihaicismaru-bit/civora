from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel
from isj_writer_shadow_lane import SCOPE_NOTE

EXPECTED_SOURCE_URL = "https://www.isjvalcea.ro/management/concurs-directori-2026"
PROJECTED_SCOPE_NOTE = (
    "Core v2 afirmă numai termenul de înscriere 2 octombrie 2026, promovat prin lanțul independent "
    "FactKernel → writer-consumption → article-claim; celelalte intervale calendaristice fără an explicit "
    "rămân excluse până la validare separată."
)
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


def _claim_gate_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-article-deadline-claim-{digest[:24]}"


def _verified_promoted_deadline(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
) -> dict[str, Any] | None:
    kernels = fact_kernel_report.get("kernels") or []
    if len(kernels) != 1 or not isinstance(kernels[0], dict):
        return None
    promoted_rows = kernels[0].get("promoted_fact_claims") or []
    count = int(fact_kernel_report.get("promoted_fact_claim_count") or 0)
    if count == 0 and not promoted_rows:
        return None
    if count != 1 or len(promoted_rows) != 1 or not isinstance(promoted_rows[0], dict):
        raise ValueError("promoted_fact_cardinality_mismatch")
    if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
        raise ValueError("promoted_fact_not_independently_verified")
    promoted = promoted_rows[0]
    if promoted.get("field") != "registration_deadline":
        raise ValueError("unexpected_promoted_fact_field")
    return promoted


def _verify_promoted_article_claim(
    *,
    article_id: str,
    promoted: dict[str, Any],
    claim_row: dict[str, Any],
    body_segment: dict[str, Any],
) -> tuple[int, list[str]]:
    failures: list[str] = []
    fabricated = 0

    claim = _norm(promoted.get("claim"))
    deadline = _norm(promoted.get("value"))
    evidence_ids = [_norm(v) for v in promoted.get("claim_evidence_ids") or [] if _norm(v)]
    supporting_ids = [_norm(v) for v in promoted.get("supporting_field_evidence_ids") or [] if _norm(v)]
    if not claim or not deadline or not evidence_ids:
        return 1, ["promoted_fact_claim_incomplete"]

    if _norm(claim_row.get("text")) != claim:
        failures.append("promoted_article_claim_text_mismatch")
        fabricated += 1
    if claim_row.get("promoted_fact_field") != "registration_deadline":
        failures.append("promoted_article_claim_field_mismatch")
        fabricated += 1
    actual_ids = [_norm(v) for v in claim_row.get("field_evidence_ids") or [] if _norm(v)]
    if actual_ids != evidence_ids:
        failures.append("promoted_article_claim_evidence_mismatch")
        fabricated += 1

    projection_id = _norm(claim_row.get("writer_projection_evidence_id"))
    consumption_id = _norm(claim_row.get("writer_consumption_evidence_id"))
    materiality_id = _norm(claim_row.get("upstream_materiality_promotion_evidence_id"))
    fact_promotion_id = _norm(claim_row.get("fact_kernel_promotion_evidence_id"))
    page_hash = _norm(claim_row.get("page_text_sha256"))
    page_number = int(claim_row.get("page_number") or 0)
    excerpt = _norm(claim_row.get("excerpt"))
    if not all((projection_id, consumption_id, materiality_id, fact_promotion_id, page_hash, excerpt)) or page_number <= 0:
        failures.append("promoted_article_claim_identity_incomplete")
        fabricated += 1

    for key in (
        "upstream_materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "page_text_sha256",
    ):
        expected = _norm(promoted.get(key))
        actual = _norm(claim_row.get(key))
        if not expected or actual != expected:
            failures.append(f"promoted_article_claim_identity_mismatch:{key}")
            fabricated += 1

    if page_number != int(promoted.get("page_number") or 0) or excerpt != _norm(promoted.get("excerpt")):
        failures.append("promoted_article_claim_document_location_mismatch")
        fabricated += 1

    gate_id = _norm(claim_row.get("article_deadline_claim_evidence_id"))
    if not gate_id:
        failures.append("promoted_article_claim_gate_id_missing")
        fabricated += 1
    else:
        expected_gate_id = _claim_gate_id(
            article_id,
            consumption_id,
            projection_id,
            deadline,
            claim,
            *evidence_ids,
            materiality_id,
            fact_promotion_id,
            page_hash,
            str(page_number),
            excerpt,
        )
        if gate_id != expected_gate_id:
            failures.append("promoted_article_claim_gate_id_mismatch")
            fabricated += 1

    if body_segment.get("kind") != "promoted_fact_claim":
        failures.append("promoted_body_segment_kind_mismatch")
        fabricated += 1
    if body_segment.get("promoted_fact_field") != "registration_deadline":
        failures.append("promoted_body_segment_field_mismatch")
        fabricated += 1
    if _norm(body_segment.get("text")) != claim:
        failures.append("promoted_body_segment_text_mismatch")
        fabricated += 1
    if [_norm(v) for v in body_segment.get("field_evidence_ids") or [] if _norm(v)] != evidence_ids:
        failures.append("promoted_body_segment_evidence_mismatch")
        fabricated += 1
    if _norm(body_segment.get("article_deadline_claim_evidence_id")) != gate_id:
        failures.append("promoted_body_segment_gate_id_mismatch")
        fabricated += 1
    if _norm(body_segment.get("writer_consumption_evidence_id")) != consumption_id:
        failures.append("promoted_body_segment_consumption_id_mismatch")
        fabricated += 1
    if _norm(body_segment.get("fact_kernel_promotion_evidence_id")) != fact_promotion_id:
        failures.append("promoted_body_segment_fact_promotion_id_mismatch")
        fabricated += 1

    if not supporting_ids:
        failures.append("promoted_fact_supporting_evidence_missing")
        fabricated += 1

    return fabricated, failures


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
    verified_candidate: dict[str, Any] | None = None
    projected_deadline_verified = False
    article_deadline_claim_evidence_id: str | None = None

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

    try:
        promoted_deadline = _verified_promoted_deadline(fact_kernel_report, fact_integrity)
    except ValueError as exc:
        promoted_deadline = None
        failures.append(str(exc))

    projected_mode = bool(article_report.get("article_contains_registration_deadline"))
    if projected_mode:
        if article_report.get("shadow_article_projection_applied") is not True:
            failures.append("projected_article_missing_shadow_projection_marker")
        if int(article_report.get("canonical_promoted_claim_count") or 0) != 1:
            failures.append("projected_article_promoted_claim_count_mismatch")
        article_deadline_claim_evidence_id = _norm(article_report.get("article_deadline_claim_evidence_id")) or None
        if promoted_deadline is None:
            failures.append("projected_article_without_verified_promoted_fact")

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
            if package.get("article_projection_allowed") is not False:
                failures.append("article_projection_authority_boundary_violation")
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
            expected_claim_count = len(kernel.claims) + (1 if projected_mode else 0)
            if len(claim_rows) != expected_claim_count:
                failures.append("article_claim_count_mismatch")
                fabricated += abs(len(claim_rows) - expected_claim_count) or 1

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

            if projected_mode:
                if promoted_deadline is None or len(claim_rows) <= len(kernel.claims) or not isinstance(claim_rows[len(kernel.claims)], dict):
                    failures.append("projected_deadline_claim_missing")
                    fabricated += 1
                else:
                    promoted_claim_row = claim_rows[len(kernel.claims)]
                    article_id = _norm(package.get("article_id"))
                    promoted_segment = {
                        "kind": "promoted_fact_claim",
                        "promoted_fact_field": "registration_deadline",
                        "text": _norm(promoted_deadline.get("claim")),
                        "field_evidence_ids": list(promoted_deadline.get("claim_evidence_ids") or []),
                        "article_deadline_claim_evidence_id": _norm(promoted_claim_row.get("article_deadline_claim_evidence_id")),
                        "writer_consumption_evidence_id": _norm(promoted_claim_row.get("writer_consumption_evidence_id")),
                        "fact_kernel_promotion_evidence_id": _norm(promoted_claim_row.get("fact_kernel_promotion_evidence_id")),
                    }
                    added_fabricated, added_failures = _verify_promoted_article_claim(
                        article_id=article_id,
                        promoted=promoted_deadline,
                        claim_row=promoted_claim_row,
                        body_segment=promoted_segment,
                    )
                    fabricated += added_fabricated
                    failures.extend(added_failures)
                    if not added_failures:
                        verified_claim_count += 1
                        evidence_binding_count += len(promoted_deadline.get("claim_evidence_ids") or [])
                        projected_deadline_verified = True
                        article_deadline_claim_evidence_id = _norm(promoted_claim_row.get("article_deadline_claim_evidence_id"))

                    expected_segments.append(promoted_segment)

            expected_segments.extend(
                [
                    {"kind": "kernel_when", "text": f"Momentul documentat: {kernel.when}.", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "kernel_why_it_matters", "text": f"De ce contează: {kernel.why_it_matters}", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "kernel_source", "text": f"Sursa: {kernel.source} — {kernel.source_url}", "evidence_ids": list(kernel.evidence_ids)},
                    {"kind": "scope_note", "text": PROJECTED_SCOPE_NOTE if projected_mode else SCOPE_NOTE, "evidence_ids": []},
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
                elif expected["kind"] == "promoted_fact_claim":
                    if actual.get("promoted_fact_field") != "registration_deadline":
                        failures.append("promoted_body_segment_field_mismatch")
                        fabricated += 1
                    if [_norm(v) for v in actual.get("field_evidence_ids") or [] if _norm(v)] != [
                        _norm(v) for v in expected.get("field_evidence_ids") or [] if _norm(v)
                    ]:
                        failures.append("promoted_body_segment_evidence_mismatch")
                        fabricated += 1
                    for key in (
                        "article_deadline_claim_evidence_id",
                        "writer_consumption_evidence_id",
                        "fact_kernel_promotion_evidence_id",
                    ):
                        if _norm(actual.get(key)) != _norm(expected.get(key)):
                            failures.append(f"promoted_body_segment_{key}_mismatch")
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
            if projected_mode:
                if "registration_deadline" in excluded:
                    failures.append("verified_registration_deadline_remains_excluded")
                if not {"interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded):
                    failures.append("article_does_not_preserve_remaining_unverified_field_exclusions")
                if package.get("article_contains_registration_deadline") is not True:
                    failures.append("package_deadline_projection_marker_missing")
                if int(package.get("canonical_promoted_claim_count") or 0) != 1:
                    failures.append("package_promoted_claim_count_mismatch")
                if package.get("rendered_promoted_claims_pending_integrity"):
                    failures.append("pending_promoted_claim_not_cleared_after_projection")
                if len(package.get("promoted_claims_projected_shadow") or []) != 1:
                    failures.append("projected_promoted_claim_snapshot_missing")
            else:
                if not {"registration_deadline", "interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded):
                    failures.append("article_does_not_preserve_unverified_field_exclusions")

            verified_candidate = {
                "article_id": _norm(package.get("article_id")),
                "headline": _norm(package.get("headline")),
                "where": kernel.where,
                "who": kernel.who,
                "source_url": kernel.source_url,
            }
            if projected_mode:
                verified_candidate["article_deadline_claim_evidence_id"] = article_deadline_claim_evidence_id
                verified_candidate["registration_deadline"] = "2026-10-02"
            if not verified_candidate["article_id"]:
                failures.append("verified_candidate_article_id_missing")

    failures = list(dict.fromkeys(failures))
    status = "PASS_SHADOW" if not failures and fabricated == 0 else "BLOCKED"
    verified_candidates = [verified_candidate] if status == "PASS_SHADOW" and verified_candidate is not None else []
    return {
        **base,
        "status": status,
        "article_truth_state": "VERIFIED_WRITTEN_SHADOW" if status == "PASS_SHADOW" else "BLOCKED",
        "verified_article_count": len(verified_candidates),
        "verified_candidates": verified_candidates,
        "verified_claim_count": verified_claim_count,
        "evidence_binding_count": evidence_binding_count,
        "fabricated_claim_count": fabricated,
        "failures": failures,
        "article_integrity_verified": status == "PASS_SHADOW",
        "projected_deadline_verified": bool(status == "PASS_SHADOW" and projected_mode and projected_deadline_verified),
        "article_contains_registration_deadline": bool(projected_mode),
        "canonical_promoted_claim_count": 1 if projected_mode else 0,
        "article_deadline_claim_evidence_id": article_deadline_claim_evidence_id if projected_mode else None,
        "photo_gate_status": "ELIGIBLE_FOR_SEPARATE_PHOTO_TRUTH_GATE" if status == "PASS_SHADOW" else "BLOCKED",
        "truth_rule": (
            "This independent gate reconstructs the complete allowed ISJ article from the verified FactKernel and exact claim evidence bindings. "
            "When the registration deadline is projected, it independently reconstructs its deterministic article-claim identity from the promoted "
            "FactKernel evidence chain and requires an exact third claim/body segment. Any extra, detached or modified factual prose fails closed. "
            "PASS_SHADOW grants no visual, site publication, social delivery, acceptance, merge or deployment authority."
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
        "projected_deadline_verified": result["projected_deadline_verified"],
        "fabricated_claim_count": result["fabricated_claim_count"],
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
