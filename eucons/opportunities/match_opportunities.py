#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "matching_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(values: list[Any]) -> list[str]:
    return sorted({fold(value) for value in values if fold(value)})


def validate_profile(profile: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    allowed = set(contract["input"]["allowed_profile_fields"])
    forbidden = set(contract["input"]["pii_fields_forbidden"])
    unknown = set(profile) - allowed
    if unknown:
        raise ValueError(f"unsupported profile fields: {sorted(unknown)}")
    present_forbidden = set(profile) & forbidden
    if present_forbidden:
        raise ValueError(f"PII fields forbidden in E10: {sorted(present_forbidden)}")
    if not profile.get("profile_id"):
        raise ValueError("profile_id required")
    normalized = dict(profile)
    for field in contract["input"]["list_fields"]:
        value = profile.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"{field} must be a list")
        normalized[field] = tokens(value)
    if profile.get("requested_grant_eur") is not None:
        amount = profile["requested_grant_eur"]
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError("requested_grant_eur must be a positive number")
        normalized["requested_grant_eur"] = float(amount)
    return normalized


def walk_pairs(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield path, item
            yield from walk_pairs(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_pairs(item, f"{prefix}[{index}]")


def extract_activity_codes(material: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for path, value in walk_pairs(material):
        key = path.lower()
        if "activity_code" not in key and "caen" not in key:
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            for match in re.findall(r"(?:caen\s*)?(\d{2,4})", fold(candidate)):
                found.add(match)
    return found


def extract_verified_grant_cap(material: dict[str, Any]) -> float | None:
    candidates: list[float] = []
    for path, value in walk_pairs(material.get("grant") or {}):
        key = path.lower()
        if not any(marker in key for marker in ("maximum_eur", "cap_eur_per_beneficiary", "max_eur")):
            continue
        if isinstance(value, (int, float)) and value > 0:
            candidates.append(float(value))
    return max(candidates) if candidates else None


def text_blob(record: dict[str, Any]) -> str:
    public = {
        "title": record.get("title"),
        "programme": record.get("programme"),
        "code": record.get("code"),
        "material_facts": record.get("material_facts") or {},
    }
    return fold(json.dumps(public, ensure_ascii=False, sort_keys=True))


def matched_terms(terms: list[str], blob: str) -> list[str]:
    return [term for term in terms if term and term in blob]


def score_record(record: dict[str, Any], profile: dict[str, Any], bridge: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    held = contract["outputs"]["held"]
    semantics = contract["score_semantics"]
    provenance = record.get("provenance") or {}
    base = {
        "opportunity_id": record.get("id"),
        "title": record.get("title"),
        "programme": record.get("programme"),
        "score": 0,
        "score_semantics": semantics,
        "confidence": "LOW",
        "state": held,
        "explanations": [],
        "hard_exclusion_reasons": [],
        "source_provenance": provenance,
    }
    guards = contract["source_guards"]
    if bridge.get("bridge_state") != guards["required_bridge_state"]:
        base["explanations"] = [f"bridge_state={bridge.get('bridge_state')} prevents matching"]
        return base
    if record.get("commercial_state") != guards["required_record_state"] or (guards["require_actionable"] and not record.get("actionable")):
        base["explanations"] = ["opportunity is not in a fresh actionable verified state"]
        return base

    material = record.get("material_facts") or {}
    explicit_codes = extract_activity_codes(material)
    profile_codes = {re.sub(r"\D", "", code) for code in profile.get("activity_codes", []) if re.sub(r"\D", "", code)}
    if explicit_codes and profile_codes and not (explicit_codes & profile_codes):
        base["state"] = contract["outputs"]["excluded"]
        base["hard_exclusion_reasons"] = [f"activity code mismatch: profile={sorted(profile_codes)} source={sorted(explicit_codes)}"]
        base["explanations"] = ["A verified activity-code rule conflicts with the supplied profile."]
        return base

    requested = profile.get("requested_grant_eur")
    verified_cap = extract_verified_grant_cap(material)
    if requested is not None and verified_cap is not None and requested > verified_cap:
        base["state"] = contract["outputs"]["excluded"]
        base["hard_exclusion_reasons"] = [f"requested_grant_eur={requested:g} exceeds verified_cap_eur={verified_cap:g}"]
        base["explanations"] = ["The requested grant exceeds a verified source cap."]
        return base

    blob = text_blob(record)
    weights = contract["weights"]
    score = 0
    dimensions = 0
    explanations: list[str] = []

    if explicit_codes and profile_codes and (explicit_codes & profile_codes):
        score += int(weights["activity_code"])
        dimensions += 1
        explanations.append(f"verified activity-code overlap: {', '.join(sorted(explicit_codes & profile_codes))}")

    investment_hits = matched_terms(profile.get("investment_terms", []), blob)
    if investment_hits:
        score += min(int(weights["investment_terms_max"]), 10 * len(investment_hits))
        dimensions += 1
        explanations.append("investment terms found in verified opportunity facts: " + ", ".join(investment_hits))

    organization_hits = matched_terms(profile.get("organization_labels", []), blob)
    if organization_hits:
        score += min(int(weights["organization_terms_max"]), 10 * len(organization_hits))
        dimensions += 1
        explanations.append("organization terms found in verified opportunity facts: " + ", ".join(organization_hits))

    region_hits = matched_terms(profile.get("region_terms", []), blob)
    if region_hits:
        score += min(int(weights["region_terms_max"]), 5 * len(region_hits))
        dimensions += 1
        explanations.append("region terms found in verified opportunity facts: " + ", ".join(region_hits))

    if requested is not None and verified_cap is not None and requested <= verified_cap:
        score += int(weights["grant_within_verified_cap"])
        dimensions += 1
        explanations.append(f"requested grant is within verified cap ({verified_cap:g} EUR)")

    score = min(100, score)
    thresholds = contract["thresholds"]
    state = contract["outputs"]["candidate"] if score >= int(thresholds["match_candidate_min"]) else contract["outputs"]["insufficient"]
    if score >= int(thresholds["high_confidence_min_score"]) and dimensions >= int(thresholds["high_confidence_min_positive_dimensions"]):
        confidence = "HIGH"
    elif score >= int(thresholds["medium_confidence_min_score"]) and dimensions >= int(thresholds["medium_confidence_min_positive_dimensions"]):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    base.update({
        "score": score,
        "confidence": confidence,
        "state": state,
        "explanations": explanations or ["No sufficiently specific verified matching signal was found; more project data is required."],
    })
    return base


def match(profile: dict[str, Any], bridge: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_profile(profile, contract)
    results = [score_record(record, normalized, bridge, contract) for record in bridge.get("opportunities") or []]
    results.sort(key=lambda row: (-row["score"], str(row.get("opportunity_id") or "")))
    return {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "profile_id": normalized["profile_id"],
        "score_semantics": contract["score_semantics"],
        "bridge_state": bridge.get("bridge_state"),
        "summary": {
            "evaluated": len(results),
            "candidates": sum(row["state"] == contract["outputs"]["candidate"] for row in results),
            "excluded_known_rule": sum(row["state"] == contract["outputs"]["excluded"] for row in results),
            "held_source_state": sum(row["state"] == contract["outputs"]["held"] for row in results),
            "requires_data": sum(row["state"] == contract["outputs"]["insufficient"] for row in results),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = match(load_json(Path(args.profile)), load_json(Path(args.projection)), load_json(Path(args.contract)))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
