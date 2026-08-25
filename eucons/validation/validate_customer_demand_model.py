#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json"
SERVICE_REGISTRY = ROOT / "services" / "service_registry.json"

ALLOWED_CLASSES = {"FACT", "INFERENCE", "UNKNOWN", "CONFLICT", "HYPOTHESIS"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
REQUIRED_AUDIENCES = {
    "companies_entrepreneurs",
    "public_authorities_institutions",
    "ngos_eligible_organizations",
    "existing_beneficiaries",
}
REQUIRED_SPECIALIST_SEGMENTS = {"SEG-TRAINING", "SEG-RURAL", "SEG-BENEFICIARY"}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def nonempty_list(value, label):
    require(isinstance(value, list) and value, f"{label} must be a non-empty list")
    require(all(isinstance(item, str) and item.strip() for item in value), f"{label} contains an empty/invalid value")


def unique_ids(items, label):
    ids = []
    for item in items:
        require(isinstance(item, dict), f"{label} contains a non-object")
        item_id = item.get("id")
        require(isinstance(item_id, str) and item_id.strip(), f"{label} contains a missing/invalid id")
        ids.append(item_id)
    require(len(ids) == len(set(ids)), f"{label} contains duplicate ids")
    return set(ids)


def validate(model_path=DEFAULT_MODEL):
    data = json.loads(Path(model_path).read_text(encoding="utf-8"))
    services = json.loads(SERVICE_REGISTRY.read_text(encoding="utf-8"))
    service_ids = {item["id"] for item in services.get("services", [])}

    require(data.get("product") == "EUCONS_COMMERCIAL_OS", "wrong product identifier")
    require(data.get("id") == "R02-CDM-001", "wrong model id")
    require(data.get("phase") == "R02_CUSTOMER_DEMAND_MODEL", "wrong phase")
    require(data.get("status") == "CANONICAL", "status must be CANONICAL")

    truth = data.get("truth_model") or {}
    require(set(truth.get("allowed_classes") or []) == ALLOWED_CLASSES, "truth classes are incomplete")
    for key in ("rule", "performance_rule", "privacy_rule"):
        require(str(truth.get(key, "")).strip(), f"truth_model missing {key}")

    facts = data.get("market_facts") or []
    require(len(facts) >= 4, "at least four market facts are required")
    unique_ids(facts, "market_facts")
    for fact in facts:
        require(fact.get("classification") == "FACT", f"{fact['id']} is not classified FACT")
        require(fact.get("publicability") == "PUBLIC_VERIFIED", f"{fact['id']} is not PUBLIC_VERIFIED")
        require(str(fact.get("authority", "")).strip(), f"{fact['id']} missing authority")
        nonempty_list(fact.get("evidence_urls"), f"{fact['id']}.evidence_urls")
        require(all(url.startswith("https://") for url in fact["evidence_urls"]), f"{fact['id']} has non-HTTPS evidence")
        require(str(fact.get("verified_at", "")).strip(), f"{fact['id']} missing verified_at")
        if fact.get("material_claim") is True:
            require(fact["authority"] not in {"Competitor", "Market hypothesis"}, f"{fact['id']} material claim lacks authoritative source")

    segments = data.get("customer_segments") or []
    require(len(segments) >= 6, "at least six operational segments are required")
    segment_ids = unique_ids(segments, "customer_segments")
    audience_ids = set()
    for segment in segments:
        require(segment.get("priority") in ALLOWED_PRIORITIES, f"{segment['id']} invalid priority")
        audience_id = segment.get("canonical_audience_id")
        require(audience_id in REQUIRED_AUDIENCES, f"{segment['id']} unknown canonical audience")
        audience_ids.add(audience_id)
        require(str(segment.get("inclusion", "")).strip(), f"{segment['id']} missing inclusion")
        nonempty_list(segment.get("exclusions"), f"{segment['id']}.exclusions")
        nonempty_list(segment.get("core_objections"), f"{segment['id']}.core_objections")
    require(REQUIRED_AUDIENCES <= audience_ids, "not all canonical audiences have an operational segment")
    require(REQUIRED_SPECIALIST_SEGMENTS <= segment_ids, "required specialist segments are missing")

    triggers = data.get("trigger_taxonomy") or []
    require(len(triggers) >= 8, "at least eight trigger types are required")
    trigger_ids = unique_ids(triggers, "trigger_taxonomy")
    for trigger in triggers:
        nonempty_list(trigger.get("source_classes"), f"{trigger['id']}.source_classes")
        require(isinstance(trigger.get("default_expiry_days"), int) and trigger["default_expiry_days"] > 0, f"{trigger['id']} invalid expiry")
        require(str(trigger.get("classification", "")).strip(), f"{trigger['id']} missing classification")
        require(str(trigger.get("allowed_inference", "")).strip(), f"{trigger['id']} missing inference boundary")

    jobs = data.get("demand_matrix") or []
    minimum_jobs = (data.get("acceptance") or {}).get("minimum_jobs", 12)
    require(len(jobs) >= minimum_jobs, f"fewer than {minimum_jobs} demand jobs")
    unique_ids(jobs, "demand_matrix")
    used_segments = set()
    used_services = set()
    for job in jobs:
        segment_id = job.get("segment_id")
        require(segment_id in segment_ids, f"{job['id']} references unknown segment")
        used_segments.add(segment_id)
        require(job.get("priority") in ALLOWED_PRIORITIES, f"{job['id']} invalid priority")
        require(str(job.get("job", "")).strip(), f"{job['id']} missing job statement")
        require(str(job.get("moment", "")).strip(), f"{job['id']} missing moment")
        nonempty_list(job.get("trigger_ids"), f"{job['id']}.trigger_ids")
        unknown_triggers = set(job["trigger_ids"]) - trigger_ids
        require(not unknown_triggers, f"{job['id']} references unknown triggers: {sorted(unknown_triggers)}")
        nonempty_list(job.get("service_ids"), f"{job['id']}.service_ids")
        unknown_services = set(job["service_ids"]) - service_ids
        require(not unknown_services, f"{job['id']} references unknown services: {sorted(unknown_services)}")
        used_services.update(job["service_ids"])
        for key in ("evidence_needed", "search_intents", "acquisition_channels"):
            nonempty_list(job.get(key), f"{job['id']}.{key}")
        require(str(job.get("recommended_next_action", "")).strip(), f"{job['id']} missing next action")
    require(used_segments == segment_ids, f"segments without demand jobs: {sorted(segment_ids - used_segments)}")
    require(len(used_services) >= 7, "demand model does not exercise enough canonical services")

    hypotheses = data.get("acquisition_hypotheses") or []
    require(len(hypotheses) >= 4, "at least four acquisition hypotheses are required")
    unique_ids(hypotheses, "acquisition_hypotheses")
    for hypothesis in hypotheses:
        require(hypothesis.get("classification") == "HYPOTHESIS", f"{hypothesis['id']} must remain HYPOTHESIS")
        require(str(hypothesis.get("statement", "")).strip(), f"{hypothesis['id']} missing statement")
        require(str(hypothesis.get("validation_plan", "")).strip(), f"{hypothesis['id']} missing validation plan")

    implications = data.get("product_implications") or []
    require(len(implications) >= 5, "at least five product implications are required")
    unique_ids(implications, "product_implications")
    ranks = [item.get("rank") for item in implications]
    require(ranks == sorted(ranks) and len(ranks) == len(set(ranks)), "product implication ranks must be unique and ordered")

    acceptance = data.get("acceptance") or {}
    require(set(acceptance.get("required_segment_lanes") or []) == REQUIRED_AUDIENCES, "acceptance audience lanes drifted")
    require(set(acceptance.get("required_specialist_segments") or []) == REQUIRED_SPECIALIST_SEGMENTS, "specialist acceptance lanes drifted")
    for key in ("no_autonomous_contact", "no_inferred_eligibility", "no_synthetic_performance"):
        require(acceptance.get(key) is True, f"{key} must be true")

    decision = data.get("decision") or {}
    require(decision.get("state") == "PASS", "decision must be PASS")
    require((decision.get("next_unit") or {}).get("id") == "R03-SEA-001", "next unit must be R03-SEA-001")

    return {
        "segments": len(segments),
        "jobs": len(jobs),
        "triggers": len(triggers),
        "facts": len(facts),
        "hypotheses": len(hypotheses),
    }


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MODEL
    try:
        counts = validate(path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SystemExit(f"EUCONS R02 customer demand validation failed: {exc}")
    print(
        "EUCONS R02 customer demand model valid: "
        f"{counts['segments']} segments, {counts['jobs']} jobs, "
        f"{counts['triggers']} triggers, {counts['facts']} sourced facts, "
        f"{counts['hypotheses']} explicit hypotheses"
    )


if __name__ == "__main__":
    main()
