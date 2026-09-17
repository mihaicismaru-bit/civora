#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ADAPTER_PATH = EUCONS / "opportunities" / "official_source_receipt_adapter.py"
ADAPTER_CONTRACT_PATH = EUCONS / "opportunities" / "official_source_receipt_adapter_contract.json"
MATCHING_CONTRACT_PATH = EUCONS / "opportunities" / "matching_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module("official_source_receipt_adapter_tests", ADAPTER_PATH)
MATCHER = load_module("opportunity_matcher_for_receipt_adapter_tests", EUCONS / "opportunities" / "match_opportunities.py")
CONTRACT = json.loads(ADAPTER_CONTRACT_PATH.read_text(encoding="utf-8"))
MATCHING_CONTRACT = json.loads(MATCHING_CONTRACT_PATH.read_text(encoding="utf-8"))
REFERENCE_TIME = "2026-08-29T05:00:00Z"


def opportunity(item_id: str, deadline: str = "2026-10-01T12:00:00+03:00") -> dict:
    return {
        "id": item_id,
        "title": "Investiții în energie solară pentru întreprinderi",
        "programme": "Program oficial test",
        "code": "TEST",
        "status": "OPEN",
        "commercial_state": "VERIFIED_AVAILABLE",
        "actionable": True,
        "verified_fact_classes": ["status", "deadline", "eligibility", "grant"],
        "material_facts": {
            "status": "OPEN",
            "deadline": {"closes_at": deadline},
            "eligibility": {
                "activity_codes_at_application": ["CAEN 10"],
                "eligible_classes": ["întreprindere agricolă"],
            },
            "grant": {"maximum_eur": 1000000},
        },
        "provenance": {
            "source_product": "PARTENER.EU",
            "source_opportunity_id": item_id,
            "verification_evidence": [{"id": "DISCOVERY-EV"}],
        },
    }


def projection(*items: dict) -> dict:
    return {
        "product": "EUCONS_COMMERCIAL_OS",
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "bridge_state": "READY",
        "read_only": True,
        "source_mutation_allowed": False,
        "opportunities": list(items),
    }


