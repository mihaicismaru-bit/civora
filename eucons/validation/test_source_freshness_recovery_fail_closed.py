#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "opportunities" / "source_freshness_recovery.py"
CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "source_freshness_recovery_contract.json"
BRIDGE_CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "bridge_contract.json"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_source_freshness_recovery", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source freshness recovery engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


def projection(state: str, bridge_state: str, age_seconds=None) -> dict:
    return {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "generated_at": "2026-08-29T08:00:00Z",
        "bridge_state": bridge_state,
        "read_only": True,
        "source_mutation_allowed": False,
        "source": {
            "product": "PARTENER.EU",
            "path": "partener-eu/web/p11-public-data.js",
            "as_of": "2026-08-25T08:00:00Z",
            "sha256": "a" * 64,
            "policy_accepted": True,
        },
        "freshness": {
            "state": state,
            "age_seconds": age_seconds,
            "max_age_seconds": 72 * 3600,
        },
        "summary": {
            "source_opportunity_count": 3,
            "admitted_verified_count": 2,
            "actionable_open_count": 0,
            "held_stale_count": 2 if bridge_state == "STALE_SOURCE_HOLD" else 0,
        },
        "opportunities": [
            {
                "id": "secret-opportunity",
                "title": "Must never leak",
                "material_facts": {"budget": 999999},
            }
        ],
    }


def main() -> None:
    engine = load_engine()
    contract = engine.load_json(CONTRACT_PATH)
    bridge_contract = engine.load_json(BRIDGE_CONTRACT_PATH)
    engine.validate_contract(contract, bridge_contract)

    fresh = engine.build_recovery_queue(projection("FRESH", "READY", 60), contract, bridge_contract)
    assert fresh["summary"]["source_held"] is False
    assert fresh["tasks"] == []
    assert fresh["source_role"] == "DISCOVERY_ONLY"

    stale_input = projection("STALE", "STALE_SOURCE_HOLD", 96 * 3600)
    stale = engine.build_recovery_queue(stale_input, contract, bridge_contract)
    stale_again = engine.build_recovery_queue(copy.deepcopy(stale_input), contract, bridge_contract)
    assert stale == stale_again
    assert stale["summary"]["source_held"] is True
    assert len(stale["tasks"]) == 1
    task = stale["tasks"][0]
    assert task["priority"] == "P1"
    assert task["reason_code"] == "DISCOVERY_SOURCE_STALE"
    assert task["operator_action"] == "REQUEST_DISCOVERY_REFRESH_REVIEW"
    assert task["age_hours"] == 96.0
    assert task["official_authority_inferred"] is False
    assert task["external_action_authorized"] is False

    invalid = engine.build_recovery_queue(projection("INVALID_TIME", "STALE_SOURCE_HOLD", None), contract, bridge_contract)
    assert invalid["tasks"][0]["priority"] == "P0"
    assert invalid["tasks"][0]["reason_code"] == "DISCOVERY_TIMESTAMP_INTEGRITY_HOLD"
    assert invalid["tasks"][0]["age_hours"] is None

    future = engine.build_recovery_queue(projection("FUTURE_TIME", "STALE_SOURCE_HOLD", -3600), contract, bridge_contract)
    assert future["tasks"][0]["priority"] == "P0"
    assert future["tasks"][0]["age_hours"] == 0.0

    serialized = str(stale)
    assert "secret-opportunity" not in serialized
    assert "Must never leak" not in serialized
    assert "999999" not in serialized

    bad = projection("STALE", "READY", 96 * 3600)
    must_fail("stale bridge mismatch", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("FRESH", "STALE_SOURCE_HOLD", 60)
    must_fail("fresh bridge mismatch", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("STALE", "STALE_SOURCE_HOLD", -1)
    must_fail("negative stale age", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("STALE", "STALE_SOURCE_HOLD", 96 * 3600)
    bad["freshness"]["max_age_seconds"] = 1
    must_fail("max age drift", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("STALE", "STALE_SOURCE_HOLD", 96 * 3600)
    bad["source"]["sha256"] = "not-a-hash"
    must_fail("source hash drift", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("STALE", "STALE_SOURCE_HOLD", 96 * 3600)
    bad["source"]["product"] = "PARTENER.EU-OFFICIAL"
    must_fail("PARTENER authority promotion", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    bad = projection("STALE", "STALE_SOURCE_HOLD", 96 * 3600)
    bad["source"]["policy_accepted"] = False
    must_fail("policy rejection misclassified as freshness", lambda: engine.build_recovery_queue(bad, contract, bridge_contract))

    drift = copy.deepcopy(contract)
    drift["input"]["required_source_role"] = "OFFICIAL_AUTHORITY"
    must_fail("source role drift", lambda: engine.validate_contract(drift, bridge_contract))

    drift = copy.deepcopy(contract)
    drift["boundaries"]["network_fetch"] = True
    must_fail("network boundary", lambda: engine.validate_contract(drift, bridge_contract))

    drift = copy.deepcopy(contract)
    drift["output"]["external_action_authorized"] = True
    must_fail("external action boundary", lambda: engine.validate_contract(drift, bridge_contract))

    print("PASS: source freshness recovery stays read-only, discovery-only and fail-closed")


if __name__ == "__main__":
    main()
