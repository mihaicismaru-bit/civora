#!/usr/bin/env python3
"""Fleet metrics authorization-seal CLI with explicit re-read spend enforcement.

This is the operational execution entry point for observed-metrics harvest. It keeps
``fleet_metrics_authorization_seal`` as the canonical capability/access/credential
boundary, installs the channel-local single-use re-read spend guard, crash-safe
reconciliation for a RESERVED spend left before NETWORK_CALL_STARTED, and the
receipt-only provenance binding from a safely released reservation to the eventual
reclaim attempt. Planning semantics and command-line arguments remain unchanged.
"""
from __future__ import annotations

import reread_spend_reauthorization as reread_spend

reread_spend.install()

import reread_spend_reservation_recovery as reread_reservation_recovery

reread_reservation_recovery.install()

import reread_spend_reclaim_binding as reread_reclaim_binding

reread_reclaim_binding.install()

import fleet_metrics_authorization_seal as base


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
