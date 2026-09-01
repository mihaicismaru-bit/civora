#!/usr/bin/env python3
"""Read-only, NOINDEX product projection for admitted competitive/cascading calls.

This projection is deliberately not a publication surface. It consumes one exact
Funding & Tenders competitive-call evidence object plus its STATUS_ONLY material
admission receipt and emits a deterministic internal preview. Only the admitted
OPEN status may appear as a confirmed material fact. Deadline, budget,
eligibility and participation remain withheld until their own admission gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping

import creative_europe_ft_competitive_admission as admission
import creative_europe_ft_competitive_exact as exact

PROJECTION_ID = "CREATIVE_EUROPE_COMPETITIVE_PRODUCT_PROJECTION_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_COMPETITIVE_PRODUCT_PROJECTION_V1"
OBSERVATION_STATE = "INTERNAL_NOINDEX_STATUS_ONLY_PRODUCT_PREVIEW"
CONFIDENCE = "HIGH_STATUS_ONLY"
ROBOTS = "noindex,nofollow,noarchive,nosnippet"
WITHHELD_FIELDS = ("deadline", "budget", "eligibility", "participation")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_projection(exact_evidence: Mapping[str, Any], admission_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Build an internal preview without widening the material-admission scope."""
    exact.validate_exact_evidence(exact_evidence)
    admission.validate_admission(admission_receipt)

    exact_sha = _sha(dict(exact_evidence))
    identity = str(exact_evidence.get("identity_key") or "")
    cid = exact.validate_competitive_id(str(exact_evidence.get("competitive_call_id") or ""))
    parent = exact.validate_reference(str(exact_evidence.get("parent_reference") or ""))

    if admission_receipt.get("identity_key") != identity:
        raise ValueError("competitive product projection identity mismatch")
    if admission_receipt.get("competitive_call_id") != cid:
        raise ValueError("competitive product projection id mismatch")
    if admission_receipt.get("parent_reference") != parent:
        raise ValueError("competitive product projection parent mismatch")
    if admission_receipt.get("exact_evidence_sha256") != exact_sha:
        raise ValueError("competitive product projection admission does not bind exact evidence")
    if admission_receipt.get("authority_url") != exact_evidence.get("authority_url"):
        raise ValueError("competitive product projection authority mismatch")
    if admission_receipt.get("authority_url_verified") is not True or exact_evidence.get("authority_url_verified") is not True:
        raise ValueError("competitive product projection requires verified authority")
    if admission_receipt.get("material_admission_scope") != "STATUS_ONLY":
        raise ValueError("competitive product projection requires STATUS_ONLY admission")
    if admission_receipt.get("status_fact_authorized") is not True or admission_receipt.get("open_call_authorized") is not True:
        raise ValueError("competitive product projection requires admitted OPEN status")
    if admission_receipt.get("admitted_status") != "OPEN_CALL":
        raise ValueError("competitive product projection current admitted status is not OPEN")
    if admission_receipt.get("admitted_status_label") != exact_evidence.get("status_label"):
        raise ValueError("competitive product projection status label mismatch")
    for key in ("deadline_authorized", "budget_authorized", "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized"):
        if admission_receipt.get(key) is not False:
            raise ValueError(f"competitive product projection received broadened admission: {key}")

    raw_title = str(exact_evidence.get("title_candidate") or "").strip()
    display_title = raw_title or f"Competitive/cascading call {cid}"

    projection: dict[str, Any] = {
        "schema": SCHEMA,
        "projection_id": PROJECTION_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "opportunity_class": "COMPETITIVE_CASCADING_CALL",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "observation_state": OBSERVATION_STATE,
        "identity_key": identity,
        "competitive_call_id": cid,
        "parent_reference": parent,
        "display_title": display_title,
        "display_title_source": "EXACT_FUNDING_TENDERS_IDENTITY_METADATA_NON_MATERIAL",
        "authority_url": exact_evidence.get("authority_url"),
        "authority_url_verified": True,
        "status": "OPEN_CALL",
        "status_label": admission_receipt.get("admitted_status_label"),
        "status_fact_authorized": True,
        "confirmed_material_fields": ["status"],
        "withheld_material_fields": list(WITHHELD_FIELDS),
        "missing_for_full_call_confirmation": [
            "field-specific deadline admission",
            "field-specific budget admission",
            "field-specific eligibility admission",
            "field-specific participation/geography admission",
            "publication review",
            "distribution change gate",
        ],
        "confidence": CONFIDENCE,
        "confidence_basis": [
            "exact Funding & Tenders competitive-call authority URL verified",
            "current structured status resolved from official F&T evidence",
            "same-identity semantic reconciliation passed",
            "STATUS_ONLY material admission passed",
        ],
        "observed_at": exact_evidence.get("fetched_at"),
        "admitted_at": admission_receipt.get("admitted_at"),
        "exact_run_id": exact_evidence.get("run_id"),
        "authority_chain": {
            "programme": "Creative Europe",
            "parent_topic_reference": parent,
            "downstream_opportunity_identity": identity,
            "exact_authority_url": exact_evidence.get("authority_url"),
        },
        "reader_explanation": {
            "ro": "Apel competitiv/cascading downstream. Statutul DESCHIS este confirmat din sursa oficiala curenta; termenul, bugetul si eligibilitatea nu sunt inca admise ca fapte materiale PARTENER.EU.",
            "en": "Downstream competitive/cascading call. OPEN status is confirmed from the current official source; deadline, budget and eligibility are not yet admitted as PARTENER.EU material facts.",
        },
        "surface_policy": {
            "preview_only": True,
            "reader_visibility": "INTERNAL_PREVIEW_ONLY",
            "robots": ROBOTS,
            "indexable": False,
            "canonical_route_enabled": False,
            "homepage_inclusion": False,
            "search_index_inclusion": False,
            "ask_partener_inclusion": False,
            "sitemap_inclusion": False,
            "structured_data_inclusion": False,
        },
        "admission_binding": {
            "exact_evidence_sha256": exact_sha,
            "admission_receipt_sha256": _sha(dict(admission_receipt)),
            "admission_fingerprint": admission_receipt.get("admission_fingerprint"),
            "reconciliation_sha256": admission_receipt.get("reconciliation_sha256"),
            "reconciliation_fingerprint": admission_receipt.get("reconciliation_fingerprint"),
        },
        "material_fact_use": True,
        "material_fact_use_scope": ["status"],
        "open_call_authorized": True,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "participation_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    projection["projection_fingerprint"] = _sha({
        "identity_key": identity,
        "status": projection["status"],
        "authority_url": projection["authority_url"],
        "observed_at": projection["observed_at"],
        "exact_evidence_sha256": exact_sha,
        "admission_receipt_sha256": projection["admission_binding"]["admission_receipt_sha256"],
        "surface_policy": projection["surface_policy"],
    })
    validate_projection(projection)
    return projection


