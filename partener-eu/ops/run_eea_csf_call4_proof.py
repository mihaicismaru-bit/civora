#!/usr/bin/env python3
"""Temporary bounded proof wiring for EEA CSF Call #4 through the shared exact runner.

Retire this wrapper when Call #4 is added to the canonical CONFIGS and Official
Programme workflow. It adds no acquisition, reconciliation or authority logic.
"""
from __future__ import annotations

import sys

import run_eea_csf_exact_canonical as shared


shared.CONFIGS["4"] = shared.CallConfig(
    call_id="4",
    exact_module="eea_civil_society_fund_call4_exact",
    reconcile_module="eea_civil_society_fund_call4_reconcile",
    evidence_filename="eea-csf-ro-call4-exact-evidence.json",
    reconciliation_filename="eea-csf-ro-call4-reconciliation.json",
    legacy_artifact_prefixes=("partener-eu-eea-csf-call4-exact-",),
)


if __name__ == "__main__":
    sys.argv = [
        sys.argv[0],
        "--call-id", "4",
        "--root", "/tmp/partener-eu-eea-csf-call4-exact",
        "--allow-legacy-history",
    ]
    raise SystemExit(shared.main())
