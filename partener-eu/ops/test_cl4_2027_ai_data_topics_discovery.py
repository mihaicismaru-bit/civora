#!/usr/bin/env python3
"""CL4 2027 exact AI-data topic discovery: stale indexed stage != live OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
PREFIX = "SRC-EU-HORIZON-CL4-2027-"
TOPICS = {
    "DATA-09": (
        "HORIZON-CL4-2027-04-DATA-09",
        "Energy efficiency and sustainability of AI data processing in Data Centres (IA)",
        "data_centre_ai_energy_efficiency",
    ),
    "DATA-03": (
        "HORIZON-CL4-2027-04-DATA-03",
        "New approaches for decentralized, federated and sustainable AI data processing (RIA)",
        "decentralized_federated_sustainable_ai",
    ),
}
LINKED_ANNOUNCEMENT = "SRC-EU-DGCONNECT-HORIZON-CL4-2027-DIGITAL-LAUNCH-20261117"
MISSING_RECEIPT_OR_MATERIAL = {
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
    "current_status", "call_status", "status", "exact_submission_endpoint",
    "application_endpoint", "current_budget", "budget_eur",
    "current_deadline", "deadline", "eligibility",
}


def validate(rows):
    ids = [x["id"] for x in rows]
    assert len(ids) == len(set(ids)), "duplicate source identity"
    by_id = {x["id"]: x for x in rows}
    assert LINKED_ANNOUNCEMENT in by_id
    for code, (topic, title, theme) in TOPICS.items():
        key = PREFIX + code + "-DISCOVERY"
        assert ids.count(key) == 1
        row = by_id[key]
        assert row["tier"] == "T1"
        assert row["class"] == "official_eu_funding_tenders_exact_topic_indexed_discovery"
        assert row["topic_identifier_discovery"] == topic
        assert row["topic_title_discovery"] == title
        assert row["market_intelligence_theme_discovery"] == theme
        assert row["linked_commission_announcement_source_id"] == LINKED_ANNOUNCEMENT
        p = urlparse(row["url"])
        assert p.scheme == "https" and p.hostname == "ec.europa.eu"
        assert p.path.endswith("/topic-details/" + topic)
        assert p.username is None and p.password is None and p.port is None
        listing = urlparse(row["listing_url"])
        assert listing.scheme == "https" and listing.hostname == "ec.europa.eu"
        assert {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY", "FORTHCOMING", "DISCOVERY"} <= set(row["source_families"])
        assert "OPEN_CALL" not in row["source_families"]
        assert "PROGRAMMING_PIPELINE" not in row["source_families"]
        assert row["authority_class"] == "T1_OFFICIAL_EC_FUNDING_TENDERS"
        assert row["authority_scope"] == "EXACT_TOPIC_INDEXED_DISCOVERY_ONLY_NO_CURRENT_STATUS_OR_SUBMISSION_PROOF"
        assert row["observation_state"] == "EXACT_TOPIC_INDEXED_DISCOVERY_RAW_PENDING"
        assert row["indexed_search_label_discovery"] == "Forthcoming (cached index label, NOT verified present status)"
        assert row["indexed_planned_opening_discovery"] == "2026-11-17 (indexed schedule, NOT current application confirmation)"
        assert row["adapter_required"] == "EC_FT_EXACT_TOPIC_CURRENT_STATUS_AND_ENDPOINT_RECONCILE_V1"
        for flag in ("material_fact_use", "open_call_authorized",
                     "material_fact_publication_authorized", "credentials_required"):
            assert row[flag] is False, (key, flag)
        assert not MISSING_RECEIPT_OR_MATERIAL.intersection(row), "invented current evidence or material admission"
        assert {"older_crawled_index_label_forthcoming_is_not_live_status",
                "direct_exact_topic_detail_returns_js_shell_not_verified_current_call_bytes",
                "source_and_current_submission_endpoint_raw_receipts_missing"} <= set(row["extract"])
        note = row["note"]
        for witness in ("19 November 2026", "17 November 2026", "JS topic shell",
                        "final_url", "fetched_at UTC", "raw_sha256", "semantic_sha256",
                        "parser_version", "run_id", "SURFACEMC", "NOT_CAPTURED",
                        "semantic reconciliation", "NO OPEN_CALL", "no confirmed budget",
                        "no confirmed budget"):
            assert witness in note, (key, witness)


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    rejected = 0
    for code in TOPICS:
        key = PREFIX + code + "-DISCOVERY"
        for field, value in (
            ("observation_state", "OPEN_CALL"),
            ("authority_scope", "EXACT_OPEN_CALL"),
            ("indexed_search_label_discovery", "Open now"),
            ("open_call_authorized", True),
            ("material_fact_use", True),
            ("material_fact_publication_authorized", True),
            ("status", "OPEN"),
            ("deadline", "2027-03-18"),
            ("budget_eur", 39000000),
            ("application_endpoint", "https://example.invalid/submit"),
            ("raw_sha256", "0" * 64),
            ("fetched_at", "2026-11-19T00:00:00Z"),
            ("run_id", "fiction"),
            ("topic_identifier_discovery", "FAKE-ID"),
        ):
            mutation = copy.deepcopy(rows)
            next(x for x in mutation if x["id"] == key)[field] = value
            try:
                validate(mutation)
            except AssertionError:
                rejected += 1
            else:
                raise AssertionError("unsafe mutation admitted: " + key + "." + field)
        duplicate = copy.deepcopy(rows)
        duplicate.append(copy.deepcopy(next(x for x in rows if x["id"] == key)))
        try:
            validate(duplicate)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("duplicate accepted: " + key)
    assert rejected == 30
    print(json.dumps({"result": "PASS", "topics": sorted(TOPICS),
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False,
                      "publication_effect": "NONE"}))


if __name__ == "__main__":
    main()
