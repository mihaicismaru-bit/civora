#!/usr/bin/env python3
"""Fleet metrics authorization-seal CLI with explicit re-read spend enforcement.

This is the operational execution entry point for observed-metrics harvest. It keeps
``fleet_metrics_authorization_seal`` as the canonical capability/access/credential
boundary and installs the channel-local re-read spend guard before delegating to the
existing CLI. Planning semantics and command-line arguments remain unchanged.
"""
from __future__ import annotations

import reread_spend_reauthorization as reread_spend

reread_spend.install()

import fleet_metrics_authorization_seal as base


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
