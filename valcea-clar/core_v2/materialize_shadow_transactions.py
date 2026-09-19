from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from contracts import ContractViolation, FactKernel
from editorial_integrity import validate_editorial_package
from historical_fact_evidence_preflight import build as build_historical_fact_preflight

REQUIRED_KERNEL_KEYS = (
    "what",
    "who",
    "where",
    "when",
    "why_it_matters",
    "source",
    "source_url",
    "claims",
    "evidence_ids",
)

ID_KEYS = ("story_id", "id", "article_id", "slug")


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _matches_story(row: dict[str, Any], story_id: str) -> bool:
    return any(str(row.get(key) or "").strip() == story_id for key in ID_KEYS)


def _explicit_kernel_dict(row: dict[str, Any]) -> dict[str, Any] | None:
    nested = row.get("fact_kernel")
    if isinstance(nested, dict) and all(key in nested for key in REQUIRED_KERNEL_KEYS):
        return nested
    if all(key in row for key in REQUIRED_KERNEL_KEYS):
        return row
    return None


def _explicit_article_package(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("article_package", "editorial_package", "article"):
        nested = row.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("body"), str) and isinstance(nested.get("claims"), list):
            return nested
    if isinstance(row.get("body"), str) and isinstance(row.get("claims"), list):
        return row
    return None


def find_explicit_evidence(story_id: str, documents: list[tuple[str, Any]]) -> dict[str, Any]:
    matched_records: list[tuple[str, dict[str, Any]]] = []
    kernel: dict[str, Any] | None = None
    article: dict[str, Any] | None = None
    kernel_source: str | None = None
    article_source: str | None = None

    for source_name, document in documents:
        for row in _walk(document):
            if not _matches_story(row, story_id):
                continue
            matched_records.append((source_name, row))
            if kernel is None:
                candidate = _explicit_kernel_dict(row)
                if candidate is not None:
                    kernel = candidate
                    kernel_source = source_name
            if article is None:
                candidate = _explicit_article_package(row)
                if candidate is not None:
                    article = candidate
                    article_source = source_name

    # A matching wrapper may carry the ID while the structured package is one level below.
    for source_name, row in matched_records:
        if kernel is None:
            for child in row.values():
                if isinstance(child, dict):
                    candidate = _explicit_kernel_dict(child)
                    if candidate is not None:
                        kernel = candidate
                        kernel_source = source_name
                        break
        if article is None:
            for child in row.values():
                if isinstance(child, dict):
                    candidate = _explicit_article_package(child)
                    if candidate is not None:
                        article = candidate
                        article_source = source_name
                        break

    return {
        "matched_record_count": len(matched_records),
        "kernel": kernel,
        "kernel_source": kernel_source,
        "article_package": article,
        "article_source": article_source,
    }


def _kernel_from_dict(data: dict[str, Any]) -> FactKernel:
    return FactKernel(
        what=str(data.get("what") or ""),
        who=str(data.get("who") or ""),
        where=str(data.get("where") or ""),
        when=str(data.get("when") or ""),
        why_it_matters=str(data.get("why_it_matters") or ""),
        source=str(data.get("source") or ""),
        source_url=str(data.get("source_url") or ""),
        claims=tuple(str(v) for v in data.get("claims") or [] if str(v).strip()),
        evidence_ids=tuple(str(v) for v in data.get("evidence_ids") or [] if str(v).strip()),
    )


