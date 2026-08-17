#!/usr/bin/env python3
"""Canonical, provider-neutral persistence health signal for CIVORA / LOCAL NEWS OS.

PRS-041 separates persistence health from product/runtime health.  The signal is
pure and deterministic: it grants no publication, deployment or external-LIVE
authority and contains no instance identity or provider-specific behavior.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

SCHEMA_VERSION = "1.0"
CONTRACT = "CIVORA_PERSISTENCE_HEALTH_SIGNAL_V1"

PERSISTENCE_FRESH = "PERSISTENCE_FRESH"
PERSISTENCE_STALE = "PERSISTENCE_STALE"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
PERSISTENCE_BLOCKED = "PERSISTENCE_BLOCKED"

ALLOWED_STATUSES = frozenset(
    {
        PERSISTENCE_FRESH,
        PERSISTENCE_STALE,
        RECONCILIATION_REQUIRED,
        PERSISTENCE_BLOCKED,
    }
)


@dataclass(frozen=True)
class PersistenceHealthEvidence:
    """Minimal evidence needed to derive one canonical persistence health state."""

    transport_blocked: bool = False
    reconciliation_required: bool = False
    synchronized: bool = False
    stale: bool = False


@dataclass(frozen=True)
class PersistenceHealthSignal:
    schema_version: str
    contract: str
    status: str
    reason: str
    product_runtime_may_continue: bool
    grants_external_live_authority: bool

    def to_dict(self) -> dict:
        return asdict(self)


def validate_status(status: str) -> str:
    value = str(status or "").strip()
    if value not in ALLOWED_STATUSES:
        raise ValueError(f"invalid persistence health status: {value!r}")
    return value


def derive_health(evidence: PersistenceHealthEvidence) -> PersistenceHealthSignal:
    """Derive the canonical state with fail-closed precedence.

    Precedence is BLOCKED > RECONCILIATION_REQUIRED > STALE > FRESH.  FRESH is
    possible only when synchronization has been proven and no stale condition is
    present.  Product runtime may continue in every state; persistence health is
    deliberately not a product-runtime kill switch.
    """
    if evidence.transport_blocked:
        status = PERSISTENCE_BLOCKED
        reason = "PERSISTENCE_TRANSPORT_OR_OWNERSHIP_BLOCKED"
    elif evidence.reconciliation_required:
        status = RECONCILIATION_REQUIRED
        reason = "AUTHORITATIVE_STATE_RECONCILIATION_REQUIRED"
    elif evidence.stale or not evidence.synchronized:
        status = PERSISTENCE_STALE
        reason = "LATEST_STATE_NOT_READBACK_SYNCHRONIZED"
    else:
        status = PERSISTENCE_FRESH
        reason = "LATEST_STATE_SYNCHRONIZED_AND_READBACK_VERIFIED"

    return PersistenceHealthSignal(
        schema_version=SCHEMA_VERSION,
        contract=CONTRACT,
        status=validate_status(status),
        reason=reason,
        product_runtime_may_continue=True,
        grants_external_live_authority=False,
    )


def self_test() -> int:
    fresh = derive_health(PersistenceHealthEvidence(synchronized=True))
    assert fresh.status == PERSISTENCE_FRESH

    stale_missing_sync = derive_health(PersistenceHealthEvidence())
    assert stale_missing_sync.status == PERSISTENCE_STALE

    stale_explicit = derive_health(PersistenceHealthEvidence(synchronized=True, stale=True))
    assert stale_explicit.status == PERSISTENCE_STALE

    reconcile = derive_health(
        PersistenceHealthEvidence(reconciliation_required=True, synchronized=True, stale=True)
    )
    assert reconcile.status == RECONCILIATION_REQUIRED

    blocked = derive_health(
        PersistenceHealthEvidence(
            transport_blocked=True,
            reconciliation_required=True,
            synchronized=True,
            stale=True,
        )
    )
    assert blocked.status == PERSISTENCE_BLOCKED

    for signal in (fresh, stale_missing_sync, stale_explicit, reconcile, blocked):
        assert signal.status in ALLOWED_STATUSES
        assert signal.product_runtime_may_continue is True
        assert signal.grants_external_live_authority is False

    try:
        validate_status("READY")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown persistence status must fail closed")

    print(json.dumps({
        "status": "PASS",
        "contract": CONTRACT,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("This module is a library contract. Use --self-test or call derive_health.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
