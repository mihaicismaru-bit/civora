#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import interreg_territorial_fit as territorial_fit

PARSER_VERSION = "INTERREG_APPLICANT_PARTNER_FIT_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_applicant_partner_fit_registry.json"
DEFAULT_TERRITORIAL_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_territorial_fit_registry.json"

MISSING_FOR_CALL_CONFIRMATION = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "call_specific_applicant_geography_partnership_and_role_rules",
    "semantic_reconciliation",
]

APPLICANT_ALIASES = {
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

KNOWN_TYPES = {
    "PUBLIC_AUTHORITY",
    "PUBLIC_INSTITUTION",
    "PUBLIC_LAW_BODY",
    "NGO_NONPROFIT",
    "EDUCATION_RESEARCH",
    "EGTC",
    "PRIVATE_BODY",
    "INTERNATIONAL_ORGANISATION",
    "OTHER_RELEVANT_ORGANISATION",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_value.lower().replace("-", " ").replace("_", " ").split())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_applicant_type(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("applicant_type is required")
    raw = value.strip().upper().replace("-", "_").replace(" ", "_")
    if raw in KNOWN_TYPES:
        return raw
    alias = APPLICANT_ALIASES.get(_fold(value))
    if alias:
        return alias
    raise ValueError(f"unsupported applicant_type: {value}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0":
        raise ValueError("unsupported applicant-partner fit registry schema")
    programmes = data.get("programmes") or []
    if not programmes:
        raise ValueError("applicant-partner fit registry is empty")
    ids = [row.get("id") for row in programmes]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("duplicate or empty applicant-partner programme id")
    return data, _sha256(raw)


def _signal_state(observation_state: str, applicant_type: str, supported: set[str]) -> tuple[str, int]:
    if applicant_type in supported:
        if observation_state == "PROGRAMME_APPLICANT_SIGNAL":
            return "SUPPORTED_PROGRAMME_SIGNAL", 30
        if observation_state == "RECENT_CALL_APPLICANT_SIGNAL":
            return "SUPPORTED_RECENT_CALL_SIGNAL", 20
        raise ValueError(f"unsupported evidence state carrying applicant types: {observation_state}")
    if not supported:
        return "INSUFFICIENT_EVIDENCE", 0
    return "NO_SUPPORTING_SIGNAL", 0


def resolve(
    county: str,
    applicant_type: str,
    *,
    run_id: str,
    has_international_partner: bool = False,
    registry_path: Path = DEFAULT_REGISTRY,
    territorial_registry_path: Path = DEFAULT_TERRITORIAL_REGISTRY,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_type = normalize_applicant_type(applicant_type)
    registry, registry_sha256 = load_registry(registry_path)
    now = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    territorial = territorial_fit.resolve(
        county,
        run_id=run_id,
        registry_path=territorial_registry_path,
        observed_at=now,
    )
    by_id = {row["id"]: row for row in registry["programmes"]}
    territorial_ids = {row["programme_id"] for row in territorial["fits"] + territorial["non_fits"]}
    if territorial_ids != set(by_id):
        missing = sorted(territorial_ids ^ set(by_id))
        raise ValueError(f"applicant/territorial registry programme drift: {missing}")

    ranked: list[dict[str, Any]] = []
    non_fits: list[dict[str, Any]] = []
    for territorial_row in territorial["fits"] + territorial["non_fits"]:
        programme = by_id[territorial_row["programme_id"]]
        supported = set(programme.get("supported_applicant_types") or [])
        unknown_types = supported - KNOWN_TYPES
        if unknown_types:
            raise ValueError(f"unknown supported applicant type for {programme['id']}: {sorted(unknown_types)}")
        signal_state, applicant_points = _signal_state(
            programme["observation_state"], normalized_type, supported
        )
        territorial_ok = bool(territorial_row["territorial_fit"])
        partner_points = 10 if territorial_ok and has_international_partner else 0
        market_fit_score = (60 if territorial_ok else 0) + applicant_points + partner_points
        row = {
            "programme_id": programme["id"],
            "source_id": programme["source_id"],
            "programme": programme["programme"],
            "programme_family": territorial_row["programme_family"],
            "authority_class": programme["authority_class"],
            "observation_state": programme["observation_state"],
            "evidence_url": programme["evidence_url"],
            "evidence_checked_date": programme["evidence_checked_date"],
            "signal_basis": programme["signal_basis"],
            "territorial_fit": territorial_ok,
            "matched_territory": territorial_row["matched_territory"],
            "applicant_type": normalized_type,
            "applicant_signal_state": signal_state,
            "supported_applicant_types_observed": sorted(supported),
            "partnership_signal": programme["partnership_signal"],
            "international_partner_declared": bool(has_international_partner),
            "call_specific_applicant_rules_required": bool(programme.get("call_specific_applicant_rules_required", True)),
            "market_fit_score": market_fit_score,
            "score_components": {
                "territorial_programme_fit": 60 if territorial_ok else 0,
                "applicant_signal": applicant_points,
                "international_partner_readiness": partner_points,
            },
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "missing_for_call_confirmation": list(MISSING_FOR_CALL_CONFIRMATION),
        }
        (ranked if territorial_ok else non_fits).append(row)

    ranked.sort(key=lambda row: (-row["market_fit_score"], row["programme_id"]))
    non_fits.sort(key=lambda row: row["programme_id"])
    return {
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now,
        "registry_sha256": registry_sha256,
        "territorial_registry_sha256": territorial["registry_sha256"],
        "source_family": "INTERREG",
        "observation_state": "APPLICANT_PARTNER_MARKET_FIT",
        "authority_class": "OFFICIAL_PROGRAMME_AND_RECENT_CALL_SIGNAL",
        "input": {
            "country": "Romania",
            "county": county,
            "applicant_type": normalized_type,
            "has_international_partner": bool(has_international_partner),
        },
        "fit_count": len(ranked),
        "ranked_programme_fits": ranked,
        "non_territorial_fits": non_fits,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "missing_for_call_confirmation": list(MISSING_FOR_CALL_CONFIRMATION),
        "note": "Score prioritizes programme discovery only. It is not an eligibility decision and cannot authorize OPEN or any material call fact.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank Romania-relevant Interreg programmes using territorial and applicant/partner signals without authorizing call facts."
    )
    parser.add_argument("--county", required=True)
    parser.add_argument("--applicant-type", required=True)
    parser.add_argument("--has-international-partner", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--territorial-registry", type=Path, default=DEFAULT_TERRITORIAL_REGISTRY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = resolve(
        args.county,
        args.applicant_type,
        run_id=args.run_id,
        has_international_partner=args.has_international_partner,
        registry_path=args.registry,
        territorial_registry_path=args.territorial_registry,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