def _preflight_index(preflight: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(preflight, dict):
        return {}
    return {
        str(row.get("story_id") or ""): row
        for row in preflight.get("rows") or []
        if isinstance(row, dict) and str(row.get("story_id") or "").strip()
    }


def materialize(
    candidates: dict[str, Any],
    receipts: dict[str, Any],
    evidence_documents: list[tuple[str, Any]],
    fact_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_ids = set(candidates.get("first_ten_candidate_ids") or [])
    candidates_by_id = {
        str(row.get("story_id") or ""): row
        for row in candidates.get("rows") or []
        if isinstance(row, dict) and row.get("story_id") in candidate_ids
    }
    receipt_by_id = {
        str(row.get("story_id") or ""): row
        for row in receipts.get("rows") or []
        if isinstance(row, dict) and row.get("story_id")
    }
    preflight_by_id = _preflight_index(fact_preflight)

    rows: list[dict[str, Any]] = []
    fully_bound = 0
    for story_id in candidates.get("first_ten_candidate_ids") or []:
        candidate = candidates_by_id.get(story_id) or {}
        receipt_row = receipt_by_id.get(story_id) or {}
        evidence = find_explicit_evidence(story_id, evidence_documents)
        preflight_row = preflight_by_id.get(story_id) or {}
        result: dict[str, Any] = {
            "story_id": story_id,
            "publication_authority": "NONE",
            "material_signal": True,
            "fact_kernel_source": evidence.get("kernel_source"),
            "article_package_source": evidence.get("article_source"),
            "matched_structured_record_count": evidence.get("matched_record_count", 0),
            "historical_fact_preflight_state": preflight_row.get("state"),
            "historical_fact_preflight_promotion_allowed": preflight_row.get("promotion_allowed") is True,
            "historical_legacy_verified_fact_record_present": preflight_row.get("legacy_verified_fact_record_present") is True,
            "historical_explicit_core_v2_fact_kernel_present": preflight_row.get("explicit_core_v2_fact_kernel_present") is True,
            "historical_t1_source_count": int(preflight_row.get("t1_source_count") or 0),
            "historical_t1_source_readback_passed": int(preflight_row.get("t1_source_readback_passed") or 0),
            "historical_all_t1_sources_readback_ok": preflight_row.get("all_t1_sources_readback_ok") is True,
            "historical_source_readback": preflight_row.get("source_readback") or [],
            "external_receipt_truth": receipt_row.get("external_delivery_truth") or "BLOCKED",
            "external_receipts": receipt_row.get("receipts") or {},
            "state": "BLOCKED",
            "terminal_reason": None,
            "integrity": None,
        }

        raw_kernel = evidence.get("kernel")
        if not isinstance(raw_kernel, dict):
            result["terminal_reason"] = "BLOCKED_FACT_KERNEL_EVIDENCE"
            rows.append(result)
            continue
        try:
            kernel = _kernel_from_dict(raw_kernel)
            kernel.validate()
        except ContractViolation as exc:
            result["terminal_reason"] = "BLOCKED_INVALID_FACT_KERNEL"
            result["fact_kernel_error"] = str(exc)
            rows.append(result)
            continue

        package = evidence.get("article_package")
        if not isinstance(package, dict):
            result["terminal_reason"] = "BLOCKED_EXPLICIT_ARTICLE_CLAIMS_EVIDENCE"
            rows.append(result)
            continue

        integrity = validate_editorial_package(kernel, package)
        result["integrity"] = {
            "status": integrity.status,
            "fabricated_claims": integrity.fabricated_claims,
            "bound_claims": integrity.bound_claims,
            "errors": list(integrity.errors),
        }
        if not integrity.pass_gate:
            result["terminal_reason"] = "BLOCKED_EDITORIAL_INTEGRITY"
            rows.append(result)
            continue

        result["fact_kernel"] = {
            "what": kernel.what,
            "who": kernel.who,
            "where": kernel.where,
            "when": kernel.when,
            "why_it_matters": kernel.why_it_matters,
            "source": kernel.source,
            "source_url": kernel.source_url,
            "claims": list(kernel.claims),
            "evidence_ids": list(kernel.evidence_ids),
        }
        result["article_claim_count"] = len(package.get("claims") or [])
        result["article_body_chars"] = len(str(package.get("body") or ""))
        result["visual_internal_truth"] = candidate.get("real_visual_internal_evidence") is True

        if receipt_row.get("external_delivery_truth") != "VERIFIED":
            result["terminal_reason"] = "BLOCKED_EXTERNAL_DELIVERY_EVIDENCE"
            rows.append(result)
            continue

        # This replay proves historical evidence binding only; it never grants live acceptance.
        result["state"] = "AUDIT_REPLAY_READY"
        result["terminal_reason"] = None
        fully_bound += 1
        rows.append(result)

    preflight_summary = None
    if isinstance(fact_preflight, dict):
        preflight_summary = {
            "schema_version": fact_preflight.get("schema_version"),
            "candidate_count": fact_preflight.get("candidate_count"),
            "source_readback_story_count": fact_preflight.get("source_readback_story_count"),
            "explicit_core_v2_fact_kernel_story_count": fact_preflight.get("explicit_core_v2_fact_kernel_story_count"),
            "state_counts": fact_preflight.get("state_counts") or {},
            "publication_authority": fact_preflight.get("publication_authority"),
            "promotion_allowed": fact_preflight.get("promotion_allowed") is True,
        }

    return {
        "schema_version": "1.1",
        "mode": "SHADOW_TRANSACTION_REPLAY",
        "publication_authority": "NONE",
        "truth_rule": "Fact kernels and article claims must already exist as explicit structured evidence; rendered article prose is never reverse-engineered into facts. Legacy fact/source preflight is read-only and cannot promote legacy records into a Core v2 FactKernel.",
        "candidate_count": len(rows),
        "fully_bound_replay_count": fully_bound,
        "historical_fact_preflight": preflight_summary,
        "acceptance_ready": False,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize fail-closed Core v2 shadow StoryTransaction evidence")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    candidates = _load(args.candidates)
    receipts = _load(args.receipts)
    documents = [(path, _load(path)) for path in args.evidence]
    facts_document = next(
        (document for source_name, document in documents if Path(source_name).name == "facts_registry.json" and isinstance(document, dict)),
        None,
    )
    fact_preflight = build_historical_fact_preflight(candidates, facts_document) if isinstance(facts_document, dict) else None
    result = materialize(candidates, receipts, documents, fact_preflight=fact_preflight)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reasons: dict[str, int] = {}
    for row in result["rows"]:
        reason = str(row.get("terminal_reason") or "AUDIT_REPLAY_READY")
        reasons[reason] = reasons.get(reason, 0) + 1
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "fully_bound_replay_count": result["fully_bound_replay_count"],
                "historical_fact_preflight": result.get("historical_fact_preflight"),
                "reasons": reasons,
                "acceptance_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
