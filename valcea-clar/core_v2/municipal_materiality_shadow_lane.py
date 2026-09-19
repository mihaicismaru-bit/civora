from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:,\d+)?)\s*(?:lei|ron)\b", re.I)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fold(value: Any) -> str:
    text = _normalize(value).casefold()
    return text.translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def _amounts_lei(text: str) -> list[float]:
    values: list[float] = []
    for match in AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value >= 0:
            values.append(value)
    return values


def _evidence_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in row.get("evidence") or [] if isinstance(item, dict)]


def _candidate(category: str, consequence: str, evidence_ids: list[str], **details: Any) -> dict[str, Any]:
    return {
        "category": category,
        "public_consequence": consequence,
        "evidence_ids": sorted(set(evidence_ids)),
        "details": details,
        "epistemic_status": "DOCUMENT_SUPPORTED_MATERIALITY_CANDIDATE",
        "fact_kernel_status": "NOT_PROMOTED",
    }


def adjudicate_document(row: dict[str, Any]) -> dict[str, Any]:
    """Classify verified HCL evidence for reader-relevant material consequence.

    This gate never creates a FactKernel or article. It only identifies bounded
    candidates whose materiality is directly supported by first-party document
    evidence IDs. Titles alone never satisfy materiality.
    """
    base = {
        "decision_number": row.get("decision_number"),
        "decision_date": row.get("decision_date"),
        "registered_title": row.get("registered_title"),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
    }
    if row.get("state") != "DOCUMENT_EVIDENCE_READY":
        return {
            **base,
            "state": "BLOCKED",
            "reason": row.get("reason") or "document_evidence_not_ready",
            "materiality_candidates": [],
        }

    evidence = _evidence_rows(row)
    operative = [item for item in evidence if item.get("kind") == "OPERATIVE_ARTICLE"]
    if not operative:
        return {**base, "state": "BLOCKED", "reason": "operative_evidence_missing", "materiality_candidates": []}
    if any(not _normalize(item.get("evidence_id")) for item in operative):
        return {**base, "state": "BLOCKED", "reason": "operative_evidence_id_missing", "materiality_candidates": []}
    if any(item.get("epistemic_status") != "FIRST_PARTY_DOCUMENT_TEXT" for item in operative):
        return {**base, "state": "BLOCKED", "reason": "operative_evidence_not_first_party", "materiality_candidates": []}

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    for item in operative:
        text = _normalize(item.get("excerpt"))
        folded = _fold(text)
        eid = _normalize(item.get("evidence_id"))
        amounts = _amounts_lei(text)

        fiscal_action = any(
            phrase in folded
            for phrase in (
                "se rectifica bugetul",
                "se aproba rectificarea",
                "se aproba contractarea unei finantari",
                "se majoreaza bugetul",
                "se diminueaza bugetul",
            )
        )
        if fiscal_action and amounts:
            cand = _candidate(
                "LOCAL_PUBLIC_FINANCE",
                "official_decision_changes_local_budget_or_financing",
                [eid],
                amounts_lei=amounts,
            )
            key = (cand["category"], tuple(cand["evidence_ids"]))
            if key not in seen:
                seen.add(key)
                candidates.append(cand)

        education_action = (
            "se completeaza reteaua scolara" in folded
            or "se modifica reteaua scolara" in folded
            or ("reteaua scolara" in folded and "introduc" in folded)
        )
        if education_action:
            cand = _candidate(
                "LOCAL_EDUCATION_ACCESS",
                "official_decision_changes_the_local_school_network",
                [eid],
            )
            key = (cand["category"], tuple(cand["evidence_ids"]))
            if key not in seen:
                seen.add(key)
                candidates.append(cand)

        regulated_authorization = (
            "se aproba acordarea autorizatiei anuale de functionare" in folded
            and "jocuri de noroc" in folded
        )
        if regulated_authorization:
            supporting = [eid]
            fee_amounts: list[float] = []
            for support in evidence:
                if support.get("kind") != "MONEY_CONTEXT":
                    continue
                support_text = _normalize(support.get("excerpt"))
                if "tax" not in _fold(support_text):
                    continue
                support_id = _normalize(support.get("evidence_id"))
                if support_id and support.get("epistemic_status") == "FIRST_PARTY_DOCUMENT_TEXT":
                    supporting.append(support_id)
                    fee_amounts.extend(_amounts_lei(support_text))
            cand = _candidate(
                "REGULATED_LOCAL_AUTHORIZATION",
                "official_decision_grants_a_local_gambling_operating_authorization",
                supporting,
                annual_local_fee_lei=max(fee_amounts) if fee_amounts else None,
            )
            key = (cand["category"], tuple(cand["evidence_ids"]))
            if key not in seen:
                seen.add(key)
                candidates.append(cand)

    if not candidates:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "verified_document_has_no_proven_reader_relevant_material_consequence",
            "materiality_candidates": [],
        }

    # Collapse multiple operative articles supporting the same consequence into a
    # single candidate. This prevents one HCL from looking like multiple stories.
    consolidated: dict[tuple[str, str], dict[str, Any]] = {}
    for cand in candidates:
        key = (cand["category"], cand["public_consequence"])
        current = consolidated.get(key)
        if current is None:
            consolidated[key] = cand
            continue
        current["evidence_ids"] = sorted(set(current["evidence_ids"] + cand["evidence_ids"]))
        if "amounts_lei" in current["details"] or "amounts_lei" in cand["details"]:
            current["details"]["amounts_lei"] = sorted(set(
                (current["details"].get("amounts_lei") or []) + (cand["details"].get("amounts_lei") or [])
            ))
        if current["details"].get("annual_local_fee_lei") is None and cand["details"].get("annual_local_fee_lei") is not None:
            current["details"]["annual_local_fee_lei"] = cand["details"]["annual_local_fee_lei"]
    candidates = list(consolidated.values())

    return {
        **base,
        "state": "MATERIALITY_CANDIDATE",
        "reason": "reader_relevant_public_consequence_supported_by_first_party_document_evidence",
        "materiality_candidates": candidates,
        "materiality_candidate_count": len(candidates),
        "truth_note": (
            "Materiality is proven only at the decision-consequence level. This output is not a FactKernel, "
            "does not prove implementation beyond the adopted decision, and cannot be sent to a writer or publisher."
        ),
    }


def adjudicate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    rows = [adjudicate_document(row) for row in bundle.get("rows") or [] if isinstance(row, dict)]
    counts = {
        "materiality_candidate_count": sum(row.get("state") == "MATERIALITY_CANDIDATE" for row in rows),
        "no_story_count": sum(row.get("state") == "NO_STORY" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
    }
    return {
        "schema_version": "1.0",
        "mode": "MUNICIPAL_MATERIALITY_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "source_status": bundle.get("status"),
        "latest_official_adopted_date": bundle.get("latest_official_adopted_date"),
        **counts,
        "fabricated_claim_count": 0,
        "rows": rows,
        "truth_rule": (
            "A municipal decision is not an article. This gate may only mark a materiality candidate when an explicit "
            "reader-relevant public consequence is bound to first-party evidence IDs. FactKernel composition and writing remain separate gates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate municipal HCL materiality in non-authorizing shadow mode")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = adjudicate_bundle(bundle)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "materiality_candidate_count": result["materiality_candidate_count"],
        "no_story_count": result["no_story_count"],
        "blocked_count": result["blocked_count"],
        "fabricated_claim_count": 0,
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
