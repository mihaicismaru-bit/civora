from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel

SCOPE_NOTE = (
    "Core v2 nu afirmă termenul de înscriere și nu normalizează intervalele calendaristice fără an explicit, "
    "deoarece aceste elemente nu sunt încă verificate la același nivel de evidență."
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
        "fabricated_claim_count": 0,
    }


def compose_isj_article(fact_kernel_report: dict[str, Any], fact_integrity: dict[str, Any]) -> dict[str, Any]:
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
    package = {
        "article_id": article_id,
        "headline": kernel.what,
        "dek": kernel.why_it_matters,
        "body": body,
        "body_segments": body_segments,
        "claims": claim_rows,
        "writer_id": "isj_shadow_editorial_v1",
        "excluded_unverified_or_non_normalized_fields": list(record.get("excluded_unverified_or_non_normalized_fields") or []),
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    return {
        **base,
        "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
        "reason": "fact_kernel_integrity_passed_and_deterministic_shadow_article_composed",
        "article_count": 1,
        "shadow_writer_executed": True,
        "articles": [
            {
                "article_id": article_id,
                "fact_kernel": record.get("fact_kernel"),
                "article_package": package,
                "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
                "publication_authority": "NONE",
                "production_writer_ready": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
            }
        ],
        "truth_rule": (
            "The ISJ shadow writer runs only after the independent FactKernel integrity gate passes. It renders only exact kernel claims and controlled kernel-field/scope segments. "
            "This writer does not self-certify article integrity and grants no site, social, merge or deployment authority."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose the ISJ article in non-authorizing shadow mode after FactKernel integrity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = compose_isj_article(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "article_count": result.get("article_count", 0),
        "shadow_writer_executed": result.get("shadow_writer_executed", False),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