def validate_projection(projection: Mapping[str, Any]) -> None:
    if projection.get("schema") != SCHEMA or projection.get("projection_id") != PROJECTION_ID:
        raise ValueError("competitive product projection identity drift")
    if projection.get("source_family") != "EU_DIRECT" or projection.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("competitive product projection programme drift")
    if projection.get("opportunity_class") != "COMPETITIVE_CASCADING_CALL":
        raise ValueError("competitive product projection opportunity-class drift")
    cid = exact.validate_competitive_id(str(projection.get("competitive_call_id") or ""))
    parent = exact.validate_reference(str(projection.get("parent_reference") or ""))
    if projection.get("identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{cid}":
        raise ValueError("competitive product projection identity-key drift")
    if projection.get("authority_url") != exact.competitive_url(cid) or projection.get("authority_url_verified") is not True:
        raise ValueError("competitive product projection authority drift")
    if parent != str(projection.get("parent_reference") or "").upper():
        raise ValueError("competitive product projection parent drift")
    if projection.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("competitive product projection state drift")
    if projection.get("status") != "OPEN_CALL" or projection.get("status_fact_authorized") is not True:
        raise ValueError("competitive product projection status drift")
    if projection.get("confirmed_material_fields") != ["status"]:
        raise ValueError("competitive product projection widened confirmed fields")
    if set(projection.get("withheld_material_fields") or []) != set(WITHHELD_FIELDS):
        raise ValueError("competitive product projection withheld-field drift")
    if projection.get("material_fact_use") is not True or projection.get("material_fact_use_scope") != ["status"]:
        raise ValueError("competitive product projection material-use scope drift")
    if projection.get("open_call_authorized") is not True:
        raise ValueError("competitive product projection lost admitted OPEN status")
    for key in ("deadline_authorized", "budget_authorized", "eligibility_authorized", "participation_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized"):
        if projection.get(key) is not False:
            raise ValueError(f"competitive product projection over-authorized: {key}")
    surface = projection.get("surface_policy") or {}
    if surface.get("preview_only") is not True or surface.get("reader_visibility") != "INTERNAL_PREVIEW_ONLY":
        raise ValueError("competitive product projection reader visibility drift")
    if surface.get("robots") != ROBOTS or surface.get("indexable") is not False:
        raise ValueError("competitive product projection NOINDEX policy drift")
    for key in ("canonical_route_enabled", "homepage_inclusion", "search_index_inclusion", "ask_partener_inclusion", "sitemap_inclusion", "structured_data_inclusion"):
        if surface.get(key) is not False:
            raise ValueError(f"competitive product projection escaped preview boundary: {key}")
    if projection.get("publication_effect") != "NONE" or projection.get("canonical_corpus_mutation") is not False:
        raise ValueError("competitive product projection crossed publication boundary")
    binding = projection.get("admission_binding") or {}
    for key in ("exact_evidence_sha256", "admission_receipt_sha256", "admission_fingerprint", "reconciliation_sha256", "reconciliation_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(binding.get(key) or "")):
            raise ValueError(f"competitive product projection binding hash invalid: {key}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(projection.get("projection_fingerprint") or "")):
        raise ValueError("competitive product projection fingerprint invalid")

    serialized = json.dumps(dict(projection), ensure_ascii=False, sort_keys=True)
    # Unadmitted candidate values must never leak into the preview payload.
    for forbidden in ("deadline_candidate", "budget_candidate", "withheld_material_candidates"):
        if forbidden in serialized:
            raise ValueError(f"competitive product projection leaked withheld candidate value: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact", type=pathlib.Path, required=True)
    parser.add_argument("--admission", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    exact_evidence = json.loads(args.exact.read_text(encoding="utf-8"))
    admission_receipt = json.loads(args.admission.read_text(encoding="utf-8"))
    projection = build_projection(exact_evidence, admission_receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "identity_key": projection["identity_key"],
        "status": projection["status"],
        "confirmed_material_fields": projection["confirmed_material_fields"],
        "robots": projection["surface_policy"]["robots"],
        "canonical_route_enabled": projection["surface_policy"]["canonical_route_enabled"],
        "publish_authorized": projection["publish_authorized"],
        "distribution_authorized": projection["distribution_authorized"],
        "call_alert_authorized": projection["call_alert_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
