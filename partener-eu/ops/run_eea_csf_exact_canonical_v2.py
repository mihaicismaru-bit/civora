#!/usr/bin/env python3
"""Canonical CSF runner registration for Calls #1-#7.

This module extends the proven shared exact-call runner with the common-parser
Calls #1-#3 identities. It deliberately reuses the existing acquisition,
restore, reconciliation, boundary and history implementation; no material
authority is widened here.
"""
from __future__ import annotations

import run_eea_csf_exact_canonical as base

LEGACY_CALLS123_PREFIX = "partener-eu-eea-csf-calls123-exact-"

for _call_id in ("1", "2", "3"):
    base.CONFIGS[_call_id] = base.CallConfig(
        call_id=_call_id,
        exact_module=f"eea_civil_society_fund_call{_call_id}_exact",
        reconcile_module=f"eea_civil_society_fund_call{_call_id}_reconcile",
        evidence_filename=f"eea-csf-ro-call{_call_id}-exact-evidence.json",
        reconciliation_filename=f"eea-csf-ro-call{_call_id}-reconciliation.json",
        legacy_artifact_prefixes=(LEGACY_CALLS123_PREFIX,),
    )

CONFIGS = base.CONFIGS
CallConfig = base.CallConfig
acquire_current = base.acquire_current
restore_previous = base.restore_previous
reconcile_current = base.reconcile_current
enforce_boundary = base.enforce_boundary
stage_history = base.stage_history
healthy = base.healthy


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
