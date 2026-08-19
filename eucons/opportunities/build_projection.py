#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "bridge_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso(value: str) -> datetime:
    if not value:
        raise ValueError("missing timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_partener_payload(path: Path, prefix: str) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    text = raw.strip()
    if not text.startswith(prefix):
        raise ValueError(f"unexpected PARTENER projection prefix in {path}")
    payload = text[len(prefix):].strip()
    if payload.endswith(";"):
        payload = payload[:-1].rstrip()
    return json.loads(payload), digest


def policy_is_acceptable(source: dict[str, Any], contract: dict[str, Any]) -> bool:
    policy = source.get("policy") or {}
    required = contract["source"]["required_policy"]
    if policy.get("integrityGate") != contract["source"]["required_integrity_gate"]:
        return False
    return all(policy.get(key) == expected for key, expected in required.items())


def freshness_state(source_as_of: str | None, reference_time: datetime, contract: dict[str, Any]) -> dict[str, Any]:
    maximum = int(contract["freshness"]["max_age_hours"]) * 3600
    future_tolerance = int(contract["freshness"]["future_skew_tolerance_minutes"]) * 60
    try:
        observed = parse_iso(source_as_of or "")
    except (ValueError, TypeError):
        return {"state": "INVALID_TIME", "age_seconds": None, "max_age_seconds": maximum}
    age = int((reference_time - observed).total_seconds())
    if age < -future_tolerance:
        return {"state": "FUTURE_TIME", "age_seconds": age, "max_age_seconds": maximum}
    age = max(age, 0)
    return {
        "state": "FRESH" if age <= maximum else "STALE",
        "age_seconds": age,
        "max_age_seconds": maximum,
    }


def project_material_facts(opportunity: dict[str, Any], contract: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    verified = set(opportunity.get("verifiedFactClasses") or [])
    allowed = set(contract["admission"]["allowed_material_fact_classes"])
    material = opportunity.get("materialFacts") or {}
    classes = sorted(verified & allowed & set(material.keys()))
    return {key: copy.deepcopy(material[key]) for key in classes}, classes


def admitted(opportunity: dict[str, Any], contract: dict[str, Any]) -> bool:
    admission = contract["admission"]
    if opportunity.get("publicationState") != admission["required_publication_state"]:
        return False
    decision = (opportunity.get("publicationDecision") or {}).get("decision")
    if decision != admission["required_decision"]:
        return False
    if len(opportunity.get("verificationEvidence") or []) < int(admission["minimum_verified_evidence"]):
        return False
    return bool(opportunity.get("verifiedFactClasses"))


def build_projection(source: dict[str, Any], source_hash: str, contract: dict[str, Any], reference_time: datetime) -> dict[str, Any]:
    source_copy = copy.deepcopy(source)
    fresh = freshness_state(source.get("asOf"), reference_time, contract)
    policy_ok = policy_is_acceptable(source, contract)
    records: list[dict[str, Any]] = []

    if policy_ok:
        for item in source.get("opportunities") or []:
            if not admitted(item, contract):
                continue
            material, fact_classes = project_material_facts(item, contract)
            stale = fresh["state"] != "FRESH"
            actionable_requires = set(contract["admission"]["open_actionable_requires"])
            actionable = (
                not stale
                and item.get("status") == "OPEN"
                and actionable_requires.issubset(set(fact_classes))
            )
            records.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "programme": item.get("programme"),
                "code": item.get("code"),
                "status": item.get("status"),
                "commercial_state": (
                    contract["output"]["fresh_record_state"]
                    if not stale else contract["output"]["stale_record_state"]
                ),
                "actionable": actionable,
                "verified_fact_classes": fact_classes,
                "material_facts": material,
                "provenance": {
                    "source_product": contract["source"]["product"],
                    "source_path": contract["source"]["path"],
                    "source_opportunity_id": item.get("id"),
                    "source_as_of": source.get("asOf"),
                    "source_projection_sha256": source_hash,
                    "publication_decision": copy.deepcopy(item.get("publicationDecision") or {}),
                    "verification_evidence": copy.deepcopy(item.get("verificationEvidence") or []),
                },
            })

    if source != source_copy:
        raise AssertionError("PARTENER source payload mutated during EUCONS projection")

    bridge_state = "READY" if policy_ok else contract["output"]["source_policy_rejected_state"]
    if policy_ok and fresh["state"] != "FRESH":
        bridge_state = "STALE_SOURCE_HOLD"

    return {
        "schema_version": contract["output"]["schema_version"],
        "product": "EUCONS_COMMERCIAL_OS",
        "bridge_id": contract["bridge_id"],
        "generated_at": iso_z(reference_time),
        "bridge_state": bridge_state,
        "read_only": contract["mode"] == "READ_ONLY",
        "source_mutation_allowed": contract["output"]["source_mutation_allowed"],
        "source": {
            "product": contract["source"]["product"],
            "path": contract["source"]["path"],
            "schema_version": source.get("schemaVersion"),
            "as_of": source.get("asOf"),
            "sha256": source_hash,
            "policy_accepted": policy_ok,
        },
        "freshness": fresh,
        "summary": {
            "source_opportunity_count": len(source.get("opportunities") or []),
            "admitted_verified_count": len(records),
            "actionable_open_count": sum(1 for row in records if row["actionable"]),
            "held_stale_count": sum(1 for row in records if row["commercial_state"] == contract["output"]["stale_record_state"]),
        },
        "opportunities": records,
    }


def build_from_paths(source_path: Path, contract_path: Path, reference_time: datetime) -> dict[str, Any]:
    contract = load_json(contract_path)
    source, source_hash = load_partener_payload(source_path, contract["source"]["expected_prefix"])
    return build_projection(source, source_hash, contract, reference_time)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=str(EUCONS / "opportunities" / "opportunity_projection.json"))
    parser.add_argument("--reference-time", default=None, help="ISO-8601; defaults to current UTC")
    args = parser.parse_args()

    contract_path = Path(args.contract)
    contract = load_json(contract_path)
    source_path = Path(args.source) if args.source else ROOT / contract["source"]["path"]
    reference = parse_iso(args.reference_time) if args.reference_time else datetime.now(timezone.utc)
    projection = build_from_paths(source_path, contract_path, reference)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(projection["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
