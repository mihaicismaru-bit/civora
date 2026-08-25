#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ADAPTER_PATH = EUCONS / "prospects" / "source_adapter.py"
CONTRACT_PATH = EUCONS / "prospects" / "source_adapter_contract.json"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "source_adapter_snapshot_non_evidence.json"

spec = importlib.util.spec_from_file_location("client_finder_source_adapter", ADAPTER_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load Client Finder source adapter")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    missing = deepcopy(fixture)
    missing.pop("robots_checked_at")
    must_fail("missing governance metadata", lambda: adapter.adapt_snapshot(missing))

    tampered = deepcopy(fixture)
    tampered["records"][0]["statement"] = "Tampered after hashing."
    must_fail("content hash mismatch", lambda: adapter.adapt_snapshot(tampered))

    stale = deepcopy(fixture)
    stale["retrieved_at"] = "2026-08-20T02:10:00+03:00"
    must_fail("stale snapshot", lambda: adapter.adapt_snapshot(stale))

    unsafe_origin = deepcopy(fixture)
    unsafe_origin["source"]["url"] = "https://unreviewed.example/snapshot"
    must_fail("unallowlisted origin", lambda: adapter.adapt_snapshot(unsafe_origin))

    insecure_origin = deepcopy(fixture)
    insecure_origin["source"]["url"] = "http://example.invalid/snapshot"
    must_fail("non-HTTPS origin", lambda: adapter.adapt_snapshot(insecure_origin))

    real_disabled = deepcopy(fixture)
    real_disabled["adapter_id"] = "AFIR_OFFICIAL_SNAPSHOT"
    real_disabled["source"]["url"] = "https://www.afir.ro/"
    must_fail("real adapter activation", lambda: adapter.adapt_snapshot(real_disabled))

    private = deepcopy(fixture)
    private["records"][0]["organization"]["email"] = "person@example.invalid"
    private["content_hash"] = adapter.canonical_hash(private["records"])
    must_fail("personal contact", lambda: adapter.adapt_snapshot(private))

    wrong_mapping = deepcopy(fixture)
    wrong_mapping["records"][0]["service_ids"] = ["funding_strategy_and_eligibility"]
    wrong_mapping["content_hash"] = adapter.canonical_hash(wrong_mapping["records"])
    must_fail("signal mapping drift", lambda: adapter.adapt_snapshot(wrong_mapping))

    no_public_access = deepcopy(fixture)
    no_public_access["public_access"] = False
    must_fail("non-public snapshot", lambda: adapter.adapt_snapshot(no_public_access))

    bad_rate = deepcopy(fixture)
    bad_rate["rate_limit_policy"] = "UNLIMITED"
    must_fail("unsafe rate policy", lambda: adapter.adapt_snapshot(bad_rate))

    unsafe_contract = deepcopy(contract)
    unsafe_contract["runtime_boundary"]["network_fetch_enabled"] = True
    must_fail("network boundary", lambda: adapter.adapt_snapshot(fixture, unsafe_contract))

    duplicate_profile = deepcopy(contract)
    duplicate_profile["profiles"].append(deepcopy(duplicate_profile["profiles"][0]))
    must_fail("duplicate adapter profile", lambda: adapter.adapt_snapshot(fixture, duplicate_profile))

    discovery_claim = deepcopy(fixture)
    discovery_claim["source"]["source_type"] = "ORGANIZATION_OFFICIAL_ANNOUNCEMENT"
    discovery_claim["records"][0]["material_funding_claim"] = True
    discovery_claim["content_hash"] = adapter.canonical_hash(discovery_claim["records"])
    permissive = deepcopy(contract)
    permissive["profiles"][0]["allowed_source_types"].append("ORGANIZATION_OFFICIAL_ANNOUNCEMENT")
    must_fail("material claim without official source class", lambda: adapter.adapt_snapshot(discovery_claim, permissive))

    print("PASS: source adapter rejects stale/tampered/private/unreviewed snapshots, unsafe activation and invalid signal mappings")


if __name__ == "__main__":
    main()
