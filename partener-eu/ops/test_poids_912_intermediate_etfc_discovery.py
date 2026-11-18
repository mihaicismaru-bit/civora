#!/usr/bin/env python3
"""No intermediate PoIDS ETFC list can authorize an open call, a final award or a contract."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SOURCE_ID = "SRC-OIRVEST-POIDS-912-ITI-DELTA-INTERIM-ETFC-20261116"
CALL_ID = "PIDS/912/PIDS_P3/OP4/RSO4.3/PIDS_A11"
NOTICE = (
    "https://oirvest.ro/poids-autoritatea-de-management-pentru-programul-incluziune-"
    "si-demnitate-sociala-poids-2021-2027-publica-lista-intermediara-nr-1-a-"
    "proiectelor-aprobate-ca-urmare-a-finalizarii-pr-2/"
)
PRIMARY = "https://mfe.gov.ro/wp-content/uploads/2026/11/9c818ad0f09c99254c5a3ea47bb77058.pdf"


def validate(rows):
    matches = [source for source in rows if source.get("id") == SOURCE_ID]
    assert len(matches) == 1, "Missing or duplicate OIR Vest PoIDS exact notice"
    s = matches[0]
    assert s["url"] == NOTICE and urlparse(s["url"]).hostname == "oirvest.ro"
    assert s["linked_primary_document_url_discovery"] == PRIMARY
    assert urlparse(PRIMARY).hostname == "mfe.gov.ro"
    assert s["tier"] == "T1B"
    assert s["authority_class"] == "T1B_OFFICIAL_INTERMEDIATE_BODY_REPUBLICATION"
    assert s["authority_scope"] == "INTERMEDIATE_ETFC_SELECTION_STAGE_DISCOVERY_ONLY"
    assert s["observation_state"] == "INTERMEDIATE_ETFC_APPROVED_LIST_LINK_DISCOVERED_RAW_PENDING"
    assert s["selection_stage_discovery"] == "INTERMEDIATE_ETFC_APPROVED_LIST_NO_FINAL_CONTRACT_AWARD"
    assert s["event_date_discovery"] == "2026-11-16"
    assert s["call_identifier_discovery"] == CALL_ID
    assert s["programme_family"] == "PoIDS 2021-2027"
    assert {"ROMANIA", "MIPE", "OI", "PoIDS", "SELECTION_RESULTS", "DISCOVERY"}.issubset(
        set(s["source_families"])
    )
    for flag in ("material_fact_use", "open_call_authorized",
                 "material_fact_publication_authorized", "publish_authorized",
                 "final_selection_authorized", "contracting_completed_authorized"):
        assert s[flag] is False, f"Unsafe promotion: {flag}"
    note = s["note"].lower()
    for required in ("timeout", "not_captured", "fetched_at", "sha-256",
                     "parser_version", "run_id", "immutable handoff",
                     "mysmis", "appeal"):
        assert required in note, required
    assert "OPEN_CALL" not in s["observation_state"]
    assert "OPEN_CALL" not in s["selection_stage_discovery"]


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    rejected = 0
    cases = {
        "call_identifier_discovery": "PIDS/944/PIDS_P3/OP4/RSO4.3/PIDS_A11",
        "url": "https://example.com/fake",
        "linked_primary_document_url_discovery": "https://example.com/false.pdf",
        "observation_state": "OPEN_CALL",
        "selection_stage_discovery": "FINAL_AWARDED",
        "event_date_discovery": "2026-11-18",
    }
    cases.update(dict.fromkeys(
        ("material_fact_use", "open_call_authorized",
         "material_fact_publication_authorized", "publish_authorized",
         "final_selection_authorized", "contracting_completed_authorized"), True
    ))
    for field, value in cases.items():
        mutant = copy.deepcopy(rows)
        next(s for s in mutant if s["id"] == SOURCE_ID)[field] = value
        try:
            validate(mutant)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError(f"Unsafe intermediate-list mutation admitted: {field}")
    print(json.dumps({"result": "PASS", "negative_mutations_rejected": rejected,
                      "stage": "INTERMEDIATE_ETFC_DISCOVERY_ONLY",
                      "open_call_authorized": False, "publication_effect": "NONE"}))


if __name__ == "__main__":
    main()
