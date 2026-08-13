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
    print("PASS P11 public projection")


if __name__ == "__main__":
    main()
