#!/usr/bin/env python3
"""Hold exact Horizon CL4 2027 AI topics at discovery when DG open conflicts with stale FT index."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

PATH = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ANNOUNCEMENT = "https://digital-strategy.ec.europa.eu/en/news/commission-launches-over-eu290-million-boost-eu-tech-sovereignty-and-beyond"
TOPICS = {
    "04": ("HORIZON-CL4-2027-04-DIGITAL-EMERGING-04",
           "Apply AI: Challenge-Driven AI Innovation Booster in Apply AI prioritised sectors (RIA)",
           "challenge_driven_ai_innovation"),
    "11": ("HORIZON-CL4-2027-04-DIGITAL-EMERGING-11",
           "EU Frontier AI Initiative: Developing frontier AI solutions that are safe and computationally efficient within Apply AI (RIA)",
           "frontier_ai_safe_efficient"),
}
FORBIDDEN = {
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "status", "call_status", "current_status",
    "application_endpoint", "exact_submission_endpoint", "deadline",
    "current_deadline", "budget_eur", "eligibility",
}

def validate(sources):
    ids = [x["id"] for x in sources]
    assert len(ids) == len(set(ids))
    by_id = {x["id"]: x for x in sources}
    for suffix, (topic, title, theme) in TOPICS.items():
        source_id = "SRC-EU-CL4-2027-AI-" + suffix + "-OFFICIAL-STATUS-CONFLICT"
        row = by_id[source_id]
        p = urlparse(row["url"])
        assert p.scheme == "https" and p.hostname == "ec.europa.eu"
        assert not (p.username or p.password or p.port)
        assert p.path.endswith("/topic-details/" + topic)
        assert row["topic_identifier_discovery"] == topic
        assert row["topic_title_discovery"] == title
        assert row["market_intelligence_theme_discovery"] == theme
        assert row["tier"] == "T1"
        assert row["class"] == "official_eu_funding_tenders_exact_topic_indexed_status_conflict_discovery"
        assert row["linked_commission_announcement_url"] == ANNOUNCEMENT
        assert row["linked_commission_announcement_source_id"] == "SRC-EU-DGCONNECT-HORIZON-CL4-2027-DIGITAL-LAUNCH-20261117"
        assert row["authority_class"] == "T1_OFFICIAL_EC_FUNDING_TENDERS"
        assert row["authority_scope"] == "EXACT_TOPIC_INDEXED_AND_DG_ANNOUNCEMENT_DISCOVERY_ONLY_NO_CURRENT_SUBMISSION_PROOF"
        assert row["observation_state"] == "DG_OPEN_VS_STALE_FT_FORTHCOMING_CONFLICT_RAW_PENDING"
        assert row["ft_indexed_status_label_discovery"].startswith("Forthcoming (older")
        assert row["dg_connect_call_level_label_discovery"].startswith("Calls opened 17 November 2026")
        assert row["adapter_required"] == "EC_FT_EXACT_TOPIC_CURRENT_STATUS_AND_ENDPOINT_RECONCILE_V1"
        assert {"EU_DIRECT", "BRUSSELS", "OFFICIAL_STATUS_CONFLICT", "DISCOVERY"} <= set(row["source_families"])
        assert "OPEN_CALL" not in row["source_families"]
        for flag in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
            assert row[flag] is False
        assert not FORBIDDEN.intersection(row)
        assert {"older_ft_index_forthcoming_conflict",
                "commission_announcement_call_level_open_not_exact_topic_submission",
                "current_topic_status_and_exact_submission_endpoint_raw_reconciliation_pending"} <= set(row["extract"])
        for needle in ("SURFACEMC", "final_url", "fetched_at UTC", "raw_sha256",
                       "semantic_sha256", "parser_version", "run_id", "NOT_CAPTURED",
                       "NO OPEN_CALL", "NO MATERIAL PUBLICATION", "NO DISTRIBUTION", "LKG"):
            assert needle in row["note"], (source_id, needle)

def main():
    sources = json.loads(PATH.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    changes = [
        ("observation_state", "OPEN_CALL"), ("authority_scope", "OPEN"),
        ("open_call_authorized", True), ("material_fact_use", True),
        ("material_fact_publication_authorized", True), ("status", "OPEN"),
        ("deadline", "2027-03-18"), ("budget_eur", 107000000),
        ("eligibility", ["all EU companies"]),
        ("application_endpoint", "https://example.invalid/submit"),
        ("fetched_at", "2026-11-19T07:29:00Z"), ("raw_sha256", "0" * 64),
        ("parser_version", "fabricated"), ("topic_identifier_discovery", "FAKE"),
        ("ft_indexed_status_label_discovery", "Open now"),
        ("linked_commission_announcement_url", "https://example.invalid/news"),
    ]
    rejected = 0
    for suffix in TOPICS:
        source_id = "SRC-EU-CL4-2027-AI-" + suffix + "-OFFICIAL-STATUS-CONFLICT"
        for field, value in changes:
            candidate = copy.deepcopy(sources)
            next(x for x in candidate if x["id"] == source_id)[field] = value
            try:
                validate(candidate)
            except AssertionError:
                rejected += 1
            else:
                raise AssertionError("Unsafe material mutation accepted: " + source_id + "." + field)
        duplicate = copy.deepcopy(sources)
        duplicate.append(copy.deepcopy(next(x for x in sources if x["id"] == source_id)))
        try:
            validate(duplicate)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Duplicate identity accepted: " + source_id)
    assert rejected == 34
    print(json.dumps({"result": "PASS", "topics": sorted(TOPICS),
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
