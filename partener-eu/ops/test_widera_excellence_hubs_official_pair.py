#!/usr/bin/env python3
"""Excellence Hubs: REA and F&T exact topic corroboration is discovery, not OPEN admission."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
REA_ID = "SRC-EU-REA-WIDERA-EXCELLENCE-HUBS-2026"
FT_ID = "SRC-EU-FT-WIDERA-2027-04-WIDENING-01"
REA_URL = "https://rea.ec.europa.eu/funding-and-grants/horizon-europe-widening-participation-and-spreading-excellence/excellence-hubs_en"
FT_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-WIDERA-2027-04-WIDENING-01"
FORBIDDEN = {
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256", "status",
    "current_status", "call_status", "current_application_endpoint",
    "application_endpoint", "exact_submission_endpoint", "deadline",
    "budget", "budget_eur", "eligibility", "publication_authorized",
}

def validate(rows):
    ids = [s["id"] for s in rows]
    assert len(ids) == len(set(ids)), "source IDs must remain unique"
    by_id = {s["id"]: s for s in rows}
    assert REA_ID in by_id and FT_ID in by_id
    rea, ft = by_id[REA_ID], by_id[FT_ID]
    assert rea["linked_exact_topic_source_id"] == FT_ID
    assert ft["linked_rea_source_id"] == REA_ID
    for row, url, host, klass, scope, obs in (
        (rea, REA_URL, "rea.ec.europa.eu", "T1_OFFICIAL_EC_REA_PROGRAMME_OPERATOR",
         "EXACT_TOPIC_REA_GUIDANCE_DISCOVERY_ONLY_PORTAL_CALL_TEXT_PRECEDENCE",
         "REA_EXACT_TOPIC_TIMELINE_READBACK_RAW_PENDING"),
        (ft, FT_URL, "ec.europa.eu", "T1_OFFICIAL_EC_FUNDING_TENDERS",
         "EXACT_TOPIC_INDEX_AND_JS_SHELL_DISCOVERY_ONLY_NO_APPLICATION_RECEIPT",
         "EXACT_TOPIC_PORTAL_LISTED_OPEN_LABEL_RAW_PENDING"),
    ):
        p = urlparse(row["url"])
        assert row["url"] == url and p.scheme == "https" and p.hostname == host
        assert p.username is None and p.password is None and p.port is None
        assert row["tier"] == "T1" and row["authority_class"] == klass
        assert row["authority_scope"] == scope and row["observation_state"] == obs
        assert row["topic_identifier_discovery"] == "HORIZON-WIDERA-2027-04-WIDENING-01"
        assert row["call_identifier_discovery"] == "HORIZON-WIDERA-2027-04"
        assert row["historical_opening_date_discovery"] == "2026-09-02"
        assert row["announced_deadline_date_discovery"] == "2027-03-04"
        assert row["indicative_topic_envelope_eur_discovery"] == 100000000
        assert row["readback_date_discovery"] == "2026-11-19"
        assert {"EU_DIRECT", "BRUSSELS", "HORIZON_EUROPE", "WIDERA", "CALL_REGISTRY", "DISCOVERY"} <= set(row["source_families"])
        assert "OPEN_CALL" not in row["source_families"]
        assert row["adapter_required"] == "WIDERA_EXCELLENCE_HUBS_REA_FT_EXACT_ORIGINALS_AND_SUBMISSION_RECONCILE_V1"
        for flag in ("open_call_authorized", "material_fact_use",
                     "material_fact_publication_authorized", "credentials_required"):
            assert row[flag] is False
        assert not FORBIDDEN.intersection(row), "fabricated receipt or canonical fact"
        for term in ("19 November 2026", "SURFACEMC", "NOT_CAPTURED", "final_url",
                     "fetched_at UTC", "raw_sha256", "parser_version", "run_id",
                     "semantic reconciliation", "LKG", "NO OPEN_CALL"):
            assert term.lower() in row["note"].lower(), term
    assert ft["portal_index_label_discovery"].startswith("Open For Submission")
    assert "JS shell" in ft["note"]
    assert "legal call text takes precedence" in rea["note"]

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    mutations = [
        ("open_call_authorized", True), ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("observation_state", "OPEN_CALL"), ("authority_scope", "OPEN_CALL"),
        ("tier", "T3"), ("topic_identifier_discovery", "FAKE"),
        ("announced_deadline_date_discovery", "2027-12-01"),
        ("indicative_topic_envelope_eur_discovery", 1),
        ("historical_opening_date_discovery", "2026-11-19"),
        ("portal_index_label_discovery", "Approved for canonical release"),
        ("status", "OPEN"), ("deadline", "2027-03-04"),
        ("budget_eur", 100000000), ("eligibility", ["everyone"]),
        ("application_endpoint", "https://example.invalid/apply"),
        ("final_url", FT_URL), ("fetched_at", "2026-11-19T00:00:00Z"),
        ("raw_sha256", "0"*64), ("parser_version", "invented"),
        ("run_id", "invented"),
    ]
    rejected = 0
    for key, value in mutations:
        trial = copy.deepcopy(rows)
        next(s for s in trial if s["id"] == FT_ID)[key] = value
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("unsafe mutation accepted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == FT_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("duplicate official topic source accepted")
    assert rejected == len(mutations) + 1
    print(json.dumps({"result": "PASS", "official_paired_sources": 2,
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
