#!/usr/bin/env python3
"""Regression: a HaDEA topic-ID typo is not an OPEN_CALL admission receipt.

On the 17 November 2026 CL4 digital launch, HaDEA's photonics detail page
omitted a hyphen in the displayed identifier; its EU Funding & Tenders link
and the official FT index use the hyphenated exact identifier. Discovery
witnesses must remain non-authorizing until original immutable receipts
and live application-route reconciliation are available.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
HADEA = "SRC-EU-HADEA-CL4-2027-05-PHOTONICS-IDENTITY-CONFLICT"
FT = "SRC-EU-FT-CL4-2027-05-PHOTONICS-EXACT-TOPIC-WITNESS"
TRUE_ID = "HORIZON-CL4-2027-05-DIGITAL-EMERGING-03"
HADEA_PRINTED_ID = "HORIZON-CL4-2027-05-DIGITALEMERGING-03"


def validate(rows):
    assert len([x for x in rows if x.get("id") == HADEA]) == 1
    assert len([x for x in rows if x.get("id") == FT]) == 1
    by_id = {x["id"]: x for x in rows}
    h, f = by_id[HADEA], by_id[FT]
    assert h["exact_identifier_observed"] == HADEA_PRINTED_ID
    assert f["exact_identifier_observed"] == TRUE_ID
    assert HADEA_PRINTED_ID != TRUE_ID
    assert h["paired_official_source_id"] == FT
    assert f["paired_official_source_id"] == HADEA
    assert urlparse(h["url"]).hostname == "hadea.ec.europa.eu"
    assert urlparse(f["url"]).hostname == "ec.europa.eu"
    assert TRUE_ID in urlparse(f["url"]).path
    assert HADEA_PRINTED_ID not in urlparse(f["url"]).path
    for source in (h, f):
        assert source["tier"] == "T1"
        assert source["material_fact_use"] is False
        assert source["open_call_authorized"] is False
        assert source["material_fact_publication_authorized"] is False
        assert source["observation_state"].endswith("_RAW_PENDING")
        assert source["authority_scope"]
        assert "source_families" in source and "EU_DIRECT" in source["source_families"]
        assert "NOT_CAPTURED" in source["note"]
        assert "run_id" in source["note"]
        assert "parser_version" in source["note"]
        assert "SHA-256" in source["note"]
    assert by_id["SRC-EU-DGCONNECT-HORIZON-CL4-2027-DIGITAL-LAUNCH-20261117"]["open_call_authorized"] is False


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    for identifier in (HADEA, FT):
        for gate in ("material_fact_use", "open_call_authorized", "material_fact_publication_authorized"):
            mutant = copy.deepcopy(rows)
            next(x for x in mutant if x["id"] == identifier)[gate] = True
            try:
                validate(mutant)
            except AssertionError:
                pass
            else:
                raise AssertionError(f"unsafe {identifier}.{gate} mutation accepted")
    print("PASS photonics HaDEA/FT exact-ID conflict: discovery only, fail-closed with mutation controls")


if __name__ == "__main__":
    main()
