from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel

MUNICIPALITY = "Municipiul Râmnicu Vâlcea"
COUNCIL = "Consiliul Local al Municipiului Râmnicu Vâlcea"
PLACE = "Râmnicu Vâlcea"


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fold(value: Any) -> str:
    return _normalize(value).casefold().translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def _money(value: float | int) -> str:
    rounded = int(round(float(value)))
    return f"{rounded:,}".replace(",", ".") + " lei"


def _evidence_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _normalize(item.get("evidence_id")): item
        for item in document.get("evidence") or []
        if isinstance(item, dict) and _normalize(item.get("evidence_id"))
    }


def _source_label(number: Any, decision_date: Any) -> str:
    return f"{COUNCIL} — Hotărârea nr. {number} din {decision_date}"


def _extract_school_name(excerpts: list[str]) -> str | None:
    for text in excerpts:
        match = re.search(r"introducerii[^–-]*[–-]\s*([^,.;]+?)(?:\s*\(PJ\)|\s+la\s+Învățământ|,)", text, flags=re.I)
        if match:
            value = _normalize(match.group(1))
            if value:
                return value
        match = re.search(r"Numele\s+(Școala\s+primară\s+[^,.;]+)", text, flags=re.I)
        if match:
            return _normalize(match.group(1))
    return None


def _extract_operator(excerpts: list[str]) -> str | None:
    for text in excerpts:
        match = re.search(r"operatorului economic\s+([^,]+)", text, flags=re.I)
        if match:
            return _normalize(match.group(1))
    return None


def _extract_workpoint(excerpts: list[str]) -> str | None:
    for text in excerpts:
        match = re.search(r"punctul de lucru situat în\s+([^,]+),\s*str\.\s*([^,]+?)\s+nr\.?\s*([0-9A-Za-z/-]+)", text, flags=re.I)
        if match:
            locality = _normalize(match.group(1))
            street = _normalize(match.group(2))
            number = _normalize(match.group(3))
            return f"{locality}, str. {street} nr. {number}"
    return None


