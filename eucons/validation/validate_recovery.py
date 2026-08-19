#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = EUCONS / "ops" / "recovery_contract.json"
PERSISTENCE_CONTRACT = EUCONS / "ops" / "persistence_contract.json"
ENGINE = EUCONS / "ops" / "recovery.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_recovery", ENGINE)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E24 recovery engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operation(engine, operation_id: str, domain: str, *, status: str = "PENDING", attempt: int = 0, max_attempts: int = 3, retryable: bool = True, expected_state_hash: str | None = None, lease=None, orphan_prepare: bool = False, **extra):
    row = {
        "operation_id": operation_id,
        "domain": domain,
        "status": status,
        "input_hash": engine.digest_json({"operation": operation_id, "domain": domain}),
        "expected_state_hash": expected_state_hash,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "retryable": retryable,
        "lease": lease,
        "orphan_prepare": orphan_prepare,
    }
    row.update(extra)
    return row


def expect_action(engine, row, expected: str, *, now: str, current_hash: str | None, receipt: bool = False) -> None:
    result = engine.decide_recovery(
        row,
        reference_time=now,
        current_state_hash=current_hash,
        delivery_receipt_exists=receipt,
    )
    if result["action"] != expected:
        raise SystemExit(f"{row['operation_id']}: expected {expected}, got {result['action']}")


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    persistence = json.loads(PERSISTENCE_CONTRACT.read_text(encoding="utf-8"))
    engine = load_engine()

    if contract["engine_id"] != "EUCONS_E24_RECOVERY":
        raise SystemExit("E24 engine id drift")
    if contract["depends_on"] != persistence["engine_id"]:
        raise SystemExit("E24 must depend on canonical E23 persistence")
    if contract["runtime_side_effects_enabled"] is not False:
        raise SystemExit("E24 recovery cannot activate runtime side effects")
    if set(contract["recovery_domains"]) != engine.ALLOWED_DOMAINS:
        raise SystemExit("E24 recovery-domain contract drift")
    if not all(contract["lease_policy"].values()):
        raise SystemExit("E24 lease policy incomplete")
    if not all(contract["duplicate_policy"].values()):
        raise SystemExit("E24 duplicate policy incomplete")
    if not all(contract["persistence_rules"].values()):
        raise SystemExit("E24 persistence rules incomplete")
    if not all(contract["forbidden"].values()):
        raise SystemExit("E24 forbidden-state guard incomplete")

    now = "2026-08-19T13:00:00Z"
    state_hash = engine.digest_json({"state": "canonical"})

    pending = operation(engine, "pub-1", "PUBLICATION", expected_state_hash=state_hash)
    expect_action(engine, pending, "START", now=now, current_hash=state_hash)

    stale = operation(
        engine,
        "li-1",
        "LINKEDIN",
        status="RUNNING",
        attempt=1,
        expected_state_hash=state_hash,
        lease={"owner": "runner-a", "acquired_at": "2026-08-19T11:00:00Z", "expires_at": "2026-08-19T12:00:00Z"},
    )
    expect_action(engine, stale, "RESUME_AFTER_STALE_LEASE", now=now, current_hash=state_hash)

    active = operation(
        engine,
        "fb-1",
        "FACEBOOK",
        status="RUNNING",
        attempt=1,
        expected_state_hash=state_hash,
        lease={"owner": "runner-b", "acquired_at": "2026-08-19T12:30:00Z", "expires_at": "2026-08-19T13:30:00Z"},
    )
    expect_action(engine, active, "NOOP_ACTIVE_LEASE", now=now, current_hash=state_hash)

    retry = operation(engine, "pub-2", "PUBLICATION", status="FAILED", attempt=1, expected_state_hash=state_hash)
    expect_action(engine, retry, "RETRY", now=now, current_hash=state_hash)

    exhausted = operation(engine, "pub-3", "PUBLICATION", status="FAILED", attempt=3, max_attempts=3, expected_state_hash=state_hash)
    expect_action(engine, exhausted, "HOLD_RETRY_EXHAUSTED", now=now, current_hash=state_hash)

    non_retryable = operation(engine, "pub-4", "PUBLICATION", status="FAILED", attempt=1, retryable=False, expected_state_hash=state_hash)
    expect_action(engine, non_retryable, "HOLD_NON_RETRYABLE", now=now, current_hash=state_hash)

    stale_opportunity = operation(engine, "opp-1", "OPPORTUNITY_RECONCILE", expected_state_hash=state_hash, object_state="STALE")
    expect_action(engine, stale_opportunity, "RECONCILE_TO_HOLD", now=now, current_hash=state_hash)

    offer = operation(engine, "offer-1", "OFFER_REPLAY", status="FAILED", attempt=1, expected_state_hash=state_hash, offer_version=2)
    expect_action(engine, offer, "NOOP_ALREADY_DELIVERED", now=now, current_hash=state_hash, receipt=True)

    succeeded_without_receipt = operation(engine, "li-2", "LINKEDIN", status="SUCCEEDED", attempt=1, expected_state_hash=state_hash)
    expect_action(engine, succeeded_without_receipt, "HOLD_MISSING_RECEIPT", now=now, current_hash=state_hash)

    orphan = operation(engine, "pub-5", "PUBLICATION", expected_state_hash=state_hash, orphan_prepare=True)
    expect_action(engine, orphan, "DISCARD_ORPHAN_PREPARE", now=now, current_hash=state_hash)
    expect_action(engine, pending, "HOLD_CORRUPT_STATE", now=now, current_hash=engine.digest_json({"state": "changed"}))

    same_a = operation(engine, "dup-ok", "PUBLICATION", status="FAILED", attempt=1, expected_state_hash=state_hash)
    same_b = dict(same_a)
    same_b["attempt"] = 2
    plan_a = engine.build_recovery_plan(
        [same_a, same_b, stale_opportunity],
        reference_time=now,
        current_state_hashes={"dup-ok": state_hash, "opp-1": state_hash},
    )
    plan_b = engine.build_recovery_plan(
        [stale_opportunity, same_b, same_a],
        reference_time=now,
        current_state_hashes={"opp-1": state_hash, "dup-ok": state_hash},
    )
    if plan_a != plan_b or plan_a["plan_hash"] != engine.digest_json({k: v for k, v in plan_a.items() if k != "plan_hash"}):
        raise SystemExit("E24 deterministic resume plan drift")
    duplicate_decision = next(row for row in plan_a["decisions"] if row["operation_id"] == "dup-ok")
    if duplicate_decision["duplicate_count"] != 2:
        raise SystemExit("E24 same-idempotency-key duplicate was not collapsed")

    conflict = dict(same_a)
    conflict["input_hash"] = engine.digest_json({"different": True})
    conflict_plan = engine.build_recovery_plan(
        [same_a, conflict],
        reference_time=now,
        current_state_hashes={"dup-ok": state_hash},
    )
    if conflict_plan["decisions"][0]["action"] != "HOLD_DUPLICATE_CONFLICT":
        raise SystemExit("E24 conflicting duplicate did not fail closed")

    v1 = engine.digest_json({"version": 1})
    v2 = engine.digest_json({"version": 2})
    rollback = engine.rollback_plan(
        [
            {"version": 1, "preimage_hash": None, "postimage_hash": v1, "committed": True},
            {"version": 2, "preimage_hash": v1, "postimage_hash": v2, "committed": True},
        ],
        current_state_hash=v2,
    )
    if rollback["target_state_hash"] != v1 or rollback["to_version"] != 1:
        raise SystemExit("E24 rollback lineage target drift")

    print("EUCONS E24 Recovery: PASS (stale lease, retry, dedupe, opportunity HOLD, offer replay, rollback and deterministic resume verified)")


if __name__ == "__main__":
    main()
