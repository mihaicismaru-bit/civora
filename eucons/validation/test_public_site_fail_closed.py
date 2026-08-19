#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

EUCONS_ROOT = Path(__file__).resolve().parents[1]

def load_builder():
    path = EUCONS_ROOT / "web" / "build_public_site.py"
    spec = importlib.util.spec_from_file_location("eucons_build_public_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def main():
    builder = load_builder()
    evidence = {
        "claims": [
            {"claim_class": "SERVICE_OFFERING", "publication_state": "HOLD", "object_ref": "hold_service"},
            {"claim_class": "SERVICE_OFFERING", "publication_state": "PUBLISHABLE", "object_ref": "public_service"},
            {"claim_class": "PROJECT_RESULT", "publication_state": "PUBLISHABLE", "object_ref": "not_a_service"},
        ]
    }
    assert builder.publishable_service_ids(evidence) == {"public_service"}

    people = {
        "people": [
            {"display_name": "Hold Person", "publication_state": "HOLD"},
            {"display_name": "Public Person", "publication_state": "PUBLISHABLE"},
        ]
    }
    assert [p["display_name"] for p in builder.publishable_records(people, "people")] == ["Public Person"]

    cases = {
        "cases": [
            {"title": "Private Case", "publication_state": "HOLD"},
            {"title": "Verified Case", "publication_state": "PUBLISHABLE"},
        ]
    }
    assert [c["title"] for c in builder.publishable_records(cases, "cases")] == ["Verified Case"]

    assert builder.route_file(Path("/tmp/site"), "/") == Path("/tmp/site/index.html")
    assert builder.route_file(Path("/tmp/site"), "/servicii/") == Path("/tmp/site/servicii/index.html")
    assert builder.relative_asset_prefix("/") == ""
    assert builder.relative_asset_prefix("/servicii/") == "../"
    assert builder.relative_asset_prefix("/servicii/example/") == "../../"

    print("PASS: E08 public-site fail-closed regressions")

if __name__ == "__main__":
    main()
