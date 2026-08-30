#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PARSER_VERSION = "INTERREG_TERRITORIAL_FIT_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_territorial_fit_registry.json"
MISSING_FOR_CALL_CONFIRMATION = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "call_specific_applicant_and_geography_eligibility",
    "semantic_reconciliation",
]


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_value.lower().replace("-", " ").split())


def _registry_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0":
        raise ValueError("unsupported territorial-fit registry schema")
    programmes = data.get("programmes") or []
    if not programmes:
        raise ValueError("territorial-fit registry is empty")
    ids = [row.get("id") for row in programmes]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("duplicate or empty territorial-fit programme id")
    return data, _registry_hash(raw)


def resolve(county: str, *, run_id: str, registry_path: Path = DEFAULT_REGISTRY, observed_at: str | None = None) -> dict[str, Any]:
    if not county or not county.strip():
        raise ValueError("county is required")
    registry, registry_sha256 = load_registry(registry_path)
    county_key = _fold(county)
    now = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    fits: list[dict[str, Any]] = []
    non_fits: list[dict[str, Any]] = []
    for programme in registry["programmes"]:
        scope = programme.get("romania_scope")
        eligible = programme.get("eligible_territories_romania") or []
        if scope == "NATIONAL_ROMANIA":
            territorial_fit = True
            matched = "ALL_ROMANIA"
        elif scope == "SUBNATIONAL_COUNTIES":
            match = next((item for item in eligible if _fold(item) == county_key), None)
            territorial_fit = match is not None
            matched = match
        else:
            raise ValueError(f"unsupported romania_scope for {programme.get('id')}: {scope}")

        row = {
            "programme_id": programme["id"],
            "source_id": programme["source_id"],
            "programme": programme["programme"],
            "programme_family": programme["programme_family"],
            "authority_class": programme["authority_class"],
            "observation_state": programme["observation_state"],
            "evidence_url": programme["evidence_url"],
            "evidence_checked_date": programme["evidence_checked_date"],
            "romania_scope": scope,
            "matched_territory": matched,
            "territorial_fit": territorial_fit,
            "call_specific_geography_required": bool(programme.get("call_specific_geography_required", True)),
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "missing_for_call_confirmation": list(MISSING_FOR_CALL_CONFIRMATION),
        }
        (fits if territorial_fit else non_fits).append(row)

    return {
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now,
        "registry_sha256": registry_sha256,
        "source_family": "INTERREG",
        "observation_state": "TERRITORIAL_PROGRAMME_FIT",
        "authority_class": "OFFICIAL_PROGRAMME_GEOGRAPHY",
        "input": {"country": "Romania", "county": county},
        "fit_count": len(fits),
        "non_fit_count": len(non_fits),
        "fits": fits,
        "non_fits": non_fits,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "note": "Programme territorial fit only; exact-call applicant/geography rules remain authoritative and require semantic reconciliation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve Romania county-level Interreg programme territorial fit without authorizing call facts.")
    parser.add_argument("--county", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = resolve(args.county, run_id=args.run_id, registry_path=args.registry)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