def readback(
    item: dict,
    classes: list[str],
    *,
    source_product: str = "MIPE",
    source_authority: str = "Ministerul Investițiilor și Proiectelor Europene",
    source_url: str = "https://mfe.gov.ro/program-test",
    document_char: str = "d",
    verified_at: str = "2026-08-29T04:00:00Z",
    state: str = "OFFICIAL_READBACK_COMPLETE",
    conflicts: list[str] | None = None,
    overrides: dict | None = None,
) -> dict:
    facts = {name: deepcopy(item["material_facts"][name]) for name in classes}
    if overrides:
        facts.update(deepcopy(overrides))
    return {
        "opportunity_id": item["id"],
        "readback_state": state,
        "source_product": source_product,
        "source_authority": source_authority,
        "source_url": source_url,
        "source_document_sha256": document_char * 64,
        "verified_at": verified_at,
        "fact_values": facts,
        "conflict_fact_classes": list(conflicts or []),
    }


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, AssertionError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    ADAPTER.validate_contract(CONTRACT, MATCHING_CONTRACT)

    item = opportunity("opp-1")
    source_projection = projection(item)
    before = deepcopy(source_projection)

    partial = ADAPTER.build_registry(
        source_projection,
        [readback(item, ["status"])],
        REFERENCE_TIME,
        CONTRACT,
        MATCHING_CONTRACT,
    )
    assert partial["state"] == "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS"
    assert len(partial["receipts"]) == 1
    receipt = partial["receipts"][0]
    assert receipt["verification_state"] == "VERIFIED_OFFICIAL_SOURCE"
    assert set(receipt["verified_fact_hashes"]) == {"status"}
    assert receipt["verified_fact_hashes"]["status"] == MATCHER.canonical_hash(item["material_facts"]["status"])
    assert source_projection == before, "adapter mutated source projection"
    serialized = json.dumps(partial, ensure_ascii=False)
    assert "fact_values" not in serialized and "conflict_fact_classes" not in serialized

    profile = {
        "profile_id": "fixture-company",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["intreprindere", "agricola"],
        "activity_codes": ["CAEN 10"],
        "region_terms": [],
        "investment_terms": ["energie", "solara"],
        "requested_grant_eur": 500000,
    }
    downstream_partial = MATCHER.match(profile, source_projection, MATCHING_CONTRACT, partial)["results"][0]
    assert downstream_partial["authority_state"] == "WAITING_SOURCE"
    assert downstream_partial["state"] == "HOLD_SOURCE_STATE"

    required = ADAPTER.build_registry(
        source_projection,
        [readback(item, ["status", "deadline"])],
        REFERENCE_TIME,
        CONTRACT,
        MATCHING_CONTRACT,
    )
    downstream_required = MATCHER.match(profile, source_projection, MATCHING_CONTRACT, required)["results"][0]
    assert downstream_required["authority_state"] == "OFFICIAL_SOURCE_VERIFIED"
    assert set(downstream_required["official_fact_classes"]) == {"status", "deadline"}

    mismatched = ADAPTER.build_registry(
        source_projection,
        [readback(
            item,
            ["status", "deadline"],
            overrides={"deadline": {"closes_at": "2026-09-01T12:00:00+03:00"}},
        )],
        REFERENCE_TIME,
        CONTRACT,
        MATCHING_CONTRACT,
    )
    assert mismatched["receipts"][0]["verification_state"] == "BLOCKED_SOURCE_CONFLICT"
    assert mismatched["receipts"][0]["verified_fact_hashes"] == {}
    downstream_mismatch = MATCHER.match(profile, source_projection, MATCHING_CONTRACT, mismatched)["results"][0]
    assert downstream_mismatch["authority_state"] == "BLOCKED_SOURCE_CONFLICT"
    assert downstream_mismatch["state"] == "HOLD_SOURCE_STATE"

    explicit = ADAPTER.build_registry(
        source_projection,
        [readback(item, [], state="OFFICIAL_SOURCE_CONFLICT", conflicts=["deadline"])],
        REFERENCE_TIME,
        CONTRACT,
        MATCHING_CONTRACT,
    )
    assert explicit["receipts"][0]["verification_state"] == "BLOCKED_SOURCE_CONFLICT"

    must_fail(
        "PARTENER source product",
        lambda: ADAPTER.build_registry(
            source_projection,
            [readback(item, ["status"], source_product="PARTENER.EU")],
            REFERENCE_TIME,
            CONTRACT,
            MATCHING_CONTRACT,
        ),
    )
    must_fail(
        "PARTENER hostname",
        lambda: ADAPTER.build_registry(
            source_projection,
            [readback(item, ["status"], source_product="OTHER", source_url="https://sub.partener.eu/opportunity")],
            REFERENCE_TIME,
            CONTRACT,
            MATCHING_CONTRACT,
        ),
    )
    must_fail(
        "non-HTTPS source",
        lambda: ADAPTER.build_registry(
            source_projection,
            [readback(item, ["status"], source_url="http://mfe.gov.ro/program-test")],
            REFERENCE_TIME,
            CONTRACT,
            MATCHING_CONTRACT,
        ),
    )
    must_fail(
        "future verification",
        lambda: ADAPTER.build_registry(
            source_projection,
            [readback(item, ["status"], verified_at="2026-08-29T06:00:00Z")],
            REFERENCE_TIME,
            CONTRACT,
            MATCHING_CONTRACT,
        ),
    )

    unsupported = readback(item, ["status"])
    unsupported["fact_values"]["buying_intent"] = "HIGH"
    must_fail(
        "unsupported fact class",
        lambda: ADAPTER.build_registry(source_projection, [unsupported], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT),
    )

    person_level = readback(item, ["status"])
    person_level["fact_values"]["status"] = {"value": "OPEN", "personal_email": "person@example.test"}
    must_fail(
        "person-level official fact payload",
        lambda: ADAPTER.build_registry(source_projection, [person_level], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT),
    )

    unknown = readback(item, ["status"])
    unknown["opportunity_id"] = "missing-opportunity"
    must_fail(
        "unknown opportunity",
        lambda: ADAPTER.build_registry(source_projection, [unknown], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT),
    )

    duplicate = readback(item, ["status"])
    must_fail(
        "duplicate exact receipt",
        lambda: ADAPTER.build_registry(
            source_projection,
            [duplicate, deepcopy(duplicate)],
            REFERENCE_TIME,
            CONTRACT,
            MATCHING_CONTRACT,
        ),
    )

    second = opportunity("opp-2", deadline="2026-11-01T12:00:00+03:00")
    pair_projection = projection(item, second)
    rb1 = readback(item, ["status"], document_char="1")
    rb2 = readback(
        second,
        ["status"],
        document_char="2",
        source_authority="Agenția pentru Dezvoltare Regională",
        source_url="https://adr.example.test/program-test",
    )
    ordered_a = ADAPTER.build_registry(pair_projection, [rb2, rb1], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT)
    ordered_b = ADAPTER.build_registry(pair_projection, [rb1, rb2], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT)
    assert ordered_a == ordered_b, "registry must be deterministic regardless of input order"
    assert [row["opportunity_id"] for row in ordered_a["receipts"]] == ["opp-1", "opp-2"]

    bad_projection = deepcopy(source_projection)
    bad_projection["source_mutation_allowed"] = True
    must_fail(
        "projection mutation boundary",
        lambda: ADAPTER.build_registry(bad_projection, [rb1], REFERENCE_TIME, CONTRACT, MATCHING_CONTRACT),
    )

    bad_contract = deepcopy(CONTRACT)
    bad_contract["output_boundaries"]["network_fetch_enabled"] = True
    must_fail(
        "network fetch boundary",
        lambda: ADAPTER.build_registry(source_projection, [rb1], REFERENCE_TIME, bad_contract, MATCHING_CONTRACT),
    )

    must_fail(
        "repository runtime output",
        lambda: ADAPTER._assert_output_outside_repo(ROOT / "eucons" / "runtime" / "official-registry.json"),
    )

    print("PASS: official-source receipt adapter preserves discovery-only and fail-closed authority boundaries")


if __name__ == "__main__":
    main()
