#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"

EXPECTED = {
    "SRC-OI-RESEARCH-POCIDIF": {
        "primary_url": "https://www2.poc.research.gov.ro/ro/articol/4428/apeluri-de-proiecte-pocidif-prioritatea-1",
        "required_aliases": {
            "https://newpoc.research.gov.ro/ro/categorie/108/pocidif-2021-2027",
            "https://poc.research.gov.ro/ro/articol/4382/2021-2027-pocidif-2021-2027",
            "https://www.poc.research.gov.ro/ro/articol/4382/2021-2027-pocidif-2021-2027",
            "https://poc.mcid.gov.ro/ro/articol/4382/2021-2027-pocidif-2021-2027",
        },
        "programme_path": "/ro/articol/4428/apeluri-de-proiecte-pocidif-prioritatea-1",
    },
    "SRC-OI-RESEARCH-HEALTH": {
        "primary_url": "https://www2.poc.research.gov.ro/ro/articol/4429/apeluri-de-proiecte-pos-prioritatea-5",
        "required_aliases": {
            "https://newpoc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
            "https://poc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
            "https://www.poc.research.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
            "https://poc.mcid.gov.ro/ro/articol/4427/2021-2027-pos-2021-2027",
        },
        "programme_path": "/ro/articol/4429/apeluri-de-proiecte-pos-prioritatea-5",
    },
}


def main():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in data.get("sources", [])}

    for source_id, expected in EXPECTED.items():
        assert source_id in by_id, f"missing source: {source_id}"
        row = by_id[source_id]
        assert row.get("url") == expected["primary_url"], (source_id, row.get("url"))
        parsed = urlparse(row["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "www2.poc.research.gov.ro"
        assert parsed.path == expected["programme_path"]
        assert row.get("tier") == "T1B"
        assert row.get("material_fact_use") is True

        aliases = set(row.get("canonical_aliases") or [])
        assert expected["required_aliases"].issubset(aliases), (source_id, aliases)

        note = str(row.get("note") or "").lower()
        for blocked_fact in ("deadline", "status", "budget", "eligibility"):
            assert blocked_fact in note, (source_id, blocked_fact, note)
        assert "exact current call-level evidence" in note, (source_id, note)
        assert "reconciliation" in note, (source_id, note)

    stale_primary = [
        row["id"]
        for row in data.get("sources", [])
        if row.get("id") in EXPECTED
        and urlparse(row.get("url") or "").hostname != "www2.poc.research.gov.ro"
    ]
    assert not stale_primary, f"non-current OI Research host still primary: {stale_primary}"
    print("PASS current official OI Research programme hosts and fail-closed material-fact boundary")


if __name__ == "__main__":
    main()
