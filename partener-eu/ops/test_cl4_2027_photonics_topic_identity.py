#!/usr/bin/env python3
"""Regression for the existing HaDEA/FT photonics exact topic ID witnesses.

HaDEA displays HORIZON-CL4-2027-05-DIGITALEMERGING-03 whereas the linked
Funding & Tenders topic identifier has DIGITAL-EMERGING-03. An earlier indexed
FT 'Forthcoming' label and the HaDEA 'Open' badge are NOT synchronous current
call evidence. Neither source alone authorizes OPEN_CALL.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
HADEA = "SRC-EU-HADEA-CL4-2027-PHOTONICS-ID-WITNESS"
FT = "SRC-EU-HORIZON-CL4-2027-PHOTONICS-FORTHCOMING"
FT_ID = "HORIZON-CL4-2027-05-DIGITAL-EMERGING-03"
HADEA_ID = "HORIZON-CL4-2027-05-DIGITALEMERGING-03"


def validate(rows):
    assert len([x for x in rows if x.get("id") == HADEA]) == 1
    assert len([x for x in rows if x.get("id") == FT]) == 1
    by_id = {x["id"]: x for x in rows}
    h, f = by_id[HADEA], by_id[FT]
    assert h["displayed_reference_discovery"] == HADEA_ID
    assert h["ft_exact_topic_identifier_discovery"] == FT_ID
    assert f["topic_identifier_discovery"] == FT_ID
    assert HADEA_ID != FT_ID
    assert h["paired_official_source_id"] == FT
    assert h["linked_ft_topic_url"] == f["url"]
    assert urlparse(h["url"]).hostname == "hadea.ec.europa.eu"
    assert urlparse(f["url"]).hostname == "ec.europa.eu"
    assert FT_ID in urlparse(f["url"]).path
    assert HADEA_ID not in urlparse(f["url"]).path
    assert h["tier"] == "T1B" and f["tier"] == "T1"
    assert h["status_display_discovery"] == "Open"
    assert h["status_display_is_current_call_authority"] is False
    assert f["observation_state"] == "FORTHCOMING_EXACT_TOPIC_DISCOVERED_RAW_PENDING"
    assert h["observation_state"] == "AGENCY_REFERENCE_FORMAT_AND_STATUS_WITNESS_RAW_PENDING"
    for source in (h, f):
        assert source["material_fact_use"] is False
        assert source["open_call_authorized"] is False
        assert source["material_fact_publication_authorized"] is False
        assert source["authority_scope"]
        assert "EU_DIRECT" in source["source_families"]
        note = source["note"].lower()
        for missing_receipt in ("sha-256", "fetched_at", "parser_version", "run_id"):
            assert missing_receipt in note, (source["id"], missing_receipt)
        assert "reconciliation" in note
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
    print("PASS existing HaDEA/FT photonics witnesses: ID alias and status promotion remain fail-closed")


if __name__ == "__main__":
    main()
