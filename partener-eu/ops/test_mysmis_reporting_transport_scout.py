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
        fake("OFFICIAL_RESOURCES", True),
        fake("OFFICIAL_DWH_LEGACY", True),
    )
    assert aligned["state"] == "PRIMARY_PLUS_ALIGNED_ALTERNATES"
    assert aligned["alignedWithCanonical"] == ["OFFICIAL_RESOURCES", "OFFICIAL_DWH_LEGACY"]
    assert aligned["alternatePairSemanticallyAligned"] is True
    assert aligned["alternateAuthorizedForMaterialFacts"] is False
    assert aligned["publishAuthorized"] is False

    divergent = mod.classify(
        fake("CANONICAL_PRIMARY", True, "a" * 64, 927),
        fake("OFFICIAL_RESOURCES", True, "b" * 64, 921),
        fake("OFFICIAL_DWH_LEGACY", True, "b" * 64, 921),
    )
    assert divergent["state"] == "PRIMARY_PLUS_DIVERGENT_ALTERNATES"
    assert divergent["alignedWithCanonical"] == []
    assert divergent["divergentFromCanonical"] == [
        "OFFICIAL_RESOURCES",
        "OFFICIAL_DWH_LEGACY",
    ]
    assert divergent["alternatePairSemanticallyAligned"] is True
    assert divergent["requiresSemanticReconciliation"] is True
    assert divergent["alternateAuthorizedForMaterialFacts"] is False

    mixed = mod.classify(
        fake("CANONICAL_PRIMARY", True, "a" * 64, 927),
        fake("OFFICIAL_RESOURCES", True, "a" * 64, 927),
        fake("OFFICIAL_DWH_LEGACY", True, "b" * 64, 921),
    )
    assert mixed["state"] == "PRIMARY_PLUS_MIXED_ALTERNATES"
    assert mixed["alignedWithCanonical"] == ["OFFICIAL_RESOURCES"]
    assert mixed["divergentFromCanonical"] == ["OFFICIAL_DWH_LEGACY"]

    alternates_only = mod.classify(
        fake("CANONICAL_PRIMARY", False),
        fake("OFFICIAL_RESOURCES", True, "b" * 64, 921),
        fake("OFFICIAL_DWH_LEGACY", True, "b" * 64, 921),
    )
    assert alternates_only["state"] == "ALTERNATES_ONLY_DISCOVERY"
    assert alternates_only["alternateEligibleForDiscoveryOnly"] is True
    assert alternates_only["alternateAuthorizedForMaterialFacts"] is False

    none = mod.classify(
        fake("CANONICAL_PRIMARY", False),
        fake("OFFICIAL_RESOURCES", False),
        fake("OFFICIAL_DWH_LEGACY", False),
    )
    assert none["state"] == "NO_OFFICIAL_REPORT_TRANSPORT_AVAILABLE"
    assert none["openCallAuthorized"] is False

    assert mod.official_final_url(mod.CANONICAL_URL, "reporting.mysmis2021.gov.ro")
    assert mod.official_final_url(mod.RESOURCES_URL, "resurse.mysmis2021.gov.ro")
    assert mod.official_final_url(mod.DWH_URL, "dwh4smis.fonduri-ue.ro")
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
                **fake("OFFICIAL_RESOURCES", False),
                "requestedUrl": mod.RESOURCES_URL,
                "materialFactUse": False,
                "openCallAuthorized": False,
                "publishAuthorized": False,
                "deadlineAuthorized": False,
                "budgetAuthorized": False,
                "eligibilityAuthorized": False,
            },
            {
                **fake("OFFICIAL_DWH_LEGACY", False),
                "requestedUrl": mod.DWH_URL,
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
