#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ADAPTER_PATH = EUCONS / "prospects" / "source_adapter.py"
CONTRACT_PATH = EUCONS / "prospects" / "source_adapter_contract.json"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "source_adapter_snapshot_non_evidence.json"


def load_adapter():
    spec = importlib.util.spec_from_file_location("client_finder_source_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load Client Finder source adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    adapter = load_adapter()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    profiles = adapter.validate_adapter_contract(contract)
    if len(profiles) != 4:
        raise SystemExit("source adapter profile count drift")
    if sum(row["activation_state"] == "DRY_RUN_ONLY" for row in profiles.values()) != 1:
        raise SystemExit("dry-run activation boundary drift")

    adapted, state = adapter.run_dry_run(fixture)
    if len(adapted["observations"]) != 2 or len(state["records"]) != 2:
        raise SystemExit("source adapter dry-run cardinality drift")
    if any(row["state"] != "READY_FOR_SCORING" for row in state["records"].values()):
        raise SystemExit("adapted organization did not reach READY_FOR_SCORING")
    if any(row.get("synthetic_label") != "NON_EVIDENCE" for row in state["records"].values()):
        raise SystemExit("NON_EVIDENCE label lost")
    if any(source.get("official") is not True or source.get("public_access") is not True for row in state["records"].values() for source in row["sources"]):
        raise SystemExit("source provenance boundary drift")
    if adapted["network_fetch_enabled"] is not False or adapted["production_persistence_enabled"] is not False:
        raise SystemExit("source adapter runtime boundary failed open")
    if adapted["personal_contact_extraction_enabled"] is not False:
        raise SystemExit("personal contact extraction failed open")

    second, second_state = adapter.run_dry_run(fixture)
    if adapter.canonical_hash(adapted) != adapter.canonical_hash(second):
        raise SystemExit("source adaptation is not deterministic")
    if adapter.ENGINE.canonical_hash(state) != adapter.ENGINE.canonical_hash(second_state):
        raise SystemExit("adapter to Client Finder state is not deterministic")

    source_text = ADAPTER_PATH.read_text(encoding="utf-8").casefold()
    for forbidden in ("urlopen(", "requests.", "httpx.", "aiohttp."):
        if forbidden in source_text:
            raise SystemExit("network client found in pre-fetched adapter")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "adapted.json"
        state_output = Path(td) / "state.json"
        adapter.ENGINE.write_atomic(output, adapted)
        adapter.ENGINE.write_atomic(state_output, state)
        if adapter.canonical_hash(json.loads(output.read_text(encoding="utf-8"))) != adapter.canonical_hash(adapted):
            raise SystemExit("adapter output readback drift")
        if adapter.ENGINE.canonical_hash(json.loads(state_output.read_text(encoding="utf-8"))) != adapter.ENGINE.canonical_hash(state):
            raise SystemExit("Client Finder state readback drift")

    print(json.dumps({
        "status": "PASS",
        "unit": "R06-CF-SOURCE-ADAPTER-001",
        "profiles": len(profiles),
        "real_source_profiles_activated": 0,
        "synthetic_observations": len(adapted["observations"]),
        "deduplicated_organizations": len(state["records"]),
        "network_fetch": False,
        "production_records": 0,
        "personal_contacts": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
