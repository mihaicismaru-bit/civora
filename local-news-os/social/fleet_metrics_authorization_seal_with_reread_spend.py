#!/usr/bin/env python3
"""Fleet metrics authorization-seal CLI with explicit re-read spend enforcement.

This is the operational execution entry point for observed-metrics harvest. It keeps
``fleet_metrics_authorization_seal`` as the canonical capability/access/credential
boundary, installs the channel-local single-use re-read spend guard, crash-safe
reconciliation for a RESERVED spend left before NETWORK_CALL_STARTED, receipt-only
provenance binding from safe release to reclaim, atomic provider-outcome binding, and
read-back validation of the durable observed-metrics ledger/snapshot before a re-read
may become COMPLETED. Planning semantics and CLI arguments are unchanged.
"""
from __future__ import annotations

import reread_spend_reauthorization as reread_spend

reread_spend.install()

import reread_spend_reservation_recovery as reread_reservation_recovery

reread_reservation_recovery.install()

import reread_spend_reclaim_binding as reread_reclaim_binding

reread_reclaim_binding.install()

import reread_provider_outcome_binding as reread_provider_outcome_binding

reread_provider_outcome_binding.install()

import reread_result_materialization_binding as reread_result_materialization_binding

reread_result_materialization_binding.install()

import fleet_metrics_authorization_seal as base


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
