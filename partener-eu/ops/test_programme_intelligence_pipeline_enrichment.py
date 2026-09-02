#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))
sys.path.insert(0, str(ROOT / "partener-eu" / "web"))

import interreg_future_programming_watch as future  # noqa: E402
import programme_intelligence_pipeline_enrichment as enrich_mod  # noqa: E402


def healthy_fetch(row, timeout):
    raw = f"official:{row['id']}".encode()
    return {
        "health_state": "HEALTHY",
        "requested_url": row["authority_url"],
        "final_url": row["authority_url"],
        "http_status": 200,
        "content_type": "text/html",
        "raw_sha256": future._sha(raw),
        "raw_size_bytes": len(raw),
        "missing_marker_groups": [],
        "error_type": None,
        "error": None,
    }


def base_preview():
    card = {
        "card_id": "EEA_NORWAY_PROGRAMMING_1",
        "source_family": "EEA_NORWAY",
        "programme_family": "EEA_NORWAY_ROMANIA_2021_2028",
        "programme": "EEA and Norway Grants Romania 2021-2028",
        "title": "Signed programme framework",
        "observation_state": "PROGRAMMING",
        "observation_label_ro": "Programare",
        "authority_class": "T1_OFFICIAL_FMO",
        "authority_url": "https://eeagrants.org/countries/romania",
        "observed_at": "2026-09-02T07:00:00Z",
        "source_health": "HEALTHY",
        "confidence": "HIGH",
        "confidence_reason": "CURRENT_OFFICIAL_FMO_PROGRAMMING_EVIDENCE_VERIFIED_NON_AUTHORIZING",
        "open_confirmation_state": "NOT_CONFIRMED_PROGRAMMING_ONLY",
        "missing_for_open_confirmation": sorted(enrich_mod.REQUIRED_MISSING_FOR_OPEN),
        "semantic_reconciliation_present": False,
        "semantic_reconciliation_required_before_material_change": True,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }
    output = {
        "schema": enrich_mod.BASE_SCHEMA,
        "parser_version": "FUTURE_PROGRAMMING_PROJECTION_V1",
        "surface": "PROGRAMARE_VIITOARE_PIPELINE",
        "surface_state": "PREVIEW_READ_ONLY_NOT_PUBLISHED",
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "open_upcoming_separation": "STRICT",
        "generated_from": {},
        "card_count": 1,
        "allowed_observation_states": ["PLANNED", "PROGRAMMING"],
        "material_change_claimed": False,
        "semantic_reconciliation_present": False,
        "semantic_reconciliation_required_before_material_change": True,
        "reader_explanation_ro": "preview",
        "cards": [card],
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }
    output["semantic_fingerprint"] = enrich_mod.fingerprint({
        "surface": output["surface"],
        "generated_from": output["generated_from"],
        "cards": output["cards"],
        "material_change_claimed": False,
    })
    return output


def expect_failure(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def main():
    original_fetch = future._fetch
    future._fetch = healthy_fetch
    try:
        snapshot = future.build_snapshot(run_id="future-1", observed_at="2026-09-02T07:00:00Z")
    finally:
        future._fetch = original_fetch
    reconciliation = future.reconcile(snapshot, None, reconciled_at="2026-09-02T07:01:00Z")
    output = enrich_mod.enrich(base_preview(), snapshot, reconciliation)

    assert output["schema"] == enrich_mod.SCHEMA
    assert output["surface_state"] == "PREVIEW_READ_ONLY_NOT_PUBLISHED"
    assert output["seo_indexing_state"] == "NOINDEX_PREVIEW_ONLY"
    assert output["open_upcoming_separation"] == "STRICT"
    assert output["future_programming_card_count"] == 9
    states = {card["observation_state"] for card in output["cards"]}
    assert {"PROGRAMMING", "PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}.issubset(states)
    future_cards = [card for card in output["cards"] if card["card_id"].startswith("INTERREG_FUTURE_")]
    assert all(card["semantic_reconciliation_present"] is True for card in future_cards)
    assert all(card["semantic_reconciliation_material_authority"] is False for card in future_cards)
    assert all(card["open_call_authorized"] is False for card in output["cards"])
    assert all(card["publish_authorized"] is False for card in output["cards"])
    assert all(card["call_alert_authorized"] is False for card in output["cards"])
    bsb = next(card for card in future_cards if card["programme_family"] == "INTERREG_NEXT_BLACK_SEA_BASIN")
    assert bsb["observation_state"] == "CONSULTATION"
    assert bsb["open_confirmation_state"] == "NOT_CONFIRMED_PROGRAMMING_PIPELINE_ONLY"

    tampered = copy.deepcopy(output)
    tampered["cards"][0]["open_call_authorized"] = True
    expect_failure(lambda: enrich_mod.validate(tampered), "card OPEN authorization")

    tampered = copy.deepcopy(output)
    target = next(card for card in tampered["cards"] if card["card_id"].startswith("INTERREG_FUTURE_"))
    target["observation_state"] = "OPEN_CALL"
    expect_failure(lambda: enrich_mod.validate(tampered), "future card OPEN_CALL")

    tampered = copy.deepcopy(output)
    target = next(card for card in tampered["cards"] if card["card_id"].startswith("INTERREG_FUTURE_"))
    target["missing_for_open_confirmation"] = []
    expect_failure(lambda: enrich_mod.validate(tampered), "missing-for-open weakening")

    tampered_base = base_preview()
    tampered_base["publish_authorized"] = True
    expect_failure(lambda: enrich_mod.enrich(tampered_base, snapshot, reconciliation), "base preview publication widening")

    tampered_rec = copy.deepcopy(reconciliation)
    tampered_rec["call_alert_authorized"] = True
    expect_failure(lambda: enrich_mod.enrich(base_preview(), snapshot, tampered_rec), "reconciliation alert widening")

    print({
        "status": "PASS",
        "schema": output["schema"],
        "cards": output["card_count"],
        "future_cards": output["future_programming_card_count"],
        "states": sorted(states),
        "open_upcoming_separation": output["open_upcoming_separation"],
    })


if __name__ == "__main__":
    main()
