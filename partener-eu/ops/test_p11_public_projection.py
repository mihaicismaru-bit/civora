#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("projection", ROOT / "p11" / "build_public_projection.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    bundle = json.loads((ROOT / "p11" / "opportunity_bundle.json").read_text(encoding="utf-8"))
    projection = mod.build(bundle)
    assert projection["summary"]["opportunityCount"] == 26
    assert projection["summary"]["openVerifiedCount"] >= 1
    step = next(row for row in projection["opportunities"] if row["id"] == "PEO-STEP-LLL-ADULTI-2026")
    assert step["status"] == "OPEN"
    assert {"status", "deadline"} <= set(step["verifiedFactClasses"])
    regional = next(row for row in projection["opportunities"] if row["id"] == "pr-centru-digital-2")
    assert regional["status"] == "DISCOVERED"
    assert regional["materialFacts"] == {}
    north_east = next(
        row for row in projection["opportunities"]
        if row["id"] == "pr-ne-energy-residential-towns-2026"
    )
    assert north_east["status"] == "EXPECTED"
    assert north_east["publicationState"] == "PUBLISHABLE"
    assert set(north_east["verifiedFactClasses"]) == {
        "status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"
    }
    clusters = next(
        row for row in projection["opportunities"]
        if row["id"] == "pr-centru-clusters-122"
    )
    assert clusters["status"] == "OPEN"
    assert clusters["publicationState"] == "PUBLISHABLE"
    assert clusters["materialFacts"]["budget"]["total_eur"] == 11664904
    assert clusters["materialFacts"]["grant"]["maximum_eur"] == 3500000
    pids = next(
        row for row in projection["opportunities"]
        if row["id"] == "pids-supported-decision"
    )
    assert pids["status"] == "OPEN"
    assert pids["publicationState"] == "PUBLISHABLE"
    assert pids["materialFacts"]["budget"]["total_eur"] == 11804343
    assert pids["materialFacts"]["grant"]["form"] == "grant nerambursabil"
    assert pids["materialFacts"]["scoring"]["minimum_total_points"] == 70
    assert set(pids["verifiedFactClasses"]) == {
        "status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"
    }
    step_edu = next(
        row for row in projection["opportunities"]
        if row["id"] == "peo-step-edu-adulti"
    )
    assert step_edu["status"] == "DISCOVERED"
    assert step_edu["publicationState"] == "QUARANTINED"
    assert step_edu["materialFacts"] == {}
    assert step_edu["verifiedFactClasses"] == []
    print("PASS P11 public projection")


if __name__ == "__main__":
    main()
