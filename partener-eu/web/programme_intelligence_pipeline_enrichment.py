#!/usr/bin/env python3
"""Enrich the artifact-only PROGRAMARE VIITOARE preview with reconciled Interreg 2028-2034 evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))
import interreg_future_programming_watch as future  # noqa: E402

SCHEMA = "PARTENER_EU_FUTURE_PROGRAMMING_PROJECTION_V2"
PARSER_VERSION = "FUTURE_PROGRAMMING_PROJECTION_ENRICHMENT_V1"
BASE_SCHEMA = "PARTENER_EU_FUTURE_PROGRAMMING_PROJECTION_V1"
ALLOWED_STATES = {"PROGRAMMING", "PLANNED", "PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
STATE_LABELS_RO = {
    "PROGRAMMING": "Programare",
    "PLANNED": "Planificat",
    "PROPOSAL": "Propunere",
    "CONSULTATION": "Consultare",
    "PROGRAMMING_PROCESS": "Programare",
}
MATERIAL_FLAGS = future.MATERIAL_FLAGS
REQUIRED_MISSING_FOR_OPEN = set(future.MISSING_FOR_OPEN)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require_false(obj: Mapping[str, Any], label: str) -> None:
    if obj.get("market_intelligence_only") is not True or obj.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: market-intelligence boundary drift")
    for flag in MATERIAL_FLAGS:
        if obj.get(flag) is not False:
            raise ValueError(f"{label}: authorizing drift on {flag}")


def validate_base(base: Mapping[str, Any]) -> None:
    if base.get("schema") != BASE_SCHEMA:
        raise ValueError("base preview schema mismatch")
    if base.get("surface") != "PROGRAMARE_VIITOARE_PIPELINE":
        raise ValueError("base preview surface mismatch")
    if base.get("surface_state") != "PREVIEW_READ_ONLY_NOT_PUBLISHED" or base.get("seo_indexing_state") != "NOINDEX_PREVIEW_ONLY":
        raise ValueError("base preview publication boundary drift")
    if base.get("open_upcoming_separation") != "STRICT":
        raise ValueError("base preview OPEN/UPCOMING separation weakened")
    require_false(base, "base preview")
    for card in base.get("cards") or []:
        require_false(card, f"base card {card.get('card_id')}")


def _change_index(reconciliation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if reconciliation.get("schema") != future.RECONCILIATION_SCHEMA:
        raise ValueError("future programming reconciliation schema mismatch")
    require_false(reconciliation, "future programming reconciliation")
    return {str(item.get("source_id")): item for item in reconciliation.get("changes") or []}


def _confidence(row: Mapping[str, Any]) -> tuple[str, str]:
    health = (row.get("source_health") or {}).get("health_state")
    if health == "HEALTHY":
        return "HIGH", "CURRENT_OFFICIAL_PROGRAMMING_SOURCE_VERIFIED_NON_AUTHORIZING"
    return "LOW", "CURRENT_OFFICIAL_PROGRAMMING_SOURCE_DEGRADED_LKG_IF_AVAILABLE_IS_EVIDENCE_ONLY"


def enrich(base: Mapping[str, Any], snapshot: Mapping[str, Any], reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    validate_base(base)
    future.validate_snapshot(snapshot)
    changes = _change_index(reconciliation)
    cards = [dict(card) for card in base.get("cards") or []]
    seen = {str(card.get("card_id")) for card in cards}

    for row in snapshot["watchlist"]:
        if row.get("projection_eligible") is not True:
            continue
        state = str(row.get("observation_state"))
        if state not in {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}:
            raise ValueError(f"projection-eligible future row has forbidden state: {state}")
        card_id = f"INTERREG_FUTURE_{row['source_id']}"
        if card_id in seen:
            raise ValueError(f"duplicate enriched card id: {card_id}")
        seen.add(card_id)
        confidence, confidence_reason = _confidence(row)
        change = changes.get(row["source_id"]) or {}
        lkg = change.get("lkg_reference") if isinstance(change, Mapping) else None
        cards.append({
            "card_id": card_id,
            "source_family": "INTERREG",
            "programme_family": row.get("programme_family"),
            "programme": row.get("programme"),
            "title": row.get("programme"),
            "observation_state": state,
            "observation_label_ro": STATE_LABELS_RO[state],
            "consultation_lifecycle": row.get("consultation_lifecycle"),
            "authority_class": row.get("authority_class"),
            "authority_url": row.get("authority_url"),
            "supporting_authority_url": row.get("supporting_authority_url"),
            "observed_at": snapshot.get("fetched_at"),
            "source_health": (row.get("source_health") or {}).get("health_state"),
            "source_hash": (row.get("source_health") or {}).get("raw_sha256"),
            "semantic_fingerprint": row.get("semantic_fingerprint"),
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "reconciliation_state": reconciliation.get("reconciliation_state"),
            "source_change_kind": change.get("change_kind"),
            "lkg_reference_state": change.get("lkg_status"),
            "lkg_reference_available": bool(lkg),
            "open_confirmation_state": "NOT_CONFIRMED_PROGRAMMING_PIPELINE_ONLY",
            "missing_for_open_confirmation": sorted(set(row.get("missing_for_open_confirmation") or []) | REQUIRED_MISSING_FOR_OPEN),
            "semantic_reconciliation_present": True,
            "semantic_reconciliation_material_authority": False,
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
        })

    cards.sort(key=lambda item: (str(item.get("source_family")), str(item.get("observation_state")), str(item.get("card_id"))))
    output = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "surface": "PROGRAMARE_VIITOARE_PIPELINE",
        "surface_state": "PREVIEW_READ_ONLY_NOT_PUBLISHED",
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "open_upcoming_separation": "STRICT",
        "allowed_observation_states": sorted(ALLOWED_STATES),
        "generated_from": {
            "base_preview_schema": base.get("schema"),
            "base_preview_semantic_fingerprint": base.get("semantic_fingerprint"),
            "interreg_future_run_id": snapshot.get("run_id"),
            "interreg_future_fetched_at": snapshot.get("fetched_at"),
            "interreg_future_semantic_fingerprint": snapshot.get("semantic_fingerprint"),
            "interreg_future_transport_fingerprint": snapshot.get("transport_fingerprint"),
            "interreg_future_reconciliation_state": reconciliation.get("reconciliation_state"),
        },
        "card_count": len(cards),
        "future_programming_card_count": sum(1 for card in cards if str(card.get("card_id")).startswith("INTERREG_FUTURE_")),
        "material_change_claimed": False,
        "semantic_reconciliation_present": True,
        "semantic_reconciliation_material_authority": False,
        "reader_explanation_ro": (
            "PROGRAMARE VIITOARE arată propuneri, consultări și procese oficiale de programare separat de apelurile OPEN/UPCOMING. "
            "Niciun element de aici nu este apel deschis. Pentru confirmare sunt necesare identificatorul exact al apelului, endpointul oficial curent, "
            "reconcilierea semantică pe aceeași identitate și admiterea materială pe câmpuri."
        ),
        "cards": cards,
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
    output["semantic_fingerprint"] = fingerprint({
        "surface": output["surface"],
        "generated_from": output["generated_from"],
        "cards": cards,
        "material_change_claimed": False,
    })
    validate(output)
    return output


def validate(output: Mapping[str, Any]) -> None:
    if output.get("schema") != SCHEMA or output.get("parser_version") != PARSER_VERSION:
        raise ValueError("enriched preview schema/parser mismatch")
    if output.get("surface") != "PROGRAMARE_VIITOARE_PIPELINE" or output.get("surface_state") != "PREVIEW_READ_ONLY_NOT_PUBLISHED":
        raise ValueError("enriched preview surface drift")
    if output.get("seo_indexing_state") != "NOINDEX_PREVIEW_ONLY" or output.get("open_upcoming_separation") != "STRICT":
        raise ValueError("enriched preview publication/separation boundary drift")
    require_false(output, "enriched preview")
    if output.get("material_change_claimed") is not False:
        raise ValueError("enriched preview claimed material change")
    if output.get("semantic_reconciliation_present") is not True or output.get("semantic_reconciliation_material_authority") is not False:
        raise ValueError("enriched preview reconciliation boundary drift")
    cards = output.get("cards")
    if not isinstance(cards, list) or not cards or output.get("card_count") != len(cards):
        raise ValueError("enriched preview card inventory mismatch")
    if output.get("future_programming_card_count", 0) < 1:
        raise ValueError("enriched preview missing future-programming cards")
    seen: set[str] = set()
    for card in cards:
        cid = str(card.get("card_id") or "")
        if not cid or cid in seen:
            raise ValueError("enriched preview card id missing/duplicate")
        seen.add(cid)
        if card.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{cid}: forbidden observation state")
        require_false(card, f"enriched card {cid}")
        missing = set(card.get("missing_for_open_confirmation") or [])
        if str(cid).startswith("INTERREG_FUTURE_") and not REQUIRED_MISSING_FOR_OPEN.issubset(missing):
            raise ValueError(f"{cid}: missing-for-open boundary weakened")
        if str(cid).startswith("INTERREG_FUTURE_") and card.get("open_confirmation_state") != "NOT_CONFIRMED_PROGRAMMING_PIPELINE_ONLY":
            raise ValueError(f"{cid}: future card confirmation-state drift")
    expected = fingerprint({
        "surface": output["surface"],
        "generated_from": output["generated_from"],
        "cards": cards,
        "material_change_claimed": False,
    })
    if output.get("semantic_fingerprint") != expected:
        raise ValueError("enriched preview semantic fingerprint mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-preview", type=Path, required=True)
    parser.add_argument("--future-snapshot", type=Path, required=True)
    parser.add_argument("--future-reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = json.loads(args.base_preview.read_text(encoding="utf-8"))
    snapshot = json.loads(args.future_snapshot.read_text(encoding="utf-8"))
    reconciliation = json.loads(args.future_reconciliation.read_text(encoding="utf-8"))
    output = enrich(base, snapshot, reconciliation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
