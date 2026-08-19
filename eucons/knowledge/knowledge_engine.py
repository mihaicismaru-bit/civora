#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "knowledge" / "knowledge_contract.json"


class KnowledgeError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def record_id(record_type: str, source_ref: str) -> str:
    return "KNW-" + hashlib.sha256(f"{record_type}|{source_ref}".encode("utf-8")).hexdigest()[:24]


def evidence_indexes(evidence: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    items = {str(row.get("id") or ""): row for row in evidence.get("evidence_items") or []}
    if "" in items:
        raise KnowledgeError("evidence item without id")
    return items, list(evidence.get("claims") or [])


def service_claim(service_id: str, evidence: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    items, claims = evidence_indexes(evidence)
    policy = contract["service_content"]
    required_evidence = policy["required_evidence_id"]
    item = items.get(required_evidence)
    if not item or item.get("status") != "ACTIVE":
        return None
    for claim in claims:
        if (
            claim.get("object_ref") == service_id
            and claim.get("claim_class") == policy["required_claim_class"]
            and claim.get("publication_state") == policy["required_claim_state"]
            and required_evidence in (claim.get("evidence_ids") or [])
        ):
            return claim
    return None


def _service_records(service: dict[str, Any], evidence: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    sid = str(service.get("id") or "").strip()
    if not sid:
        raise KnowledgeError("service id required")
    claim = service_claim(sid, evidence, contract)
    state = "PUBLISHABLE" if claim else "HOLD"
    provenance = {
        "source_kind": "E02_SERVICE_REGISTRY",
        "source_ref": sid,
        "claim_ids": [claim["id"]] if claim else [],
        "evidence_ids": list(claim.get("evidence_ids") or []) if claim else [],
    }
    label = str(service.get("label") or sid)
    summary = str(service.get("summary") or "")
    deliverables = copy.deepcopy(service.get("deliverables") or [])
    process = copy.deepcopy(service.get("process") or [])
    boundaries = copy.deepcopy(service.get("boundaries") or [])
    if state == "PUBLISHABLE" and (not summary or not deliverables or not boundaries):
        raise KnowledgeError("publishable service knowledge requires canonical summary, deliverables and boundaries")

    return [
        {
            "id": record_id("GUIDE", sid), "type": "GUIDE", "publication_state": state,
            "source_ref": sid, "title": f"Ghid: {label}", "summary": summary,
            "sections": {"livrabile": deliverables, "limite": boundaries},
            "semantics": "CANONICAL_SERVICE_DESCRIPTION", "provenance": copy.deepcopy(provenance),
        },
        {
            "id": record_id("ANALYSIS", sid), "type": "ANALYSIS", "publication_state": state,
            "source_ref": sid, "title": f"Cum abordăm {label.lower()}", "summary": summary,
            "sections": {"proces": process, "puncte_de_control": boundaries},
            "semantics": "OPERATIONAL_INTERPRETATION_NOT_FUNDING_FACT",
            "analysis_label": "Analiză operațională bazată pe serviciul canonic; nu modifică și nu afirmă fapte administrative de finanțare.",
            "provenance": copy.deepcopy(provenance),
        },
        {
            "id": record_id("FAQ", sid), "type": "FAQ", "publication_state": state,
            "source_ref": sid, "title": f"Ce include serviciul «{label}»?", "summary": summary,
            "sections": {"include": deliverables, "nu_presupune_implicit": boundaries},
            "semantics": "CANONICAL_SERVICE_DESCRIPTION", "provenance": copy.deepcopy(provenance),
        },
    ]


def _opportunity_records(projection: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    if not projection:
        return []
    policy = contract["opportunity_content"]
    if projection.get("bridge_id") != policy["required_bridge_id"]:
        raise KnowledgeError("unknown opportunity bridge")
    records = []
    seen = set()
    bridge_ready = projection.get("bridge_state") == policy["required_bridge_state"]
    for row in projection.get("opportunities") or []:
        source_id = str(row.get("id") or "").strip()
        if not source_id or source_id in seen:
            raise KnowledgeError("duplicate or missing opportunity source id")
        seen.add(source_id)
        provenance = copy.deepcopy(row.get("provenance") or {})
        if provenance.get("source_product") != "PARTENER.EU" or provenance.get("source_opportunity_id") != source_id:
            raise KnowledgeError("opportunity provenance mismatch")
        publishable = (
            bridge_ready
            and row.get("commercial_state") == policy["required_record_state"]
            and (not policy["requires_actionable"] or row.get("actionable") is True)
        )
        records.append({
            "id": record_id("OPPORTUNITY", source_id), "type": "OPPORTUNITY",
            "publication_state": "PUBLISHABLE" if publishable else policy["stale_or_nonactionable_state"],
            "source_ref": source_id, "title": row.get("title") or "",
            "summary": f"{row.get('programme') or ''} — {row.get('status') or ''}".strip(" —"),
            "material_facts": copy.deepcopy(row.get("material_facts") or {}),
            "verified_fact_classes": copy.deepcopy(row.get("verified_fact_classes") or []),
            "semantics": "VERIFIED_FUNDING_FACTS_FROM_E09" if publishable else "WITHHELD_FUNDING_FACTS",
            "provenance": provenance,
        })
    return records


def _case_records(case_registry: dict[str, Any], evidence: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    policy = contract["case_content"]
    evidence_items, evidence_claim_rows = evidence_indexes(evidence)
    claims = {str(row.get("id") or ""): row for row in evidence_claim_rows}
    records = []
    seen = set()
    for case in case_registry.get("cases") or []:
        cid = str(case.get("id") or "").strip()
        if not cid or cid in seen:
            raise KnowledgeError("duplicate or missing case id")
        seen.add(cid)
        publishable = case.get("publication_state") == policy["required_registry_state"]
        claim_ids = list(dict.fromkeys([
            *(case.get("result_claim_ids") or []),
            *(case.get("outcome_claim_ids") or []),
        ]))
        evidence_ids: list[str] = []
        if publishable:
            if not claim_ids:
                raise KnowledgeError("publishable case requires result claim lineage")
            for claim_id in claim_ids:
                claim = claims.get(str(claim_id))
                if not claim or claim.get("claim_class") != "PROJECT_RESULT" or claim.get("publication_state") != "PUBLISHABLE":
                    raise KnowledgeError("publishable case references invalid project-result claim")
                for evidence_id in claim.get("evidence_ids") or []:
                    item = evidence_items.get(str(evidence_id))
                    if not item or item.get("status") != "ACTIVE":
                        raise KnowledgeError("publishable case references inactive or missing evidence")
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)
            problem = str(case.get("public_problem") or "").strip()
            intervention = str(case.get("public_intervention") or "").strip()
            outcomes = copy.deepcopy(case.get("public_outcomes") or [])
            if not problem or not intervention or not outcomes:
                raise KnowledgeError("publishable case requires public problem, intervention and outcomes")
        else:
            problem, intervention, outcomes = "", "", []
            claim_ids, evidence_ids = [], []
        records.append({
            "id": record_id("CASE", cid), "type": "CASE",
            "publication_state": "PUBLISHABLE" if publishable else "HOLD",
            "source_ref": cid, "title": case.get("title") or "",
            "summary": intervention,
            "sections": {"problema": problem, "interventie": intervention, "rezultate": outcomes} if publishable else {},
            "semantics": "VERIFIED_CASE_REGISTRY" if publishable else "WITHHELD_CASE",
            "provenance": {
                "source_kind": "E05_CASE_REGISTRY",
                "source_ref": cid,
                "claim_refs": copy.deepcopy(claim_ids),
                "claim_ids": claim_ids,
                "evidence_ids": evidence_ids,
            },
        })
    return records


def build_knowledge(
    service_registry: dict[str, Any], evidence: dict[str, Any], opportunity_projection: dict[str, Any],
    case_registry: dict[str, Any], contract: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for service in service_registry.get("services") or []:
        records.extend(_service_records(service, evidence, contract))
    records.extend(_opportunity_records(opportunity_projection, contract))
    records.extend(_case_records(case_registry, evidence, contract))
    ids = [row["id"] for row in records]
    if len(ids) != len(set(ids)):
        raise KnowledgeError("duplicate knowledge record id")
    allowed_types = set(contract["record_types"])
    if any(row["type"] not in allowed_types for row in records):
        raise KnowledgeError("unknown knowledge type")
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "provider_neutral": contract["output"]["provider_neutral"],
        "runtime_publication_enabled": contract["output"]["runtime_publication_enabled"],
        "summary": {
            "records": len(records),
            "publishable": sum(row["publication_state"] == "PUBLISHABLE" for row in records),
            "held": sum(row["publication_state"] != "PUBLISHABLE" for row in records),
            "by_type": {kind: sum(row["type"] == kind for row in records) for kind in contract["record_types"]},
        },
        "records": records,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise KnowledgeError("runtime knowledge output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", default=str(EUCONS / "services" / "service_registry.json"))
    parser.add_argument("--evidence", default=str(EUCONS / "evidence" / "evidence_registry.json"))
    parser.add_argument("--opportunities", required=True)
    parser.add_argument("--cases", default=str(EUCONS / "cases" / "case_study_registry.json"))
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_knowledge(load_json(Path(args.services)), load_json(Path(args.evidence)), load_json(Path(args.opportunities)), load_json(Path(args.cases)), load_json(Path(args.contract)))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
