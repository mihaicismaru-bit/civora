#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ENGINE_PATH = EUCONS / "opportunities" / "match_operator_explainability.py"
CONTRACT_PATH = EUCONS / "opportunities" / "match_operator_explainability_contract.json"
MATCHING_CONTRACT_PATH = EUCONS / "opportunities" / "matching_contract.json"
QUEUE_CONTRACT_PATH = EUCONS / "opportunities" / "official_source_operator_queue_contract.json"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_match_operator_explainability", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load match operator explainability engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


def match_row(
    opportunity_id: str,
    *,
    state: str,
    authority_state: str,
    score: int = 0,
    confidence: str = "LOW",
    fact_classes: list[str] | None = None,
    explanations: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> dict:
    return {
        "opportunity_id": opportunity_id,
        "title": f"Opportunity {opportunity_id}",
        "programme": "Programme X",
        "score": score,
        "score_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
        "confidence": confidence,
        "state": state,
        "authority_state": authority_state,
        "official_fact_classes": fact_classes or [],
        "official_source_count": 1 if fact_classes else 0,
        "explanations": explanations or [],
        "hard_exclusion_reasons": exclusions or [],
        "source_provenance": {"source_product": "PARTENER.EU", "role": "DISCOVERY_ONLY"},
    }


def queue_task(
    opportunity_id: str,
    *,
    priority: str,
    authority_state: str,
    reason_code: str,
    operator_action: str,
    verified: list[str] | None = None,
    missing: list[str] | None = None,
    unbound: list[str] | None = None,
) -> dict:
    return {
        "opportunity_id": opportunity_id,
        "title": f"Opportunity {opportunity_id}",
        "programme": "Programme X",
        "priority": priority,
        "authority_state": authority_state,
        "reason_code": reason_code,
        "operator_action": operator_action,
        "required_candidate_fact_classes": ["deadline", "status"],
        "verified_fact_classes": verified or [],
        "missing_candidate_fact_classes": missing or [],
        "unbound_material_fact_classes": unbound or [],
        "official_source_count": 1 if verified else 0,
        "discovery_context": {"source_product": "PARTENER.EU", "role": "DISCOVERY_ONLY", "source_as_of": "2026-08-29T00:00:00Z"},
        "external_action_authorized": False,
    }


def fixtures() -> tuple[dict, dict]:
    match = {
        "schema_version": 2,
        "engine_id": "EUCONS_E10_OPPORTUNITY_MATCHING",
        "profile_id": "profile-test-001",
        "score_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
        "bridge_state": "READY",
        "partener_role": "DISCOVERY_ONLY",
        "summary": {},
        "results": [
            match_row(
                "opp-blocked",
                state="HOLD_SOURCE_STATE",
                authority_state="BLOCKED_SOURCE_CONFLICT",
                explanations=["Official-source conflict is unresolved; no material fact is authoritative.", "PARTENER.EU remains discovery/intelligence only."],
            ),
            match_row(
                "opp-waiting",
                state="HOLD_SOURCE_STATE",
                authority_state="WAITING_SOURCE",
                explanations=["Waiting for official-source binding of: deadline, status.", "PARTENER.EU remains discovery/intelligence only."],
            ),
            match_row(
                "opp-candidate",
                state="MATCH_CANDIDATE",
                authority_state="OFFICIAL_SOURCE_VERIFIED",
                score=65,
                confidence="MEDIUM",
                fact_classes=["status", "deadline", "grant"],
                explanations=[
                    "relevance terms found in discovery metadata or officially bound facts: digitalizare",
                    "organization terms found in discovery metadata or officially bound facts: imm",
                    "requested grant is within officially bound cap (100000 EUR)",
                ],
            ),
            match_row(
                "opp-needs-data",
                state="REQUIRES_DATA",
                authority_state="OFFICIAL_SOURCE_VERIFIED",
                score=0,
                confidence="LOW",
                fact_classes=["status", "deadline"],
                explanations=["No sufficiently specific relevance signal was found; more project data is required."],
            ),
            match_row(
                "opp-excluded",
                state="EXCLUDED_KNOWN_RULE",
                authority_state="OFFICIAL_SOURCE_VERIFIED",
                score=0,
                confidence="LOW",
                fact_classes=["status", "deadline", "grant"],
                explanations=["The requested grant exceeds an officially bound source cap."],
                exclusions=["requested_grant_eur=200000 exceeds officially_bound_cap_eur=100000"],
            ),
        ],
    }
    queue = {
        "schema_version": 1,
        "engine_id": "EUCONS_E10_OFFICIAL_SOURCE_OPERATOR_QUEUE",
        "state": "READ_ONLY_OPERATOR_QUEUE",
        "read_only": True,
        "source_projection_sha256": "1" * 64,
        "official_registry_state": "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS",
        "summary": {},
        "tasks": [
            queue_task(
                "opp-blocked",
                priority="P0",
                authority_state="BLOCKED_SOURCE_CONFLICT",
                reason_code="OFFICIAL_SOURCE_CONFLICT",
                operator_action="RESOLVE_OFFICIAL_SOURCE_CONFLICT",
            ),
            queue_task(
                "opp-waiting",
                priority="P1",
                authority_state="WAITING_SOURCE",
                reason_code="REQUIRED_OFFICIAL_BINDING_MISSING",
                operator_action="VERIFY_REQUIRED_OFFICIAL_FACTS",
                missing=["deadline", "status"],
            ),
            queue_task(
                "opp-candidate",
                priority="P2",
                authority_state="OFFICIAL_SOURCE_VERIFIED",
                reason_code="OPTIONAL_MATCHING_FACT_BINDINGS_INCOMPLETE",
                operator_action="ENRICH_OFFICIAL_MATERIAL_FACT_BINDINGS",
                verified=["deadline", "grant", "status"],
                unbound=["eligibility"],
            ),
        ],
        "boundaries": {
            "network_fetch": False,
            "crm_write": False,
            "provider_write": False,
            "mysmis_write": False,
            "outreach": False,
            "message_send": False,
            "offer_send": False,
            "publication": False,
            "deployment": False,
        },
        "queue_id": "2" * 64,
    }
    return match, queue


def main() -> None:
    engine = load_engine()
    contract = load_json(CONTRACT_PATH)
    matching_contract = load_json(MATCHING_CONTRACT_PATH)
    queue_contract = load_json(QUEUE_CONTRACT_PATH)
    match, queue = fixtures()

    first = engine.build_explainability(match, queue, contract, matching_contract, queue_contract)
    second = engine.build_explainability(deepcopy(match), deepcopy(queue), contract, matching_contract, queue_contract)
    assert first == second
    assert first["state"] == "READ_ONLY_MATCH_EXPLAINABILITY"
    assert first["partener_role"] == "DISCOVERY_ONLY"
    assert first["summary"] == {
        "evaluated": 5,
        "blocked_source_conflict": 1,
        "waiting_source": 1,
        "candidate_for_human_review": 1,
        "needs_profile_detail": 1,
        "excluded_by_known_rule": 1,
        "authority_queue_pending": 3,
        "numeric_scores_visible": 2,
    }
    by_id = {row["opportunity_id"]: row for row in first["results"]}
    assert by_id["opp-blocked"]["disposition"] == "BLOCKED_SOURCE_CONFLICT"
    assert by_id["opp-blocked"]["score_display"] == {
        "visibility": "WITHHELD",
        "value": None,
        "semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
    }
    assert by_id["opp-blocked"]["source_followup_action"] == "RESOLVE_OFFICIAL_SOURCE_CONFLICT"
    assert by_id["opp-waiting"]["disposition"] == "WAITING_SOURCE"
    assert by_id["opp-waiting"]["source_followup_action"] == "VERIFY_REQUIRED_OFFICIAL_FACTS"
    assert by_id["opp-candidate"]["disposition"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert by_id["opp-candidate"]["score_display"]["value"] == 65
    assert by_id["opp-candidate"]["confidence"]["level"] == "MEDIUM"
    assert by_id["opp-candidate"]["reason_codes"] == ["GRANT_WITHIN_OFFICIAL_CAP", "INVESTMENT_TERM_MATCH", "ORGANIZATION_TERM_MATCH"]
    assert by_id["opp-candidate"]["source_followup_action"] == "ENRICH_OFFICIAL_MATERIAL_FACT_BINDINGS"
    assert by_id["opp-needs-data"]["disposition"] == "NEEDS_PROFILE_DETAIL"
    assert by_id["opp-needs-data"]["reason_codes"] == ["INSUFFICIENT_SPECIFIC_SIGNAL"]
    assert by_id["opp-excluded"]["disposition"] == "EXCLUDED_BY_KNOWN_RULE"
    assert by_id["opp-excluded"]["score_display"]["visibility"] == "WITHHELD"
    assert by_id["opp-excluded"]["reason_codes"] == ["REQUESTED_GRANT_ABOVE_OFFICIAL_CAP"]
    rendered = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert "200000" not in rendered and "100000" not in rendered
    assert "digitalizare" not in rendered and "imm" not in rendered
    assert "source_provenance" not in rendered
    assert "profile-test-001" not in rendered
    assert all(row["external_action_authorized"] is False for row in first["results"])
    assert all(value is False for value in first["boundaries"].values())

    bad = deepcopy(match)
    bad["score_semantics"] = "APPROVAL_PROBABILITY"
    must_fail("root score semantics drift", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad = deepcopy(match)
    bad["results"][2]["score_semantics"] = "APPROVAL_PROBABILITY"
    must_fail("row score semantics drift", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad = deepcopy(match)
    bad["partener_role"] = "AUTHORITATIVE"
    must_fail("PARTENER authority drift", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad = deepcopy(match)
    bad["results"][1]["score"] = 10
    must_fail("waiting numeric score", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad_queue = deepcopy(queue)
    bad_queue["tasks"] = [task for task in bad_queue["tasks"] if task["opportunity_id"] != "opp-waiting"]
    must_fail("missing waiting queue task", lambda: engine.build_explainability(match, bad_queue, contract, matching_contract, queue_contract))

    bad_queue = deepcopy(queue)
    next(task for task in bad_queue["tasks"] if task["opportunity_id"] == "opp-blocked")["priority"] = "P2"
    must_fail("blocked priority drift", lambda: engine.build_explainability(match, bad_queue, contract, matching_contract, queue_contract))

    bad_queue = deepcopy(queue)
    bad_queue["boundaries"]["outreach"] = True
    must_fail("operator queue boundary enabled", lambda: engine.build_explainability(match, bad_queue, contract, matching_contract, queue_contract))

    bad = deepcopy(match)
    bad["results"][2]["explanations"] = ["opaque model says this looks good"]
    must_fail("unmapped positive explanation", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad = deepcopy(match)
    bad["results"][4]["hard_exclusion_reasons"] = ["opaque exclusion"]
    must_fail("unmapped hard exclusion", lambda: engine.build_explainability(bad, queue, contract, matching_contract, queue_contract))

    bad_queue = deepcopy(queue)
    bad_queue["tasks"].append(deepcopy(bad_queue["tasks"][0]))
    must_fail("duplicate operator task", lambda: engine.build_explainability(match, bad_queue, contract, matching_contract, queue_contract))

    bad_contract = deepcopy(contract)
    bad_contract["boundaries"]["crm_write"] = True
    must_fail("explainability boundary enabled", lambda: engine.build_explainability(match, queue, bad_contract, matching_contract, queue_contract))

    must_fail("repository runtime output", lambda: engine.ensure_output_outside_repo(EUCONS / "runtime-explainability.json"))

    print("PASS: match operator explainability is source-aware, coarse-grained, deterministic and fail-closed")


if __name__ == "__main__":
    main()
