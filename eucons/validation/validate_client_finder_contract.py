#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTIVE_STATES = {"EVIDENCE_COMPLETE", "READY_FOR_SCORING"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def organization_key(org: dict[str, Any]) -> str:
    country = str(org.get("country_code") or "").strip().upper()
    registration = str(org.get("public_registration_id") or "").strip().upper()
    if registration:
        seed = f"{country}|{registration}"
    else:
        name = " ".join(str(org.get("legal_name") or "").casefold().split())
        domain = str(org.get("official_domain") or "").strip().lower()
        region = " ".join(str(org.get("region") or "").casefold().split())
        if not domain or not region:
            raise ValueError("HOLD_IDENTITY_AMBIGUOUS")
        seed = f"{country}|{name}|{domain}|{region}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def validate_contract(contract: dict[str, Any]) -> dict[str, int]:
    if contract.get("id") != "R06-CF-CONTRACT-001":
        raise ValueError("Client Finder contract id drift")
    if contract.get("status") != "CANONICAL":
        raise ValueError("Client Finder contract not canonical")
    dependencies = contract.get("canonical_dependencies") or {}
    for path in dependencies.values():
        if not (ROOT / path).is_file():
            raise ValueError(f"missing canonical dependency: {path}")

    truth = contract.get("truth_model") or {}
    if truth.get("classes") != ["FACT", "INFERENCE", "UNKNOWN", "CONFLICT"]:
        raise ValueError("truth classes drift")

    privacy = contract.get("privacy_boundary") or {}
    forbidden = set(privacy.get("person_level_fields_forbidden") or [])
    sensitive = set(privacy.get("sensitive_or_protected_inference_forbidden") or [])
    if not forbidden or not sensitive or privacy.get("visitor_deanonymization_forbidden") is not True:
        raise ValueError("privacy boundary incomplete")
    if privacy.get("private_database_enrichment_forbidden") is not True:
        raise ValueError("private enrichment must be forbidden")

    source = contract.get("source_contract") or {}
    allowed = set(source.get("allowed_types") or [])
    official = set(source.get("official_types") or [])
    discovery = set(source.get("discovery_only_types") or [])
    if not official or not discovery or not official.issubset(allowed) or not discovery.issubset(allowed):
        raise ValueError("source taxonomy invalid")
    if official & discovery:
        raise ValueError("official and discovery source classes overlap")

    services_doc = load_json(EUCONS / "services" / "service_registry.json")
    demand_doc = load_json(EUCONS / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json")
    service_ids = {row["id"] for row in services_doc.get("services") or []}
    job_ids = {
        job["id"]
        for segment in demand_doc.get("customer_segments") or []
        for job in segment.get("jobs_to_be_done") or []
    }
    if not job_ids:
        job_ids = {row["id"] for row in demand_doc.get("jobs_to_be_done") or []}

    signals = contract.get("signal_taxonomy") or []
    signal_ids = [row.get("id") for row in signals]
    if len(signals) < 8 or len(signal_ids) != len(set(signal_ids)):
        raise ValueError("signal taxonomy incomplete or duplicated")
    for row in signals:
        if row.get("priority_lane") not in {"P0", "P1", "P2"}:
            raise ValueError("invalid signal priority")
        if not set(row.get("service_ids") or []).issubset(service_ids):
            raise ValueError(f"unknown service in {row.get('id')}")
        if not set(row.get("job_ids") or []).issubset(job_ids):
            raise ValueError(f"unknown demand job in {row.get('id')}")
        ttl = row.get("default_reverify_days")
        if not isinstance(ttl, int) or ttl < 1 or ttl > 365:
            raise ValueError("invalid signal reverify interval")

    gate = contract.get("external_action_gate") or {}
    forbidden_actions = ["autonomous_send", "autonomous_call", "autonomous_social_dm", "autonomous_offer", "autonomous_price"]
    if any(gate.get(key) is not False for key in forbidden_actions):
        raise ValueError("external action gate failed open")
    if gate.get("human_approval_required") is not True:
        raise ValueError("human approval gate missing")

    return {"signals": len(signals), "services": len(service_ids), "jobs": len(job_ids)}


def validate_record(record: dict[str, Any], contract: dict[str, Any], now: datetime) -> dict[str, Any]:
    prospect = contract["prospect_record"]
    missing = [key for key in prospect["required"] if key not in record]
    if missing:
        raise ValueError(f"missing prospect fields: {missing}")

    serialized = json.dumps(record, ensure_ascii=False).casefold()
    for key in contract["privacy_boundary"]["person_level_fields_forbidden"]:
        if f'"{key.casefold()}"' in serialized:
            raise ValueError(f"person-level field forbidden: {key}")
    for key in contract["privacy_boundary"]["sensitive_or_protected_inference_forbidden"]:
        if f'"{key.casefold()}"' in serialized:
            raise ValueError(f"protected inference forbidden: {key}")

    org = record["organization"]
    for field in contract["organization_identity"]["required"]:
        if not str(org.get(field) or "").strip():
            raise ValueError(f"organization field required: {field}")
    unknown_org = set(org) - set(contract["organization_identity"]["allowed"])
    if unknown_org:
        raise ValueError(f"unknown organization fields: {sorted(unknown_org)}")
    identity_key = organization_key(org)

    source_contract = contract["source_contract"]
    allowed_types = set(source_contract["allowed_types"])
    official_types = set(source_contract["official_types"])
    sources: dict[str, dict[str, Any]] = {}
    for source in record["sources"]:
        for field in source_contract["required_fields"]:
            if field not in source or source[field] in ("", None):
                raise ValueError(f"source field required: {field}")
        source_id = source["source_id"]
        if source_id in sources:
            raise ValueError("duplicate source_id")
        if source["source_type"] not in allowed_types:
            raise ValueError("source type not allowed")
        if source["source_type"] in official_types and source["official"] is not True:
            raise ValueError("official source type not marked official")
        if source["source_type"] in source_contract["discovery_only_types"] and source["official"] is not False:
            raise ValueError("discovery source incorrectly marked official")
        parsed = urlparse(source["url"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source URL must be public HTTPS")
        if not HEX64.fullmatch(str(source["content_hash"])):
            raise ValueError("source content_hash invalid")
        parse_time(source["retrieved_at"])
        sources[source_id] = source

    assertions: dict[str, dict[str, Any]] = {}
    for assertion in record["assertions"]:
        assertion_id = assertion.get("assertion_id")
        classification = assertion.get("classification")
        if not assertion_id or assertion_id in assertions:
            raise ValueError("assertion id missing or duplicated")
        if classification not in contract["truth_model"]["classes"]:
            raise ValueError("assertion classification invalid")
        if not assertion.get("subject") or not assertion.get("statement"):
            raise ValueError("assertion subject and statement required")
        refs = assertion.get("source_refs") or []
        if any(ref not in sources for ref in refs):
            raise ValueError("assertion source reference unknown")
        if classification == "FACT":
            if not refs:
                raise ValueError("FACT requires source")
            if assertion.get("material_funding_claim") is True and not any(sources[ref]["source_type"] in official_types for ref in refs):
                raise ValueError("material funding FACT requires official source")
        elif classification == "INFERENCE":
            support = assertion.get("supported_by_fact_ids") or []
            if not support or not assertion.get("verification_question"):
                raise ValueError("INFERENCE requires FACT support and verification question")
            confidence = assertion.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("INFERENCE confidence invalid")
        elif classification == "UNKNOWN":
            if not assertion.get("verification_question"):
                raise ValueError("UNKNOWN requires verification question")
        elif classification == "CONFLICT":
            if len(refs) < 2:
                raise ValueError("CONFLICT requires at least two sources")
        assertions[assertion_id] = assertion

    fact_ids = {key for key, row in assertions.items() if row["classification"] == "FACT"}
    for row in assertions.values():
        if row["classification"] == "INFERENCE" and not set(row["supported_by_fact_ids"]).issubset(fact_ids):
            raise ValueError("INFERENCE support is not FACT")

    taxonomy = {row["id"]: row for row in contract["signal_taxonomy"]}
    active_signals = 0
    for signal in record["signals"]:
        for field in prospect["signal_required_fields"]:
            if field not in signal or signal[field] in ("", None):
                raise ValueError(f"signal field required: {field}")
        if signal["signal_type"] not in taxonomy:
            raise ValueError("unknown signal type")
        if any(ref not in sources for ref in signal["source_refs"]):
            raise ValueError("signal source reference unknown")
        facts = set(signal["fact_assertion_ids"])
        if not facts or not facts.issubset(fact_ids):
            raise ValueError("signal requires FACT assertions")
        confidence = signal["confidence"]
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("signal confidence invalid")
        if parse_time(signal["expires_at"]) <= now.astimezone(timezone.utc):
            if record["state"] in ACTIVE_STATES:
                raise ValueError("active prospect contains expired signal")
        else:
            active_signals += 1
        row = taxonomy[signal["signal_type"]]
        if not set(signal.get("job_ids") or []).issubset(set(row["job_ids"])):
            raise ValueError("signal job mapping drift")
        if not set(signal.get("service_ids") or []).issubset(set(row["service_ids"])):
            raise ValueError("signal service mapping drift")

    if record["state"] not in prospect["states"]:
        raise ValueError("invalid prospect state")
    if parse_time(record["expires_at"]) <= now.astimezone(timezone.utc) and record["state"] in ACTIVE_STATES:
        raise ValueError("active prospect expired")
    if record["state"] == "READY_FOR_SCORING" and active_signals < 1:
        raise ValueError("READY_FOR_SCORING requires active signal")
    if record["suppression"].get("active") is True and record["state"] != "SUPPRESSED":
        raise ValueError("suppression state mismatch")
    if record["state"] == "SUPPRESSED" and record["suppression"].get("active") is not True:
        raise ValueError("suppressed record missing active suppression")

    return {
        "prospect_id": record["prospect_id"],
        "organization_key": identity_key,
        "state": record["state"],
        "active_signals": active_signals,
        "eligibility_state": contract["qualification_gate"]["eligibility_state"],
        "maximum_external_state": contract["external_action_gate"]["maximum_state_from_r06"],
    }


def synthetic_record() -> dict[str, Any]:
    return {
        "prospect_id": "PROS-SYNTHETIC-001",
        "synthetic_label": "NON_EVIDENCE",
        "organization": {
            "legal_name": "Organizație sintetică pentru test",
            "country_code": "RO",
            "organization_type": "PUBLIC_INSTITUTION",
            "public_registration_id": "RO-SYNTHETIC-0001",
            "region": "Sud-Vest Oltenia",
            "official_domain": "synthetic.invalid",
        },
        "sources": [{
            "source_id": "SRC-SYNTH-001",
            "source_type": "OFFICIAL_BENEFICIARY_OR_AWARD_LIST",
            "authority": "SYNTHETIC TEST AUTHORITY",
            "url": "https://example.invalid/synthetic-award",
            "title": "Synthetic award fixture",
            "retrieved_at": "2026-08-26T00:00:00+03:00",
            "content_hash": hashlib.sha256(b"synthetic-award-v1").hexdigest(),
            "official": True,
            "public_access": True,
        }],
        "assertions": [
            {
                "assertion_id": "AST-FACT-001",
                "classification": "FACT",
                "subject": "project_award",
                "statement": "Synthetic organization appears in a synthetic award fixture.",
                "source_refs": ["SRC-SYNTH-001"],
                "material_funding_claim": False,
            },
            {
                "assertion_id": "AST-INF-001",
                "classification": "INFERENCE",
                "subject": "service_need",
                "statement": "The organization may need implementation capacity.",
                "source_refs": ["SRC-SYNTH-001"],
                "supported_by_fact_ids": ["AST-FACT-001"],
                "confidence": 0.65,
                "verification_question": "Is implementation support already contracted?",
            },
        ],
        "signals": [{
            "signal_id": "SIGNAL-SYNTH-001",
            "signal_type": "SIG-AWARDED-PROJECT",
            "source_refs": ["SRC-SYNTH-001"],
            "observed_at": "2026-08-26T00:00:00+03:00",
            "expires_at": "2026-09-25T00:00:00+03:00",
            "fact_assertion_ids": ["AST-FACT-001"],
            "confidence": 0.65,
            "why_now": "Synthetic awarded-project signal inside its revalidation window.",
            "job_ids": ["JTBD-BEN-01"],
            "service_ids": ["implementation_and_reporting"],
        }],
        "state": "READY_FOR_SCORING",
        "created_at": "2026-08-26T00:00:00+03:00",
        "updated_at": "2026-08-26T00:00:00+03:00",
        "expires_at": "2026-09-25T00:00:00+03:00",
        "suppression": {"active": False, "reason": None},
    }


def main() -> None:
    contract = load_json(EUCONS / "prospects" / "client_finder_contract.json")
    coverage = validate_contract(contract)
    fixture = synthetic_record()
    result = validate_record(fixture, contract, parse_time("2026-08-26T01:00:00+03:00"))
    if fixture.get("synthetic_label") != "NON_EVIDENCE":
        raise SystemExit("synthetic fixture evidence label missing")
    print(json.dumps({
        "status": "PASS",
        "phase": "R06",
        "unit": contract["id"],
        "signal_types": coverage["signals"],
        "service_mappings": coverage["services"],
        "demand_jobs": coverage["jobs"],
        "synthetic_record": result,
        "production_records": 0,
        "autonomous_contact": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
