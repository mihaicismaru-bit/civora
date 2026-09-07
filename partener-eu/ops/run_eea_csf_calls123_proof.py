#!/usr/bin/env python3
"""Temporary bounded proof runner for EEA CSF Romania Calls #1-#3.

This proof reuses the canonical shared runner primitives. It exists only to seed
same-identity history before the three identities move into Official Programme.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import sys

from run_eea_csf_exact_canonical import (
    CallConfig,
    acquire_current,
    enforce_boundary,
    reconcile_current,
    restore_previous,
    stage_history,
)

ROOT = pathlib.Path("/tmp/partener-eu-eea-csf-calls123-proof")
LEGACY_PREFIX = "partener-eu-eea-csf-calls123-exact-"


def cfg(call_id: str) -> CallConfig:
    return CallConfig(
        call_id=call_id,
        exact_module=f"eea_civil_society_fund_call{call_id}_exact",
        reconcile_module=f"eea_civil_society_fund_call{call_id}_reconcile",
        evidence_filename=f"eea-csf-ro-call{call_id}-exact-evidence.json",
        reconciliation_filename=f"eea-csf-ro-call{call_id}-reconciliation.json",
        legacy_artifact_prefixes=(LEGACY_PREFIX,),
    )


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    if str(ingest) not in sys.path:
        sys.path.insert(0, str(ingest))
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    results = {}
    for call_id in ("1", "2", "3"):
        call_cfg = cfg(call_id)
        exact_module = importlib.import_module(call_cfg.exact_module)
        reconcile_module = importlib.import_module(call_cfg.reconcile_module)
        call_root = ROOT / f"call{call_id}"
        (call_root / "current").mkdir(parents=True)
        (call_root / "previous").mkdir(parents=True)
        (call_root / "history").mkdir(parents=True)
        current = acquire_current(call_cfg, root=call_root, repo_root=repo_root, exact_module=exact_module)
        restore = restore_previous(
            call_cfg,
            root=call_root,
            current=current,
            exact_module=exact_module,
            allow_legacy_history=True,
        )
        reconcile_current(call_cfg, root=call_root, repo_root=repo_root, restore=restore)
        boundary = enforce_boundary(
            call_cfg,
            root=call_root,
            exact_module=exact_module,
            reconcile_module=reconcile_module,
        )
        history = stage_history(call_cfg, root=call_root)
        results[call_id] = {"restore": restore, "boundary": boundary, "history": history}
    (ROOT / "proof-summary.json").write_text(
        json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
