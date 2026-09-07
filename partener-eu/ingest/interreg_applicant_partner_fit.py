#!/usr/bin/env python3
"""Non-authorizing applicant/partner market-fit ranking for Romania-relevant Interreg programmes.

This module consumes an already-acquired, validated Interreg Romania programme/territory
matrix receipt. It never performs call discovery and never converts programme or historical
call signals into current applicant eligibility. The score is prioritisation research only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import unicodedata
from typing import Any, Mapping

import interreg_romania_programme_matrix as programme_matrix

SCHEMA = "PARTENER_EU_INTERREG_APPLICANT_PARTNER_FIT_V2"
PARSER_VERSION = "INTERREG_APPLICANT_PARTNER_FIT_V2"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_ROMANIA_RELEVANT_2021_2027"
AUTHORITY_CLASS = "OFFICIAL_PROGRAMME_AND_HISTORICAL_CALL_MARKET_SIGNAL"
OBSERVATION_STATE = "APPLICANT_PARTNER_MARKET_FIT_NON_AUTHORIZING"
ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_applicant_partner_fit_registry.json"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)

MISSING_FOR_OPEN_CONFIRMATION = (
    "exact_call_or_topic_identifier",
    "fresh_current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "call_specific_applicant_geography_partnership_and_role_rules",
    "same_identity_semantic_reconciliation",
    "field_scoped_material_admission",
)

KNOWN_TYPES = {
    "PUBLIC_AUTHORITY", "PUBLIC_INSTITUTION", "PUBLIC_LAW_BODY", "NGO_NONPROFIT",
    "EDUCATION_RESEARCH", "EGTC", "PRIVATE_BODY", "INTERNATIONAL_ORGANISATION",
    "OTHER_RELEVANT_ORGANISATION",
}

ALIASES = {
    "public authority": "PUBLIC_AUTHORITY",
    "authority": "PUBLIC_AUTHORITY",
    "local authority": "PUBLIC_AUTHORITY",
    "regional authority": "PUBLIC_AUTHORITY",
    "national authority": "PUBLIC_AUTHORITY",
    "municipality": "PUBLIC_AUTHORITY",
    "county council": "PUBLIC_AUTHORITY",
    "ministry": "PUBLIC_AUTHORITY",
    "public institution": "PUBLIC_INSTITUTION",
    "public hospital": "PUBLIC_INSTITUTION",
    "public school": "PUBLIC_INSTITUTION",
    "public law body": "PUBLIC_LAW_BODY",
    "body governed by public law": "PUBLIC_LAW_BODY",
    "ngo": "NGO_NONPROFIT",
    "nonprofit": "NGO_NONPROFIT",
    "non profit": "NGO_NONPROFIT",
    "association": "NGO_NONPROFIT",
    "foundation": "NGO_NONPROFIT",
    "university": "EDUCATION_RESEARCH",
    "research institute": "EDUCATION_RESEARCH",
    "education research": "EDUCATION_RESEARCH",
    "egtc": "EGTC",
    "company": "PRIVATE_BODY",
    "private company": "PRIVATE_BODY",
    "private body": "PRIVATE_BODY",
    "sme": "PRIVATE_BODY",
    "international organisation": "INTERNATIONAL_ORGANISATION",
    "international organization": "INTERNATIONAL_ORGANISATION",
    "other relevant organisation": "OTHER_RELEVANT_ORGANISATION",
    "other relevant organization": "OTHER_RELEVANT_ORGANISATION",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_value.casefold().replace("-", " ").replace("_", " ").split())


def normalize_applicant_type(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("applicant_type is required")
    raw = value.strip().upper().replace("-", "_").replace(" ", "_")
    if raw in KNOWN_TYPES:
        return raw
    alias = ALIASES.get(fold(value))
    if alias:
        return alias
    raise ValueError(f"unsupported applicant_type: {value}")


def load_registry(path: pathlib.Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "2.0":
        raise ValueError("unsupported applicant/partner registry schema")
    policy = data.get("policy") or {}
    if policy.get("scope") != "PROGRAMME_APPLICANT_PARTNER_MARKET_INTELLIGENCE_ONLY":
        raise ValueError("applicant/partner registry policy drift")
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"applicant/partner registry attempted authorization: {flag}")
    rows = data.get("programmes") or []
    if not rows:
        raise ValueError("applicant/partner registry is empty")
    ids = [str(row.get("id") or "") for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("duplicate or empty applicant/partner programme id")
    for row in rows:
        if row.get("authority_class") != "T1_OFFICIAL_PROGRAMME":
            raise ValueError(f"applicant signal authority drift: {row.get('id')}")
        if row.get("observation_state") not in {
            "PROGRAMME_APPLICANT_SIGNAL", "HISTORICAL_CALL_APPLICANT_SIGNAL", "APPLICANT_SIGNAL_INSUFFICIENT",
        }:
            raise ValueError(f"unsupported applicant signal state: {row.get('id')}")
        supported = set(row.get("supported_applicant_types") or [])
        if supported - KNOWN_TYPES:
            raise ValueError(f"unknown applicant type signal: {row.get('id')}")
        if row.get("observation_state") == "APPLICANT_SIGNAL_INSUFFICIENT" and supported:
            raise ValueError(f"insufficient signal row cannot carry applicant types: {row.get('id')}")
        if row.get("observation_state") != "APPLICANT_SIGNAL_INSUFFICIENT" and not supported:
            raise ValueError(f"supported signal row requires applicant types: {row.get('id')}")
        if row.get("call_specific_applicant_rules_required") is not True:
            raise ValueError(f"call-specific applicant rules must remain required: {row.get('id')}")
        if not str(row.get("evidence_url") or "").startswith("https://"):
            raise ValueError(f"non-HTTPS applicant evidence: {row.get('id')}")
    return data, sha256_bytes(raw)


def load_matrix(path: pathlib.Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    programme_matrix.validate_receipt(receipt)
    return receipt


def territory_matches(scope: list[str], county: str) -> tuple[bool, str | None]:
    if "ALL_ROMANIA" in scope:
        return True, "ALL_ROMANIA"
    wanted = fold(county)
    for territory in scope:
        if fold(str(territory)) == wanted:
            return True, str(territory)
    return False, None


def applicant_signal(state: str, applicant_type: str, supported: set[str]) -> tuple[str, int, str]:
    if applicant_type not in supported:
        if not supported:
            return "INSUFFICIENT_EVIDENCE", 0, "LOW"
        return "NO_SUPPORTING_SIGNAL", 0, "LOW"
    if state == "PROGRAMME_APPLICANT_SIGNAL":
        return "SUPPORTED_PROGRAMME_SIGNAL", 30, "HIGH"
    if state == "HISTORICAL_CALL_APPLICANT_SIGNAL":
        return "SUPPORTED_HISTORICAL_CALL_SIGNAL", 20, "MEDIUM"
    raise ValueError("applicant type carried by unsupported signal state")


def resolve(
    *,
    county: str,
    applicant_type: str,
    run_id: str,
    programme_matrix_path: pathlib.Path,
    registry_path: pathlib.Path = DEFAULT_REGISTRY,
    has_international_partner: bool = False,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    if not county or not county.strip():
        raise ValueError("county is required")
    normalized_type = normalize_applicant_type(applicant_type)
    matrix = load_matrix(programme_matrix_path)
    registry, registry_sha256 = load_registry(registry_path)
    now = fetched_at or utc_now()

    signal_by_id = {str(row["id"]): row for row in registry["programmes"]}
    matrix_by_id = {str(row["programme_id"]): row for row in matrix["programmes"]}
    if set(signal_by_id) != set(matrix_by_id):
        raise ValueError(f"applicant signal / programme matrix drift: {sorted(set(signal_by_id) ^ set(matrix_by_id))}")

    ranked: list[dict[str, Any]] = []
    non_territorial: list[dict[str, Any]] = []
    for programme_id, territory in matrix_by_id.items():
        signal = signal_by_id[programme_id]
        territory_ok, matched_territory = territory_matches(list(territory.get("romania_scope") or []), county)
        supported = set(signal.get("supported_applicant_types") or [])
        signal_state, applicant_points, confidence = applicant_signal(
            str(signal["observation_state"]), normalized_type, supported
        )
        partner_points = 10 if territory_ok and has_international_partner else 0
        score = (60 if territory_ok else 0) + applicant_points + partner_points
        row: dict[str, Any] = {
            "programme_id": programme_id,
            "programme": territory["programme"],
            "programme_family": PROGRAMME_FAMILY,
            "territorial_authority_url": territory["authority_url"],
            "territorial_source_sha256": territory["source_sha256"],
            "territorial_fit": territory_ok,
            "matched_territory": matched_territory,
            "territorial_fit_state": territory["territorial_fit_state"],
            "applicant_type": normalized_type,
            "applicant_signal_state": signal_state,
            "applicant_signal_observation_state": signal["observation_state"],
            "applicant_signal_confidence": confidence,
            "applicant_evidence_url": signal["evidence_url"],
            "applicant_evidence_checked_date": signal["evidence_checked_date"],
            "applicant_signal_basis": signal["signal_basis"],
            "supported_applicant_types_observed": sorted(supported),
            "partnership_signal": signal["partnership_signal"],
            "international_partner_declared": bool(has_international_partner),
            "call_specific_applicant_rules_required": True,
            "market_fit_score": score,
            "score_components": {
                "verified_programme_territorial_fit": 60 if territory_ok else 0,
                "non_authorizing_applicant_signal": applicant_points,
                "declared_partner_readiness": partner_points,
            },
            "market_intelligence_only": True,
            "fit_is_not_eligibility": True,
            "missing_for_open_confirmation": list(MISSING_FOR_OPEN_CONFIRMATION),
        }
        for flag in MATERIAL_FLAGS:
            row[flag] = False
        (ranked if territory_ok else non_territorial).append(row)

    ranked.sort(key=lambda row: (-int(row["market_fit_score"]), str(row["programme_id"])))
    non_territorial.sort(key=lambda row: str(row["programme_id"]))
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "run_id": run_id,
        "fetched_at": now,
        "registry_sha256": registry_sha256,
        "programme_matrix_semantic_fingerprint": matrix["semantic_fingerprint"],
        "programme_matrix_run_id": matrix["run_id"],
        "input": {
            "country": "Romania",
            "county": county,
            "applicant_type": normalized_type,
            "has_international_partner": bool(has_international_partner),
        },
        "programme_count": len(matrix_by_id),
        "fit_count": len(ranked),
        "ranked_programme_fits": ranked,
        "non_territorial_fits": non_territorial,
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN_CONFIRMATION),
        "note": "Score ranks programme discovery using verified Romania programme geography plus official programme/historical-call applicant signals. It cannot establish current-call eligibility or OPEN status.",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["semantic_fingerprint"] = sha256_json({
        "registry_sha256": registry_sha256,
        "programme_matrix_semantic_fingerprint": matrix["semantic_fingerprint"],
        "input": result["input"],
        "ranked_programme_fits": ranked,
        "non_territorial_fits": non_territorial,
    })
    validate_result(result)
    return result


def validate_result(result: Mapping[str, Any]) -> None:
    if result.get("schema") != SCHEMA or result.get("parser_version") != PARSER_VERSION:
        raise ValueError("Interreg applicant/partner fit schema/parser drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Interreg applicant/partner fit family drift")
    if result.get("authority_class") != AUTHORITY_CLASS or result.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("Interreg applicant/partner fit authority/state drift")
    if result.get("market_intelligence_only") is not True or result.get("fit_is_not_eligibility") is not True:
        raise ValueError("Interreg applicant/partner fit crossed market-intelligence boundary")
    if result.get("publication_effect") != "NONE":
        raise ValueError("Interreg applicant/partner fit attempted publication effect")
    for flag in MATERIAL_FLAGS:
        if result.get(flag) is not False:
            raise ValueError(f"Interreg applicant/partner fit attempted authorization: {flag}")
    missing = set(result.get("missing_for_open_confirmation") or [])
    if not set(MISSING_FOR_OPEN_CONFIRMATION).issubset(missing):
        raise ValueError("Interreg applicant/partner fit weakened exact-call confirmation requirements")
    rows = list(result.get("ranked_programme_fits") or []) + list(result.get("non_territorial_fits") or [])
    if len(rows) != int(result.get("programme_count") or 0):
        raise ValueError("Interreg applicant/partner fit programme count drift")
    for row in rows:
        if not 0 <= int(row.get("market_fit_score") or 0) <= 100:
            raise ValueError("Interreg applicant/partner score outside 0..100")
        if row.get("market_intelligence_only") is not True or row.get("fit_is_not_eligibility") is not True:
            raise ValueError("Interreg applicant/partner row crossed market-intelligence boundary")
        if row.get("call_specific_applicant_rules_required") is not True:
            raise ValueError("Interreg applicant/partner row weakened call-specific rules")
        for flag in MATERIAL_FLAGS:
            if row.get(flag) is not False:
                raise ValueError(f"Interreg applicant/partner row attempted authorization: {flag}")
    fingerprint = result.get("semantic_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("Interreg applicant/partner fit missing semantic fingerprint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank Romania-relevant Interreg programmes using non-authorizing applicant/partner market signals.")
    parser.add_argument("--county", required=True)
    parser.add_argument("--applicant-type", required=True)
    parser.add_argument("--has-international-partner", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--programme-matrix", type=pathlib.Path, required=True)
    parser.add_argument("--registry", type=pathlib.Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    result = resolve(
        county=args.county,
        applicant_type=args.applicant_type,
        run_id=args.run_id,
        programme_matrix_path=args.programme_matrix,
        registry_path=args.registry,
        has_international_partner=args.has_international_partner,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
