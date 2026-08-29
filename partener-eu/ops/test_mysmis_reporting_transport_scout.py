#!/usr/bin/env python3
"""Deterministic fail-closed regression for MySMIS reporting transport scout."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
MODULE_PATH = HERE.parents[1] / "ingest" / "mysmis_reporting_transport_scout.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("mysmis_reporting_transport_scout", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def fake(role: str, ok: bool, sem: str = "a" * 64, count: int = 927):
    return {
        "role": role,
        "ok": ok,
        "semanticSha256": sem if ok else None,
        "validatedCallCount": count if ok else None,
    }


def main() -> int:
    aligned = mod.classify(
        fake("CANONICAL_PRIMARY", True),
        fake("OFFICIAL_ALTERNATE", True),
    )
    assert aligned["state"] == "BOTH_AVAILABLE_SEMANTICALLY_ALIGNED"
    assert aligned["semanticMatch"] is True
    assert aligned["alternateAuthorizedForMaterialFacts"] is False
    assert aligned["publishAuthorized"] is False

    divergent = mod.classify(
        fake("CANONICAL_PRIMARY", True, "a" * 64, 927),
        fake("OFFICIAL_ALTERNATE", True, "b" * 64, 921),
    )
    assert divergent["state"] == "BOTH_AVAILABLE_SEMANTICALLY_DIVERGENT"
    assert divergent["semanticMatch"] is False
    assert divergent["requiresSemanticReconciliation"] is True
    assert divergent["alternateAuthorizedForMaterialFacts"] is False

    alternate_only = mod.classify(
        fake("CANONICAL_PRIMARY", False),
        fake("OFFICIAL_ALTERNATE", True),
    )
    assert alternate_only["state"] == "OFFICIAL_ALTERNATE_ONLY"
    assert alternate_only["alternateEligibleForDiscoveryOnly"] is True
    assert alternate_only["alternateAuthorizedForMaterialFacts"] is False

    none = mod.classify(
        fake("CANONICAL_PRIMARY", False),
        fake("OFFICIAL_ALTERNATE", False),
    )
    assert none["state"] == "NO_OFFICIAL_REPORT_TRANSPORT_AVAILABLE"
    assert none["openCallAuthorized"] is False

    assert mod.official_final_url(mod.CANONICAL_URL, "reporting.mysmis2021.gov.ro")
    assert not mod.official_final_url(
        "http://reporting.mysmis2021.gov.ro" + mod.EXPECTED_PATH,
        "reporting.mysmis2021.gov.ro",
    )
    assert not mod.official_final_url(
        "https://example.com" + mod.EXPECTED_PATH,
        "reporting.mysmis2021.gov.ro",
    )

    payload = mod.build_payload(
        [
            {
                **fake("CANONICAL_PRIMARY", False),
                "requestedUrl": mod.CANONICAL_URL,
                "materialFactUse": False,
                "openCallAuthorized": False,
                "publishAuthorized": False,
                "deadlineAuthorized": False,
                "budgetAuthorized": False,
                "eligibilityAuthorized": False,
            },
            {
                **fake("OFFICIAL_ALTERNATE", False),
                "requestedUrl": mod.OFFICIAL_ALTERNATE_URL,
                "materialFactUse": False,
                "openCallAuthorized": False,
                "publishAuthorized": False,
                "deadlineAuthorized": False,
                "budgetAuthorized": False,
                "eligibilityAuthorized": False,
            },
        ]
    )
    mod.validate_payload(payload)
    assert payload["canonicalIdentity"] == mod.CANONICAL_URL
    assert payload["materialFactUse"] is False
    print("MySMIS reporting transport scout fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
