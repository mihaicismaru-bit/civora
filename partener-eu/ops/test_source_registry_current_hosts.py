#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"

EXPECTED = {
    "SRC-OI-RESEARCH-POCIDIF": {
        "url": "https://newpoc.research.gov.ro/ro/categorie/108/pocidif-2021-2027",
        "legacy": {
            "https://poc.research.gov.ro/ro/articol/4382/2021-2027-pocidif-2021-2027",
            "https://www.poc.research.gov.ro/ro/articol/4382/2021-2027-pocidif-2021-2027",
        },
    },
    "SRC-OI-RESEARCH-HEALTH": {
        "url": "https://newpoc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
        "legacy": {
            "https://poc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
            "https://www.poc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
        },
    },
}


def main():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in data.get("sources", [])}

    for source_id, expected in EXPECTED.items():
        assert source_id in by_id, f"missing source: {source_id}"
        row = by_id[source_id]
        assert row.get("url") == expected["url"], (source_id, row.get("url"))
        parsed = urlparse(row["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "newpoc.research.gov.ro"
        assert row.get("tier") == "T1B"
        assert row.get("material_fact_use") is True
        aliases = set(row.get("canonical_aliases") or [])
        assert expected["legacy"].issubset(aliases), (source_id, aliases)

    stale_primary = [
        row["id"]
        for row in data.get("sources", [])
        if urlparse(row.get("url") or "").hostname in {"poc.research.gov.ro", "www.poc.research.gov.ro"}
    ]
    assert not stale_primary, f"legacy OI Research host still primary: {stale_primary}"
    print("PASS current OI Research source hosts and legacy provenance aliases")


if __name__ == "__main__":
    main()
