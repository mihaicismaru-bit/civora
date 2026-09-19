from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel
from municipal_article_integrity import POLICY_NOTE, validate_municipal_article


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


def _slug(value: Any) -> str:
    text = _norm(value).casefold()
    text = text.translate(str.maketrans("ăâîșşțţ", "aaisstt"))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "material"


def compose_article(kernel_record: dict[str, Any], *, decision_number: Any, decision_date: Any) -> dict[str, Any]:
    kernel_data = kernel_record.get("fact_kernel")
    if not isinstance(kernel_data, dict):
        raise ContractViolation("municipal writer requires a FactKernel object")
    kernel = _kernel_from_dict(kernel_data)

    bindings: dict[str, list[str]] = {}
    for row in kernel_record.get("claim_evidence") or []:
        if not isinstance(row, dict):
            continue
        claim = _norm(row.get("claim"))
        evidence_ids = [_norm(value) for value in row.get("evidence_ids") or [] if _norm(value)]
        if claim and evidence_ids:
            bindings[claim] = evidence_ids

    claim_rows: list[dict[str, Any]] = []
    body_segments: list[dict[str, Any]] = []
    evidence_universe = set(kernel.evidence_ids)
    for idx, claim in enumerate(kernel.claims):
        evidence_ids = bindings.get(claim) or list(kernel.evidence_ids)
        if not evidence_ids or not set(evidence_ids).issubset(evidence_universe):
            raise ContractViolation("municipal article claim evidence is missing or outside FactKernel evidence")
        claim_rows.append(
            {
                "text": claim,
                "kernel_claim_index": idx,
                "evidence_ids": evidence_ids,
            }
        )
        body_segments.append(
            {
                "kind": "kernel_claim",
                "kernel_claim_index": idx,
                "text": claim,
                "evidence_ids": evidence_ids,
            }
        )

    body_segments.extend(
        [
            {
                "kind": "kernel_when",
                "text": f"Momentul documentat: {kernel.when}.",
                "evidence_ids": list(kernel.evidence_ids),
            },
            {
                "kind": "kernel_why_it_matters",
                "text": f"De ce contează: {kernel.why_it_matters}",
                "evidence_ids": list(kernel.evidence_ids),
            },
            {
                "kind": "kernel_source",
                "text": f"Sursa: {kernel.source} — {kernel.source_url}",
                "evidence_ids": list(kernel.evidence_ids),
            },
            {
                "kind": "policy_note",
                "text": POLICY_NOTE,
                "evidence_ids": [],
            },
        ]
    )
    body = "\n\n".join(_norm(segment["text"]) for segment in body_segments)
    category = _norm(kernel_record.get("category"))
    article_id = f"hcl-{int(decision_number)}-{_slug(category)}"
    package = {
        "article_id": article_id,
        "headline": kernel.what,
        "dek": kernel.why_it_matters,
        "body": body,
        "body_segments": body_segments,
        "claims": claim_rows,
        "writer_id": "municipal_shadow_editorial_v1",
        "decision_number": int(decision_number),
        "decision_date": _norm(decision_date),
        "category": category,
        "production_writer_ready": False,
        "publication_authority": "NONE",
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }

    integrity = validate_municipal_article(kernel, package)
    if not integrity.pass_gate:
        raise ContractViolation("municipal article integrity failed: " + ",".join(integrity.errors))

    return {
        "article_id": article_id,
        "category": category,
        "fact_kernel": kernel_data,
        "article_package": package,
        "integrity": {
            "status": integrity.status,
            "fabricated_claims": integrity.fabricated_claims,
            "bound_claims": integrity.bound_claims,
            "errors": list(integrity.errors),
            "body_fully_controlled": True,
        },
        "state": "VERIFIED_WRITTEN_SHADOW",
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }


def compose_bundle(fact_kernel_bundle: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    article_count = 0
    fabricated_claims = 0
    for source_row in fact_kernel_bundle.get("rows") or []:
        if not isinstance(source_row, dict):
            continue
        base = {
            "decision_number": source_row.get("decision_number"),
            "decision_date": source_row.get("decision_date"),
            "publication_authority": "NONE",
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        state = source_row.get("state")
        if state != "FACT_KERNEL_VERIFIED_SHADOW":
            terminal = state if state in {"NO_STORY", "BLOCKED"} else "BLOCKED"
            rows.append({**base, "state": terminal, "reason": source_row.get("reason") or "fact_kernel_not_verified"})
            continue

        articles: list[dict[str, Any]] = []
        try:
            for kernel_record in source_row.get("kernels") or []:
                if not isinstance(kernel_record, dict):
                    raise ContractViolation("municipal FactKernel row contains a non-object kernel")
                article = compose_article(
                    kernel_record,
                    decision_number=source_row.get("decision_number"),
                    decision_date=source_row.get("decision_date"),
                )
                articles.append(article)
                article_count += 1
                fabricated_claims += int((article.get("integrity") or {}).get("fabricated_claims") or 0)
        except Exception as exc:
            rows.append(
                {
                    **base,
                    "state": "BLOCKED",
                    "reason": "municipal_shadow_writer_or_integrity_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
            continue
        if not articles:
            rows.append({**base, "state": "NO_STORY", "reason": "verified_fact_kernel_row_has_no_article_candidates"})
            continue
        rows.append(
            {
                **base,
                "state": "VERIFIED_WRITTEN_SHADOW",
                "article_count": len(articles),
                "articles": articles,
            }
        )

    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    verified_rows = sum(row.get("state") == "VERIFIED_WRITTEN_SHADOW" for row in rows)
    return {
        "schema_version": "1.0",
        "mode": "MUNICIPAL_FULL_EDITORIAL_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "verified_written_shadow_row_count": verified_rows,
        "article_count": article_count,
        "blocked_count": blocked,
        "no_story_count": no_story,
        "fabricated_claim_count": fabricated_claims,
        "rows": rows,
        "truth_rule": (
            "Municipal shadow articles are deterministic renderings of verified FactKernel claims and controlled kernel-field segments. "
            "The independent municipal integrity gate rejects any uncontrolled body text. Adopted decision evidence never proves later implementation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose municipal full editorial packages in non-authorizing shadow mode")
    parser.add_argument("--fact-kernels", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fact_kernels = json.loads(Path(args.fact_kernels).read_text(encoding="utf-8"))
    result = compose_bundle(fact_kernels)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verified_written_shadow_row_count": result["verified_written_shadow_row_count"],
        "article_count": result["article_count"],
        "blocked_count": result["blocked_count"],
        "no_story_count": result["no_story_count"],
        "fabricated_claim_count": result["fabricated_claim_count"],
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
