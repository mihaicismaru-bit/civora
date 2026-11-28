#!/usr/bin/env python3
"""Official ADR Centru Action 2.2 FAQ: discovery only, never current OPEN authority."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-PRC-22-DIGITAL-FAQ-20261120"
ACTION = "SRC-PRC-22-DIGITAL-SMES-APEL2-FUTURE-INTAKE-20261119"
URL = "https://www.regiocentru.ro/intrebari-frecvente-ghid-2-2-intreprinderi-digitale-pentru-o-economie-avansata-apel-2/"
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "application_endpoint", "submission_endpoint",
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "verified_faq_text", "current_open"
}

def validate(rows):
    found = [s for s in rows if s.get("id") == ID]
    assert len(found) == 1, "FAQ missing or duplicate"
    assert len([s for s in rows if s.get("id") == ACTION]) == 1, "Missing authoritative action companion"
    s = found[0]
    assert s["tier"] == "T1" and s["url"] == URL
    p = urlsplit(s["url"])
    assert p.scheme == "https" and p.hostname == "www.regiocentru.ro"
    assert not (p.username or p.password or p.port or p.fragment or p.query)
    assert s["class"] == "official_regional_managing_authority_guide_faq_discovery"
    assert s["authority_class"] == "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY"
    assert s["authority_scope"] == "GUIDE_FAQ_DISCOVERY_ONLY_NOT_CURRENT_CALL_AUTHORITY"
    assert s["observation_state"] == "OFFICIAL_GUIDE_FAQ_DISCOVERED_RAW_PENDING"
    assert s["source_publication_date_discovery"] == "2026-11-20"
    assert s["readback_date_discovery"] == "2026-11-21"
    assert s["official_call_identifier_hint_discovery"] == "PRC/1059/PRC_P2/OP1/RSO1.2/PRC_A32"
    assert s["linked_action_source_id"] == ACTION
    assert s["origin_readback_result"] == "HTTP_403_NOT_CAPTURED"
    assert s["adapter_required"] == "PRC_22_FAQ_SURFACEMC_RAW_AND_MYSMIS_SEMANTIC_RECONCILE"
    assert s["freshness_hours"] == 24
    assert s["programmes"] == ["Programul Regiunea Centru 2021-2027"]
    assert s["programme_family"] == "Programul Regiunea Centru 2021-2027"
    assert set(s["source_families"]) == {"ROMANIA", "ADR", "GUIDANCE_DOCUMENT", "MARKET_INTELLIGENCE", "DISCOVERY"}
    assert {"official_20261120_faq_index_discovery", "guide_2_2_appeal_2_QA_document_link_pending_raw",
            "future_submission_window_not_current_open_call",
            "current_guide_and_exact_call_semantic_reconciliation_pending"} <= set(s["extract"])
    for k in ("material_fact_use", "open_call_authorized", "material_fact_publication_authorized", "credentials_required"):
        assert s[k] is False, ("Unsafe publication / open promotion", k)
    assert not (FORBIDDEN & s.keys()), "Material facts or synthetic provenance inserted"
    for token in ("20 November 2026", "2 December 2026", "HTTP 403", "SURFACEMC",
                  "NOT_CAPTURED", "fetched_at UTC", "raw_sha256", "parser_version",
                  "run_id", "handoff_sha256", "MySMIS", "REVIEW", "LKG",
                  "NO OPEN_CALL", "NO DISTRIBUTION", "NO ALERT"):
        assert token in s["note"], ("Missing source safety boundary", token)
    return s

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    mutations = [
        ("tier", "T2"), ("url", "https://example.invalid/faq"),
        ("authority_scope", "CURRENT_OPEN_CALL"), ("observation_state", "OPEN_CALL"),
        ("source_publication_date_discovery", "2026-11-21"),
        ("readback_date_discovery", "2026-11-22"),
        ("origin_readback_result", "HTTP_200_IMMUTABLE_CAPTURE"),
        ("official_call_identifier_hint_discovery", "FAKE-CALL"),
        ("linked_action_source_id", "missing"),
        ("adapter_required", "NONE"), ("open_call_authorized", True),
        ("material_fact_use", True), ("material_fact_publication_authorized", True),
        ("source_families", ["ROMANIA", "OPEN_CALL"]),
        ("deadline", "2027-02-02"), ("budget_eur", 14113032),
        ("eligibility", "all businesses"), ("current_open", True),
        ("submission_endpoint", "https://example.invalid/submit"),
        ("verified_faq_text", "fabricated legal interpretation"),
        ("final_url", URL), ("fetched_at", "2026-11-21T08:00:00Z"),
        ("raw_sha256", "0" * 64), ("parser_version", "fake"),
        ("run_id", "fake"), ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for k,v in mutations:
        mutant=copy.deepcopy(rows)
        next(x for x in mutant if x["id"] == ID)[k] = v
        try:
            validate(mutant)
        except (AssertionError, KeyError):
            rejected += 1
        else:
            raise AssertionError("Unsafe FAQ state admitted: " + k)
    duplicate=copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(x for x in rows if x["id"] == ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate FAQ accepted")
    assert rejected == len(mutations) + 1
    print(json.dumps({"result": "PASS", "source_id": ID,
        "negative_mutations_rejected": rejected, "open_call_authorized": False,
        "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
