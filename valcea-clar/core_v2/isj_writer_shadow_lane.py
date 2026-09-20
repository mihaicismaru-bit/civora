from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel

SCOPE_NOTE = (
    "Core v2 nu afirmă termenul de înscriere și nu normalizează intervalele calendaristice fără an explicit, "
    "deoarece aceste elemente nu sunt încă proiectate în articol printr-un gate independent claim↔evidence."
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _kernel_from_dict(data: dict[str, Any]) -> FactKernel:
    kernel = FactKernel(
        what=_norm(data.get("what")),
        who=_norm(data.get("who")),
        where=_norm(data.get("where")),
        when=_norm(data.get("when")),
        why_it_matters=_norm(data.get("why_it_matters")),
        source=_norm(data.get("source")),
        source_url=_norm(data.get("source_url")),
        claims=tuple(_norm(value) for value in data.get("claims") or [] if _norm(value)),
        evidence_ids=tuple(_norm(value) for value in data.get("evidence_ids") or [] if _norm(value)),
    )
    kernel.validate()
    return kernel


def _base() -> dict[str, Any]:
    return {
        "mode": "ISJ_FULL_EDITORIAL_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "article_projection_allowed": False,
        "fabricated_claim_count": 0,
    }


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("production_writer_ready") is not False:
        raise ValueError(f"{label}_production_writer_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")


def _validated_deadline_consumption(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any] | None,
    writer_consumption_validation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if writer_consumption is None and writer_consumption_validation is None:
        return None
    if not isinstance(writer_consumption, dict) or not isinstance(writer_consumption_validation, dict):
        raise ValueError("writer_consumption_runtime_pair_incomplete")

    _require_shadow_boundary(writer_consumption, "writer_consumption")
    _require_shadow_boundary(writer_consumption_validation, "writer_consumption_validation")
    if writer_consumption.get("writer_allowed") is not False or writer_consumption.get("article_projection_allowed") is not False:
        raise ValueError("writer_consumption_authority_boundary_violation")
    if writer_consumption_validation.get("writer_allowed") is not False or writer_consumption_validation.get("article_projection_allowed") is not False:
        raise ValueError("writer_consumption_validation_authority_boundary_violation")
    if writer_consumption.get("state") != "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW":
        raise ValueError("writer_consumption_not_verified_shadow")
    if writer_consumption.get("shadow_writer_consumption_allowed") is not True:
        raise ValueError("writer_consumption_not_allowed")
    if int(writer_consumption.get("consumption_candidate_count") or 0) != 1:
        raise ValueError("writer_consumption_candidate_count_mismatch")
    if writer_consumption_validation.get("status") != "PASS_SHADOW":
        raise ValueError("writer_consumption_validation_not_passed")
    if writer_consumption_validation.get("shadow_writer_consumption_allowed") is not True:
        raise ValueError("writer_consumption_validation_not_allowed")
    if int(writer_consumption_validation.get("verified_consumption_candidate_count") or 0) != 1:
        raise ValueError("writer_consumption_not_independently_verified")
    if int(writer_consumption_validation.get("fabricated_claim_count") or 0) != 0:
        raise ValueError("writer_consumption_validation_fabricated_claims_nonzero")
    if int(writer_consumption_validation.get("tamper_regressions_passed") or 0) < 4:
        raise ValueError("writer_consumption_tamper_proof_missing")
    if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
        raise ValueError("promoted_fact_not_independently_verified")

    kernels = fact_kernel_report.get("kernels") or []
    if len(kernels) != 1 or not isinstance(kernels[0], dict):
        raise ValueError("expected_exactly_one_fact_kernel")
    promoted = kernels[0].get("promoted_fact_claims") or []
    if int(fact_kernel_report.get("promoted_fact_claim_count") or 0) != 1 or len(promoted) != 1 or not isinstance(promoted[0], dict):
        raise ValueError("expected_exactly_one_promoted_fact_claim")
    source = promoted[0]
    if source.get("field") != "registration_deadline":
        raise ValueError("promoted_fact_deadline_missing")

    candidates = writer_consumption.get("consumption_candidates") or []
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise ValueError("writer_consumption_candidate_missing")
    candidate = candidates[0]
    if candidate.get("state") != "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW":
        raise ValueError("writer_consumption_candidate_state_mismatch")
    if candidate.get("shadow_writer_consumption_allowed") is not True:
        raise ValueError("writer_consumption_candidate_not_allowed")
    if candidate.get("writer_allowed") is not False or candidate.get("article_projection_allowed") is not False:
        raise ValueError("writer_consumption_candidate_authority_boundary_violation")
    if candidate.get("field") != "registration_deadline":
        raise ValueError("writer_consumption_candidate_field_mismatch")

    consumption_id = _norm(writer_consumption.get("writer_consumption_evidence_id"))
    if not consumption_id:
        raise ValueError("writer_consumption_evidence_id_missing")
    if _norm(candidate.get("writer_consumption_evidence_id")) != consumption_id:
        raise ValueError("writer_consumption_candidate_identity_mismatch")
    if _norm(writer_consumption_validation.get("writer_consumption_evidence_id")) != consumption_id:
        raise ValueError("writer_consumption_validation_identity_mismatch")

    projection_id = _norm(writer_consumption.get("writer_projection_evidence_id"))
    if not projection_id or _norm(candidate.get("writer_projection_evidence_id")) != projection_id:
        raise ValueError("writer_projection_identity_mismatch")
    if _norm(writer_consumption_validation.get("writer_projection_evidence_id")) != projection_id:
        raise ValueError("writer_projection_validation_identity_mismatch")

    deadline = _norm(candidate.get("value"))
    claim = _norm(candidate.get("claim"))
    if not deadline or not claim:
        raise ValueError("writer_consumption_claim_missing")
    if deadline != _norm(writer_consumption.get("registration_deadline")) or deadline != _norm(writer_consumption_validation.get("registration_deadline")):
        raise ValueError("writer_consumption_deadline_identity_mismatch")
    if deadline != _norm(source.get("value")) or claim != _norm(source.get("claim")):
        raise ValueError("writer_consumption_promoted_fact_mismatch")

    claim_evidence_ids = [_norm(v) for v in candidate.get("claim_evidence_ids") or [] if _norm(v)]
    if not claim_evidence_ids or claim_evidence_ids != [_norm(v) for v in source.get("claim_evidence_ids") or [] if _norm(v)]:
        raise ValueError("writer_consumption_claim_evidence_mismatch")
    supporting_ids = [_norm(v) for v in candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]
    if supporting_ids != [_norm(v) for v in source.get("supporting_field_evidence_ids") or [] if _norm(v)]:
        raise ValueError("writer_consumption_supporting_evidence_mismatch")

    identity_keys = (
        "field_evidence_id",
        "scope_field_evidence_id",
        "source_registration_window_field_evidence_id",
        "document_text_evidence_id",
        "upstream_materiality_promotion_evidence_id",
        "fact_kernel_promotion_evidence_id",
        "page_text_sha256",
    )
    identities: dict[str, str] = {}
    for key in identity_keys:
        value = _norm(candidate.get(key))
        if not value or value != _norm(source.get(key)):
            raise ValueError(f"writer_consumption_identity_mismatch:{key}")
        identities[key] = value

    page_number = int(candidate.get("page_number") or 0)
    excerpt = _norm(candidate.get("excerpt"))
    if page_number <= 0 or not excerpt:
        raise ValueError("writer_consumption_document_location_missing")
    if page_number != int(source.get("page_number") or 0) or excerpt != _norm(source.get("excerpt")):
        raise ValueError("writer_consumption_document_location_mismatch")

    return {
        "field": "registration_deadline",
        "value": deadline,
        "text": claim,
        "writer_projection_evidence_id": projection_id,
        "writer_consumption_evidence_id": consumption_id,
        "claim_evidence_ids": claim_evidence_ids,
        "supporting_field_evidence_ids": supporting_ids,
        **identities,
        "page_number": page_number,
        "excerpt": excerpt,
        "state": "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY",
        "article_projection_allowed": False,
        "publication_authority": "NONE",
    }


def compose_isj_article(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any] | None = None,
    writer_consumption_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _base()
    if fact_kernel_report.get("publication_authority") != "NONE":
        raise ValueError("fact_kernel_publication_boundary_violation")
    if fact_kernel_report.get("writer_allowed") is True:
        raise ValueError("fact_kernel_writer_boundary_violation")
    if fact_integrity.get("publication_authority") != "NONE":
        raise ValueError("fact_integrity_publication_boundary_violation")

    if (
        fact_integrity.get("status") != "PASS_SHADOW"
        or fact_integrity.get("fact_kernel_integrity_verified") is not True
        or int(fact_integrity.get("fabricated_claim_count") or 0) != 0
        or fact_integrity.get("writer_gate_status") != "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION"
    ):
        return {
            **base,
            "state": "BLOCKED",
            "reason": "fact_kernel_integrity_gate_not_passed",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    if fact_kernel_report.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        terminal = fact_kernel_report.get("state") if fact_kernel_report.get("state") in {"NO_STORY", "BLOCKED"} else "BLOCKED"
        return {
            **base,
            "state": terminal,
            "reason": fact_kernel_report.get("reason") or "fact_kernel_not_verified_shadow",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    kernels = fact_kernel_report.get("kernels") or []
    if len(kernels) != 1 or not isinstance(kernels[0], dict):
        return {
            **base,
            "state": "BLOCKED",
            "reason": "expected_exactly_one_fact_kernel",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    record = kernels[0]
    if record.get("integrity_status") != "PENDING_SEPARATE_GATE":
        return {
            **base,
            "state": "BLOCKED",
            "reason": "unexpected_upstream_integrity_status",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    try:
        kernel = _kernel_from_dict(record.get("fact_kernel") or {})
    except ContractViolation as exc:
        return {
            **base,
            "state": "BLOCKED",
            "reason": f"fact_kernel_contract:{exc}",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    try:
        rendered_deadline = _validated_deadline_consumption(
            fact_kernel_report,
            fact_integrity,
            writer_consumption,
            writer_consumption_validation,
        )
    except (ValueError, TypeError) as exc:
        return {
            **base,
            "state": "BLOCKED",
            "reason": f"writer_deadline_consumption_gate:{exc}",
            "article_count": 0,
            "articles": [],
            "shadow_writer_executed": False,
            "writer_consumes_deadline_projection": False,
            "rendered_promoted_claim_count": 0,
        }

    bindings: dict[str, list[str]] = {}
    for row in record.get("claim_evidence") or []:
        if not isinstance(row, dict):
            continue
        claim = _norm(row.get("claim"))
        ids = [_norm(v) for v in row.get("field_evidence_ids") or [] if _norm(v)]
        if claim and ids:
            bindings[claim] = ids

    evidence_universe = set(kernel.evidence_ids)
    claim_rows: list[dict[str, Any]] = []
    body_segments: list[dict[str, Any]] = []
    for index, claim in enumerate(kernel.claims):
        evidence_ids = bindings.get(claim) or []
        if not evidence_ids or not set(evidence_ids).issubset(evidence_universe):
            return {
                **base,
                "state": "BLOCKED",
                "reason": "material_claim_missing_exact_field_evidence_binding",
                "article_count": 0,
                "articles": [],
                "shadow_writer_executed": False,
                "writer_consumes_deadline_projection": False,
                "rendered_promoted_claim_count": 0,
            }
        claim_rows.append({"text": claim, "kernel_claim_index": index, "field_evidence_ids": evidence_ids})
        body_segments.append(
            {
                "kind": "kernel_claim",
                "kernel_claim_index": index,
                "text": claim,
                "field_evidence_ids": evidence_ids,
            }
        )

    body_segments.extend(
        [
            {"kind": "kernel_when", "text": f"Momentul documentat: {kernel.when}.", "evidence_ids": list(kernel.evidence_ids)},
            {"kind": "kernel_why_it_matters", "text": f"De ce contează: {kernel.why_it_matters}", "evidence_ids": list(kernel.evidence_ids)},
            {"kind": "kernel_source", "text": f"Sursa: {kernel.source} — {kernel.source_url}", "evidence_ids": list(kernel.evidence_ids)},
            {"kind": "scope_note", "text": SCOPE_NOTE, "evidence_ids": []},
        ]
    )
    body = "\n\n".join(_norm(segment["text"]) for segment in body_segments)
    article_id = "isj-directori-2026-conducere-scoli"
    rendered_promoted_claims = [rendered_deadline] if rendered_deadline is not None else []
    package = {
        "article_id": article_id,
        "headline": kernel.what,
        "dek": kernel.why_it_matters,
        "body": body,
        "body_segments": body_segments,
        "claims": claim_rows,
        "rendered_promoted_claims_pending_integrity": rendered_promoted_claims,
        "writer_consumes_deadline_projection": rendered_deadline is not None,
        "article_contains_registration_deadline": False,
        "writer_id": "isj_shadow_editorial_v1",
        "excluded_unverified_or_non_normalized_fields": list(record.get("excluded_unverified_or_non_normalized_fields") or []),
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    return {
        **base,
        "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
        "reason": (
            "fact_kernel_integrity_passed_and_deterministic_shadow_article_composed"
            + ("_with_deadline_rendered_pending_separate_article_claim_integrity" if rendered_deadline is not None else "")
        ),
        "article_count": 1,
        "shadow_writer_executed": True,
        "writer_consumes_deadline_projection": rendered_deadline is not None,
        "rendered_promoted_claim_count": len(rendered_promoted_claims),
        "article_contains_registration_deadline": False,
        "articles": [
            {
                "article_id": article_id,
                "fact_kernel": record.get("fact_kernel"),
                "article_package": package,
                "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
                "publication_authority": "NONE",
                "production_writer_ready": False,
                "article_projection_allowed": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
            }
        ],
        "truth_rule": (
            "The ISJ shadow writer runs only after the independent FactKernel integrity gate passes. "
            "A registration-deadline claim may be rendered into a non-article pending claim slot only when the exact runtime writer_consumption_evidence_id has PASS_SHADOW independent validation. "
            "The canonical article claims/body remain unchanged until a distinct article claim-to-evidence gate is implemented and independently validated. "
            "This writer does not self-certify article integrity and grants no site, social, merge, deployment or acceptance authority."
        ),
    }


def _load_optional_runtime_pair(fact_kernel_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    workdir = fact_kernel_path.parent
    consumption_path = workdir / "valcea-core-v2-isj-writer-deadline-consumption.json"
    validation_path = workdir / "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
    if not consumption_path.exists() and not validation_path.exists():
        return None, None
    if not consumption_path.exists() or not validation_path.exists():
        raise FileNotFoundError("writer_consumption_runtime_pair_incomplete")
    return (
        json.loads(consumption_path.read_text(encoding="utf-8")),
        json.loads(validation_path.read_text(encoding="utf-8")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose the ISJ article in non-authorizing shadow mode after FactKernel integrity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption")
    parser.add_argument("--writer-consumption-validation")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel_path = Path(args.fact_kernel)
    if bool(args.writer_consumption) != bool(args.writer_consumption_validation):
        raise SystemExit("writer consumption gate and validation must be supplied together")
    if args.writer_consumption:
        writer_consumption = json.loads(Path(args.writer_consumption).read_text(encoding="utf-8"))
        writer_consumption_validation = json.loads(Path(args.writer_consumption_validation).read_text(encoding="utf-8"))
    else:
        writer_consumption, writer_consumption_validation = _load_optional_runtime_pair(fact_kernel_path)

    result = compose_isj_article(
        json.loads(fact_kernel_path.read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        writer_consumption,
        writer_consumption_validation,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "article_count": result.get("article_count", 0),
        "shadow_writer_executed": result.get("shadow_writer_executed", False),
        "writer_consumes_deadline_projection": result.get("writer_consumes_deadline_projection", False),
        "rendered_promoted_claim_count": result.get("rendered_promoted_claim_count", 0),
        "article_contains_registration_deadline": result.get("article_contains_registration_deadline", False),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
