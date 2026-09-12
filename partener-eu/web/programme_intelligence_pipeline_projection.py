#!/usr/bin/env python3
"""Read-only public-model projection for PARTENER.EU future programming intelligence.

Consumes already-validated official programme receipts and produces a preview-only
PROGRAMARE VIITOARE / PIPELINE projection. It never authorizes OPEN/CLOSED call
facts, deadlines, budgets, eligibility, publication, distribution or canonical
corpus mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "PARTENER_EU_FUTURE_PROGRAMMING_PROJECTION_V1"
PARSER_VERSION = "FUTURE_PROGRAMMING_PROJECTION_V1"
SURFACE = "PROGRAMARE_VIITOARE_PIPELINE"
EEA_SCHEMA = "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1"
INTERREG_SCHEMA = "PARTENER_EU_INTERREG_ROMANIA_CALL_SURFACE_WATCH_V2"
ALLOWED_STATES = {"PROGRAMMING", "PLANNED"}
STATE_LABELS_RO = {
    "PROGRAMMING": "Programare",
    "PLANNED": "Planificat",
}
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)
REQUIRED_MISSING_FOR_OPEN = {
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "same_identity_semantic_reconciliation",
    "field_scoped_material_admission",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _require_false_flags(obj: Mapping[str, Any], *, label: str) -> None:
    if obj.get("market_intelligence_only") is not True:
        raise ValueError(f"{label}: market_intelligence_only must remain true")
    if obj.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: publication_effect must remain NONE")
    for flag in MATERIAL_FLAGS:
        if obj.get(flag) is not False:
            raise ValueError(f"{label}: authorizing drift on {flag}")


def _validate_eea(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != EEA_SCHEMA:
        raise ValueError("EEA/Norway input schema mismatch")
    if receipt.get("source_family") != "EEA_NORWAY":
        raise ValueError("EEA/Norway source family mismatch")
    if receipt.get("source_health") != "HEALTHY":
        raise ValueError("EEA/Norway projection requires current healthy official evidence")
    _require_false_flags(receipt, label="EEA/Norway input")
    observations = receipt.get("programming_observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("EEA/Norway programming observations missing")
    for row in observations:
        if not isinstance(row, Mapping) or row.get("observation_state") != "PROGRAMMING":
            raise ValueError("EEA/Norway programming observation drift")
        if row.get("open_call_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError("EEA/Norway programming observation attempted authorization")
        if not str(row.get("source_url") or "").startswith("https://eeagrants.org/"):
            raise ValueError("EEA/Norway programming observation left official FMO authority")


def _validate_interreg(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != INTERREG_SCHEMA:
        raise ValueError("Interreg call-surface input schema mismatch")
    if receipt.get("source_family") != "INTERREG":
        raise ValueError("Interreg source family mismatch")
    if receipt.get("source_health") not in {"HEALTHY", "DEGRADED"}:
        raise ValueError("Interreg source health invalid")
    _require_false_flags(receipt, label="Interreg input")
    if receipt.get("discovered_call_facts") != []:
        raise ValueError("Interreg call-surface watch emitted call facts")
    if receipt.get("fallback_does_not_restore_call_surface_coverage") is not True:
        raise ValueError("Interreg fallback boundary weakened")
    surfaces = receipt.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise ValueError("Interreg surfaces missing")
    for row in surfaces:
        if not isinstance(row, Mapping):
            raise ValueError("Interreg surface must be an object")
        if row.get("observation_state") not in {"CALL_DISCOVERY_ONLY", "PLANNED"}:
            raise ValueError("Interreg surface observation state drift")
        if row.get("market_intelligence_only") is not True:
            raise ValueError("Interreg surface escaped market-intelligence boundary")
        for flag in (
            "call_fact_authorized",
            "status_fact_authorized",
            "deadline_fact_authorized",
            "budget_fact_authorized",
            "eligibility_fact_authorized",
        ):
            if row.get(flag) is not False:
                raise ValueError(f"Interreg surface attempted authorization: {flag}")
        fallback = row.get("fallback_provenance")
        if not isinstance(fallback, Mapping):
            raise ValueError("Interreg surface missing fallback provenance")
        if fallback.get("call_surface_authority") is not False or fallback.get("call_fact_authorized") is not False:
            raise ValueError("Interreg fallback attempted call authority")


def _confidence_for_interreg(row: Mapping[str, Any]) -> tuple[str, str]:
    if row.get("transport_health") == "HEALTHY":
        return "HIGH", "CURRENT_OFFICIAL_PROGRAMME_SURFACE_VERIFIED_NON_AUTHORIZING"
    fallback = row.get("fallback_provenance") or {}
    if fallback.get("transport_health") == "HEALTHY":
        return "LOW", "DIRECT_PROGRAMME_SURFACE_DEGRADED_REGISTRY_PROVENANCE_ONLY"
    return "LOW", "CURRENT_PROGRAMME_SURFACE_PROOF_DEGRADED"


def _missing_for_open(extra: list[str] | None = None) -> list[str]:
    values = set(REQUIRED_MISSING_FOR_OPEN)
    for value in extra or []:
        normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized:
            values.add(normalized)
    return sorted(values)


def project(eea: Mapping[str, Any], interreg: Mapping[str, Any]) -> dict[str, Any]:
    _validate_eea(eea)
    _validate_interreg(interreg)

    cards: list[dict[str, Any]] = []
    for index, row in enumerate(eea["programming_observations"], start=1):
        cards.append({
            "card_id": f"EEA_NORWAY_PROGRAMMING_{index}",
            "source_family": "EEA_NORWAY",
            "programme_family": eea.get("programme_family"),
            "programme": "EEA and Norway Grants Romania 2021-2028",
            "title": row.get("title"),
            "observation_state": "PROGRAMMING",
            "observation_label_ro": STATE_LABELS_RO["PROGRAMMING"],
            "authority_class": row.get("authority_class") or eea.get("authority_class"),
            "authority_url": row.get("source_url"),
            "observed_at": row.get("observed_at") or eea.get("fetched_at"),
            "source_health": "HEALTHY",
            "confidence": "HIGH",
            "confidence_reason": "CURRENT_OFFICIAL_FMO_PROGRAMMING_EVIDENCE_VERIFIED_NON_AUTHORIZING",
            "open_confirmation_state": "NOT_CONFIRMED_PROGRAMMING_ONLY",
            "missing_for_open_confirmation": _missing_for_open(eea.get("missing_for_open_call_confirmation")),
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
        })

    for row in interreg["surfaces"]:
        if row.get("observation_state") != "PLANNED":
            continue
        confidence, confidence_reason = _confidence_for_interreg(row)
        cards.append({
            "card_id": f"INTERREG_{row.get('programme_id')}_PLANNED",
            "source_family": "INTERREG",
            "programme_family": interreg.get("programme_family"),
            "programme": row.get("programme"),
            "title": "Calendar / planificare oficială a apelurilor",
            "observation_state": "PLANNED",
            "observation_label_ro": STATE_LABELS_RO["PLANNED"],
            "authority_class": row.get("authority_class"),
            "authority_url": row.get("authority_url"),
            "observed_at": row.get("observed_at") or interreg.get("fetched_at"),
            "source_health": row.get("transport_health"),
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "open_confirmation_state": "NOT_CONFIRMED_PLANNED_ONLY",
            "missing_for_open_confirmation": _missing_for_open(interreg.get("missing_for_open_call_confirmation")),
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
        })

    if not cards:
        raise ValueError("future programming projection has no PROGRAMMING/PLANNED observations")

    cards.sort(key=lambda item: (item["source_family"], item["card_id"]))
    output: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "surface": SURFACE,
        "surface_state": "PREVIEW_READ_ONLY_NOT_PUBLISHED",
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "generated_from": {
            "eea_run_id": eea.get("run_id"),
            "eea_fetched_at": eea.get("fetched_at"),
            "eea_semantic_fingerprint": eea.get("semantic_fingerprint"),
            "interreg_run_id": interreg.get("run_id"),
            "interreg_fetched_at": interreg.get("fetched_at"),
            "interreg_semantic_fingerprint": interreg.get("semantic_fingerprint"),
        },
        "card_count": len(cards),
        "allowed_observation_states": sorted(ALLOWED_STATES),
        "open_upcoming_separation": "STRICT",
        "material_change_claimed": False,
        "semantic_reconciliation_present": False,
        "semantic_reconciliation_required_before_material_change": True,
        "reader_explanation_ro": (
            "Această suprafață arată programare și planificare oficială, nu apeluri deschise. "
            "Un element poate deveni apel confirmat numai după identificator exact, recitirea endpointului oficial curent, "
            "reconciliere semantică pe aceeași identitate și admitere materială pe câmpuri."
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
    output["semantic_fingerprint"] = sha256_json({
        "surface": output["surface"],
        "generated_from": output["generated_from"],
        "cards": cards,
        "material_change_claimed": False,
    })
    validate_projection(output)
    return output


def validate_projection(output: Mapping[str, Any]) -> None:
    if output.get("schema") != SCHEMA or output.get("parser_version") != PARSER_VERSION:
        raise ValueError("future programming projection schema/parser drift")
    if output.get("surface") != SURFACE or output.get("surface_state") != "PREVIEW_READ_ONLY_NOT_PUBLISHED":
        raise ValueError("future programming projection surface drift")
    if output.get("seo_indexing_state") != "NOINDEX_PREVIEW_ONLY":
        raise ValueError("future programming projection SEO boundary drift")
    _require_false_flags(output, label="future programming projection")
    if output.get("open_upcoming_separation") != "STRICT":
        raise ValueError("future programming projection OPEN/UPCOMING separation weakened")
    if output.get("material_change_claimed") is not False:
        raise ValueError("future programming projection claimed a material change without reconciliation")
    if output.get("semantic_reconciliation_present") is not False:
        raise ValueError("future programming projection unexpectedly claims reconciliation")
    if output.get("semantic_reconciliation_required_before_material_change") is not True:
        raise ValueError("future programming projection reconciliation gate weakened")
    cards = output.get("cards")
    if not isinstance(cards, list) or not cards or output.get("card_count") != len(cards):
        raise ValueError("future programming projection card inventory mismatch")
    seen: set[str] = set()
    for card in cards:
        if not isinstance(card, Mapping):
            raise ValueError("future programming card must be an object")
        card_id = str(card.get("card_id") or "")
        if not card_id or card_id in seen:
            raise ValueError("future programming card id missing/duplicate")
        seen.add(card_id)
        if card.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{card_id}: forbidden observation state")
        _require_false_flags(card, label=f"future programming card {card_id}")
        if card.get("semantic_reconciliation_present") is not False:
            raise ValueError(f"{card_id}: card cannot claim semantic reconciliation")
        if card.get("semantic_reconciliation_required_before_material_change") is not True:
            raise ValueError(f"{card_id}: reconciliation gate weakened")
        missing = set(card.get("missing_for_open_confirmation") or [])
        if not REQUIRED_MISSING_FOR_OPEN.issubset(missing):
            raise ValueError(f"{card_id}: missing-for-open contract weakened")
        if card.get("open_confirmation_state") not in {
            "NOT_CONFIRMED_PROGRAMMING_ONLY",
            "NOT_CONFIRMED_PLANNED_ONLY",
        }:
            raise ValueError(f"{card_id}: open confirmation state drift")
    expected = sha256_json({
        "surface": output["surface"],
        "generated_from": output["generated_from"],
        "cards": cards,
        "material_change_claimed": False,
    })
    if output.get("semantic_fingerprint") != expected:
        raise ValueError("future programming projection semantic fingerprint mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only PARTENER.EU future-programming preview projection.")
    parser.add_argument("--eea", type=Path, required=True)
    parser.add_argument("--interreg-calls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    eea = json.loads(args.eea.read_text(encoding="utf-8"))
    interreg = json.loads(args.interreg_calls.read_text(encoding="utf-8"))
    output = project(eea, interreg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
