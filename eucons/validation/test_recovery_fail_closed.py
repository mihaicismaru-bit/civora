#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "eucons" / "ops" / "recovery.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_recovery", ENGINE)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E24 recovery engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_value_error(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise SystemExit(f"{label}: expected fail-closed ValueError")


def base(engine, operation_id: str = "op-1"):
    return {
        "operation_id": operation_id,
        "domain": "PUBLICATION",
        "status": "PENDING",
        "input_hash": engine.digest_json({"input": operation_id}),
        "expected_state_hash": engine.digest_json({"state": operation_id}),
        "attempt": 0,
        "max_attempts": 2,
        "retryable": True,
        "lease": None,
        "orphan_prepare": False,
    }


def main() -> None:
    engine = load_engine()
    now = "2026-08-19T13:00:00Z"

    missing_lease = base(engine, "missing-lease")
    missing_lease["status"] = "RUNNING"
    expect_value_error("running without lease", lambda: engine.validate_operation(missing_lease))

    bad_lease = base(engine, "bad-lease")
    bad_lease["status"] = "RUNNING"
    bad_lease["lease"] = {
        "owner": "runner",
        "acquired_at": "2026-08-19T13:00:00Z",
        "expires_at": "2026-08-19T12:59:00Z",
    }
    expect_value_error("backwards lease", lambda: engine.validate_operation(bad_lease))

    invalid_hash = base(engine, "invalid-hash")
    invalid_hash["input_hash"] = "not-a-hash"
    expect_value_error("invalid input hash", lambda: engine.validate_operation(invalid_hash))

    invalid_attempt = base(engine, "invalid-attempt")
    invalid_attempt["attempt"] = 3
    invalid_attempt["max_attempts"] = 2
    expect_value_error("attempt over budget", lambda: engine.validate_operation(invalid_attempt))

    stale = base(engine, "stale-hash")
    decision = engine.decide_recovery(
        stale,
        reference_time=now,
        current_state_hash=engine.digest_json({"different": True}),
        delivery_receipt_exists=False,
    )
    if decision["action"] != "HOLD_CORRUPT_STATE":
        raise SystemExit("state-hash drift did not fail closed")

    orphan = base(engine, "orphan")
    orphan["orphan_prepare"] = True
    orphan_decision = engine.decide_recovery(
        orphan,
        reference_time=now,
        current_state_hash=orphan["expected_state_hash"],
        delivery_receipt_exists=False,
    )
    if orphan_decision["action"] != "DISCARD_ORPHAN_PREPARE":
        raise SystemExit("orphan prepared state was not discarded")

    delivered = base(engine, "delivered")
    delivered["status"] = "FAILED"
    delivered["attempt"] = 1
    delivered_decision = engine.decide_recovery(
        delivered,
        reference_time=now,
        current_state_hash=delivered["expected_state_hash"],
        delivery_receipt_exists=True,
    )
    if delivered_decision["action"] != "NOOP_ALREADY_DELIVERED":
        raise SystemExit("existing delivery receipt did not suppress duplicate side effect")

    conflict_a = base(engine, "conflict")
    conflict_b = dict(conflict_a)
    conflict_b["input_hash"] = engine.digest_json({"changed": True})
    plan = engine.build_recovery_plan(
        [conflict_a, conflict_b],
        reference_time=now,
        current_state_hashes={"conflict": conflict_a["expected_state_hash"]},
    )
    if plan["decisions"][0]["action"] != "HOLD_DUPLICATE_CONFLICT":
        raise SystemExit("conflicting duplicate execution was not blocked")

    exhausted = base(engine, "exhausted")
    exhausted["status"] = "FAILED"
    exhausted["attempt"] = 2
    exhausted_decision = engine.decide_recovery(
        exhausted,
        reference_time=now,
        current_state_hash=exhausted["expected_state_hash"],
        delivery_receipt_exists=False,
    )
    if exhausted_decision["action"] != "HOLD_RETRY_EXHAUSTED":
        raise SystemExit("retry exhaustion was bypassed")

    offer = base(engine, "offer")
    offer["domain"] = "OFFER_REPLAY"
    offer["offer_version"] = 1
    offer["input_hash"] = engine.digest_json({"offer": "same"})
    offer_decision = engine.decide_recovery(
        offer,
        reference_time=now,
        current_state_hash=offer["expected_state_hash"],
        delivery_receipt_exists=True,
    )
    if offer_decision["action"] != "NOOP_ALREADY_DELIVERED":
        raise SystemExit("offer replay ignored existing delivery receipt")

    opp = base(engine, "opp")
    opp["domain"] = "OPPORTUNITY_RECONCILE"
    opp["object_state"] = "WITHDRAWN"
    opp_decision = engine.decide_recovery(
        opp,
        reference_time=now,
        current_state_hash=opp["expected_state_hash"],
        delivery_receipt_exists=False,
    )
    if opp_decision["action"] != "RECONCILE_TO_HOLD":
        raise SystemExit("withdrawn opportunity did not project to HOLD")

    v1 = engine.digest_json({"v": 1})
    v2 = engine.digest_json({"v": 2})
    expect_value_error(
        "rollback disconnected lineage",
        lambda: engine.rollback_plan(
            [
                {"version": 1, "preimage_hash": None, "postimage_hash": v1, "committed": True},
                {"version": 2, "preimage_hash": engine.digest_json({"wrong": True}), "postimage_hash": v2, "committed": True},
            ],
            current_state_hash=v2,
        ),
    )
    expect_value_error("rollback missing lineage", lambda: engine.rollback_plan([], current_state_hash=v2))

    print("EUCONS E24 Recovery fail-closed: PASS")


if __name__ == "__main__":
    main()