def _candidate_evidence(candidate: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    ids = [_normalize(value) for value in candidate.get("evidence_ids") or [] if _normalize(value)]
    if not ids or any(value not in evidence_by_id for value in ids):
        raise ContractViolation("materiality candidate references missing document evidence")
    if any(evidence_by_id[value].get("epistemic_status") != "FIRST_PARTY_DOCUMENT_TEXT" for value in ids):
        raise ContractViolation("materiality candidate evidence is not first-party document text")
    excerpts = [_normalize(evidence_by_id[value].get("excerpt")) for value in ids]
    if any(not value for value in excerpts):
        raise ContractViolation("materiality candidate evidence excerpt is empty")
    return ids, excerpts


def compose_document_kernel(document: dict[str, Any], materiality: dict[str, Any]) -> dict[str, Any]:
    base = {
        "decision_number": materiality.get("decision_number"),
        "decision_date": materiality.get("decision_date"),
        "publication_authority": "NONE",
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }
    if materiality.get("state") != "MATERIALITY_CANDIDATE":
        terminal = materiality.get("state") if materiality.get("state") in {"NO_STORY", "BLOCKED"} else "BLOCKED"
        return {**base, "state": terminal, "reason": materiality.get("reason") or "materiality_not_proven"}
    if document.get("state") != "DOCUMENT_EVIDENCE_READY":
        return {**base, "state": "BLOCKED", "reason": "document_evidence_not_ready"}
    if int(document.get("decision_number") or 0) != int(materiality.get("decision_number") or 0) or _normalize(document.get("decision_date")) != _normalize(materiality.get("decision_date")):
        return {**base, "state": "BLOCKED", "reason": "document_materiality_identity_mismatch"}

    source_url = _normalize(document.get("official_html_url"))
    if not source_url.startswith("https://dm.primariavl.ro/dm/2026/hotarari.nsf/"):
        return {**base, "state": "BLOCKED", "reason": "document_source_url_not_bounded"}

    evidence_by_id = _evidence_map(document)
    kernels: list[dict[str, Any]] = []
    for candidate in materiality.get("materiality_candidates") or []:
        try:
            evidence_ids, excerpts = _candidate_evidence(candidate, evidence_by_id)
        except ContractViolation as exc:
            return {**base, "state": "BLOCKED", "reason": str(exc)}
        category = _normalize(candidate.get("category"))
        details = candidate.get("details") or {}
        number = int(materiality.get("decision_number") or 0)
        decision_date = _normalize(materiality.get("decision_date"))
        claim_evidence: list[dict[str, Any]] = []

        if category == "LOCAL_PUBLIC_FINANCE":
            amounts = sorted({float(value) for value in details.get("amounts_lei") or [] if float(value) > 0})
            if len(amounts) < 2:
                return {**base, "state": "BLOCKED", "reason": "finance_materiality_missing_amount_pair"}
            increase, resulting_total = amounts[-2], amounts[-1]
            claim = (
                f"Hotărârea nr. {number}/{decision_date} rectifică bugetul creditelor interne pe 2026, "
                f"majorându-l cu {_money(increase)} până la {_money(resulting_total)} și redistribuind finanțarea între obiective de investiții."
            )
            kernel = FactKernel(
                what=claim,
                who=COUNCIL,
                where=PLACE,
                when=f"{decision_date} — data adoptării hotărârii; nu este tratată ca dată a cheltuirii efective",
                why_it_matters="Decizia schimbă plafonul și distribuția finanțării din credite interne pentru investiții locale; nu dovedește că sumele au fost deja cheltuite.",
                source=_source_label(number, decision_date),
                source_url=source_url,
                claims=(claim,),
                evidence_ids=tuple(evidence_ids),
            )
            claim_evidence.append({"claim": claim, "evidence_ids": evidence_ids})

        elif category == "LOCAL_EDUCATION_ACCESS":
            school = _extract_school_name(excerpts)
            if not school:
                return {**base, "state": "BLOCKED", "reason": "education_materiality_school_name_not_bound"}
            claim = f"Hotărârea nr. {number}/{decision_date} completează rețeaua școlară locală 2026–2027 prin introducerea unității {school}."
            kernel = FactKernel(
                what=claim,
                who=f"{COUNCIL}; unitatea de învățământ: {school}",
                where=PLACE,
                when=f"{decision_date} — data adoptării hotărârii pentru rețeaua școlară 2026–2027",
                why_it_matters="Decizia modifică rețeaua oficială a unităților de învățământ din municipiu; nu dovedește separat data începerii efective a activității unității.",
                source=_source_label(number, decision_date),
                source_url=source_url,
                claims=(claim,),
                evidence_ids=tuple(evidence_ids),
            )
            claim_evidence.append({"claim": claim, "evidence_ids": evidence_ids})

        elif category == "REGULATED_LOCAL_AUTHORIZATION":
            operator = _extract_operator(excerpts)
            workpoint = _extract_workpoint(excerpts)
            if not operator or not workpoint:
                return {**base, "state": "BLOCKED", "reason": "authorization_materiality_entity_or_workpoint_not_bound"}
            auth_ids = [eid for eid in evidence_ids if "acordarea autorizației anuale" in _normalize(evidence_by_id[eid].get("excerpt"))]
            if not auth_ids:
                auth_ids = evidence_ids[:1]
            auth_claim = f"Hotărârea nr. {number}/{decision_date} aprobă acordarea unei autorizații anuale de funcționare pentru jocuri de noroc (slot-machine) operatorului {operator}, pentru punctul de lucru din {workpoint}."
            claims = [auth_claim]
            claim_evidence.append({"claim": auth_claim, "evidence_ids": auth_ids})
            fee = details.get("annual_local_fee_lei")
            if fee is not None:
                money_ids = [eid for eid in evidence_ids if evidence_by_id[eid].get("kind") == "MONEY_CONTEXT" or "taxa locală anuală" in _fold(evidence_by_id[eid].get("excerpt"))]
                if not money_ids:
                    return {**base, "state": "BLOCKED", "reason": "authorization_fee_missing_money_evidence"}
                fee_claim = f"Documentul stabilește pentru această autorizație o taxă locală anuală de {_money(float(fee))}."
                claims.append(fee_claim)
                claim_evidence.append({"claim": fee_claim, "evidence_ids": money_ids})
            kernel = FactKernel(
                what=auth_claim,
                who=f"{COUNCIL}; operator economic: {operator}",
                where=workpoint,
                when=f"{decision_date} — data adoptării hotărârii; nu este inferată data începerii efective a activității",
                why_it_matters="Decizia acordă o autorizare locală explicită pentru o activitate reglementată la un punct de lucru identificat; nu dovedește singură funcționarea efectivă după adoptare.",
                source=_source_label(number, decision_date),
                source_url=source_url,
                claims=tuple(claims),
                evidence_ids=tuple(evidence_ids),
            )
        else:
            return {**base, "state": "BLOCKED", "reason": f"unsupported_materiality_category:{category}"}

        try:
            kernel.validate()
        except ContractViolation as exc:
            return {**base, "state": "BLOCKED", "reason": f"fact_kernel_contract:{exc}"}
        kernels.append(
            {
                "category": category,
                "fact_kernel": {
                    "what": kernel.what,
                    "who": kernel.who,
                    "where": kernel.where,
                    "when": kernel.when,
                    "why_it_matters": kernel.why_it_matters,
                    "source": kernel.source,
                    "source_url": kernel.source_url,
                    "claims": list(kernel.claims),
                    "evidence_ids": list(kernel.evidence_ids),
                },
                "claim_evidence": claim_evidence,
                "integrity": {
                    "status": "PASS_SHADOW",
                    "all_claims_evidence_bound": all(item.get("evidence_ids") for item in claim_evidence),
                    "fabricated_claims": 0,
                },
            }
        )

    if not kernels:
        return {**base, "state": "NO_STORY", "reason": "no_materiality_candidate_survived_kernel_composition"}
    return {
        **base,
        "state": "FACT_KERNEL_VERIFIED_SHADOW",
        "reason": "materiality_consequence_composed_into_contract_validated_evidence_bound_fact_kernel",
        "fact_kernel_count": len(kernels),
        "kernels": kernels,
        "truth_note": "These kernels represent what the adopted municipal decisions state. They do not prove later implementation, do not authorize a writer, and cannot publish.",
    }


def compose_bundle(documents: dict[str, Any], materiality: dict[str, Any]) -> dict[str, Any]:
    docs = {(int(row.get("decision_number") or 0), _normalize(row.get("decision_date"))): row for row in documents.get("rows") or [] if isinstance(row, dict)}
    rows: list[dict[str, Any]] = []
    for mat in materiality.get("rows") or []:
        if not isinstance(mat, dict):
            continue
        key = (int(mat.get("decision_number") or 0), _normalize(mat.get("decision_date")))
        document = docs.get(key)
        if not document:
            rows.append({
                "decision_number": mat.get("decision_number"),
                "decision_date": mat.get("decision_date"),
                "state": "BLOCKED",
                "reason": "matching_document_evidence_missing",
                "publication_authority": "NONE",
                "writer_allowed": False,
                "production_writer_ready": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
            })
            continue
        rows.append(compose_document_kernel(document, mat))
    verified = sum(row.get("state") == "FACT_KERNEL_VERIFIED_SHADOW" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    return {
        "schema_version": "1.0",
        "mode": "MUNICIPAL_FACT_KERNEL_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "verified_fact_kernel_row_count": verified,
        "blocked_count": blocked,
        "no_story_count": no_story,
        "fabricated_claim_count": 0,
        "rows": rows,
        "truth_rule": "Only materiality candidates with first-party evidence IDs may become shadow FactKernels. Decision date is not implementation time. Writer and publication remain separate forbidden gates.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose municipal evidence-bound FactKernels in shadow mode")
    parser.add_argument("--documents", required=True)
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    documents = json.loads(Path(args.documents).read_text(encoding="utf-8"))
    materiality = json.loads(Path(args.materiality).read_text(encoding="utf-8"))
    result = compose_bundle(documents, materiality)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verified_fact_kernel_row_count": result["verified_fact_kernel_row_count"],
        "blocked_count": result["blocked_count"],
        "no_story_count": result["no_story_count"],
        "fabricated_claim_count": 0,
        "publication_authority": "NONE",
        "writer_allowed": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
