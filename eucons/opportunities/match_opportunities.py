#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "matching_contract.json"

RECEIPT_FIELDS = {
    "receipt_id",
    "opportunity_id",
    "verification_state",
    "verification_method",
    "source_product",
    "source_authority",
    "source_url",
    "source_document_sha256",
    "verified_at",
    "verified_fact_hashes",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


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
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("requested_grant_eur must be a positive number")
        normalized["requested_grant_eur"] = float(amount)
    return normalized


def _validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("engine_id") == "EUCONS_E10_OPPORTUNITY_MATCHING", "matching engine id drift")
    require(contract.get("score_semantics") == "RELEVANCE_NOT_APPROVAL_PROBABILITY", "matching score semantics drift")
    guards = contract.get("official_source_guards") or {}
    require(guards.get("partener_role") == "DISCOVERY_ONLY", "PARTENER role must remain discovery-only")
    require(guards.get("verified_state") == "VERIFIED_OFFICIAL_SOURCE", "official verified state drift")
    require(guards.get("conflict_state") == "BLOCKED_SOURCE_CONFLICT", "official conflict state drift")
    require(guards.get("verification_method") == "OFFICIAL_SOURCE_READBACK", "official verification method drift")
    require(guards.get("waiting_authority_state") == "WAITING_SOURCE", "official waiting state drift")
    require(guards.get("blocked_authority_state") == "BLOCKED_SOURCE_CONFLICT", "official blocked state drift")
    require(set(guards.get("required_candidate_fact_classes") or []) == {"status", "deadline"},
            "candidate official fact gate drift")
    required_material = {"status", "deadline", "budget", "grant", "beneficiaries", "eligibility", "scoring", "indicators", "obligations"}
    require(set(guards.get("material_fact_classes_requiring_official_binding") or []) == required_material,
            "official material-fact authority set drift")
    require("PARTENER.EU" in set(guards.get("forbidden_source_products") or []),
            "PARTENER must be forbidden as official authority")
    rules = contract.get("rules") or {}
    for key in (
        "partener_material_facts_never_authoritative_without_official_binding",
        "official_source_conflict_fails_closed",
        "missing_official_source_fails_closed",
        "no_external_fetch_or_write",
        "never_claim_eligibility_or_award_probability",
        "source_provenance_must_be_retained",
    ):
        require(rules.get(key) is True, f"matching rule failed open: {key}")


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
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            candidates.append(float(value))
    return max(candidates) if candidates else None


def text_blob(record: dict[str, Any], official_fact_classes: set[str]) -> str:
    material = record.get("material_facts") or {}
    public = {
        "title": record.get("title"),
        "programme": record.get("programme"),
        "code": record.get("code"),
        "officially_bound_material_facts": {
            key: material[key]
            for key in sorted(official_fact_classes)
            if key in material
        },
    }
    return fold(json.dumps(public, ensure_ascii=False, sort_keys=True))


def matched_terms(terms: list[str], blob: str) -> list[str]:
    return [term for term in terms if term and term in blob]


def _validate_timestamp(value: Any) -> None:
    require(isinstance(value, str) and RFC3339_UTC_Z.fullmatch(value) is not None,
            "official verified_at must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid official verified_at timestamp") from exc
    require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
            "official verified_at must resolve to UTC")


def validate_official_registry(registry: dict[str, Any] | None, contract: dict[str, Any]) -> list[dict[str, Any]]:
    if registry is None:
        return []
    require(isinstance(registry, dict), "official verification registry must be an object")
    guards = contract["official_source_guards"]
    require(set(registry) == {"schema_version", "state", "receipts"}, "official registry field drift")
    require(registry.get("schema_version") == guards["registry_schema_version"], "official registry schema drift")
    require(registry.get("state") == guards["registry_state"], "official registry state drift")
    receipts = registry.get("receipts")
    require(isinstance(receipts, list), "official registry receipts must be a list")
    allowed_fact_classes = set(guards["material_fact_classes_requiring_official_binding"])
    forbidden_products = {str(item).upper() for item in guards["forbidden_source_products"]}
    seen_ids: set[str] = set()
    safe: list[dict[str, Any]] = []
    for receipt in receipts:
        require(isinstance(receipt, dict) and set(receipt) == RECEIPT_FIELDS, "official receipt field drift")
        receipt_id = receipt.get("receipt_id")
        require(isinstance(receipt_id, str) and HEX64.fullmatch(receipt_id) is not None, "official receipt id invalid")
        require(receipt_id not in seen_ids, "duplicate official receipt id")
        seen_ids.add(receipt_id)
        opportunity_id = receipt.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "official receipt opportunity id missing")
        state = receipt.get("verification_state")
        require(state in {guards["verified_state"], guards["conflict_state"]}, "official receipt verification state invalid")
        require(receipt.get("verification_method") == guards["verification_method"], "official receipt verification method drift")
        source_product = receipt.get("source_product")
        require(isinstance(source_product, str) and source_product.strip(), "official receipt source product missing")
        require(source_product.strip().upper() not in forbidden_products, "PARTENER.EU cannot satisfy official authority")
        authority = receipt.get("source_authority")
        require(isinstance(authority, str) and authority.strip(), "official source authority missing")
        source_url = receipt.get("source_url")
        require(isinstance(source_url, str), "official source URL missing")
        parsed_url = urlparse(source_url)
        require(parsed_url.scheme == guards["source_url_scheme"] and bool(parsed_url.netloc), "official source URL must be HTTPS")
        source_document_sha = receipt.get("source_document_sha256")
        require(isinstance(source_document_sha, str) and HEX64.fullmatch(source_document_sha) is not None,
                "official source document hash invalid")
        _validate_timestamp(receipt.get("verified_at"))
        hashes = receipt.get("verified_fact_hashes")
        require(isinstance(hashes, dict), "official verified_fact_hashes must be an object")
        require(set(hashes).issubset(allowed_fact_classes), "official receipt contains unsupported fact class")
        for fact_class, digest in hashes.items():
            require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None,
                    f"official fact hash invalid for {fact_class}")
        if state == guards["verified_state"]:
            require(bool(hashes), "verified official receipt must bind at least one fact")
        safe.append(dict(receipt))
    return safe


def official_authority_for_record(
    record: dict[str, Any],
    receipts: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    guards = contract["official_source_guards"]
    opportunity_id = record.get("id")
    relevant = [row for row in receipts if row["opportunity_id"] == opportunity_id]
    if any(row["verification_state"] == guards["conflict_state"] for row in relevant):
        return {
            "state": guards["blocked_authority_state"],
            "official_fact_classes": set(),
            "official_source_count": len(relevant),
            "reason": "Official-source conflict is unresolved; no material fact is authoritative.",
        }

    material = record.get("material_facts") or {}
    fact_hashes: dict[str, str] = {}
    source_ids: set[tuple[str, str, str]] = set()
    for receipt in relevant:
        if receipt["verification_state"] != guards["verified_state"]:
            continue
        source_ids.add((receipt["source_product"], receipt["source_authority"], receipt["source_url"]))
        for fact_class, digest in receipt["verified_fact_hashes"].items():
            if fact_class not in material:
                return {
                    "state": guards["blocked_authority_state"],
                    "official_fact_classes": set(),
                    "official_source_count": len(source_ids),
                    "reason": f"Official receipt binds absent material fact: {fact_class}.",
                }
            current = canonical_hash(material[fact_class])
            if digest != current:
                return {
                    "state": guards["blocked_authority_state"],
                    "official_fact_classes": set(),
                    "official_source_count": len(source_ids),
                    "reason": f"Official-source binding conflicts with current projected {fact_class} fact.",
                }
            previous = fact_hashes.get(fact_class)
            if previous is not None and previous != digest:
                return {
                    "state": guards["blocked_authority_state"],
                    "official_fact_classes": set(),
                    "official_source_count": len(source_ids),
                    "reason": f"Official receipts conflict on {fact_class}.",
                }
            fact_hashes[fact_class] = digest

    bound = set(fact_hashes)
    required = set(guards["required_candidate_fact_classes"])
    if not required.issubset(bound):
        missing = sorted(required - bound)
        return {
            "state": guards["waiting_authority_state"],
            "official_fact_classes": bound,
            "official_source_count": len(source_ids),
            "reason": "Waiting for official-source binding of: " + ", ".join(missing) + ".",
        }
    return {
        "state": guards["verified_authority_state"],
        "official_fact_classes": bound,
        "official_source_count": len(source_ids),
        "reason": "Required status and deadline facts are bound to official-source readback.",
    }


def score_record(
    record: dict[str, Any],
    profile: dict[str, Any],
    bridge: dict[str, Any],
    contract: dict[str, Any],
    official_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    held = contract["outputs"]["held"]
    semantics = contract["score_semantics"]
    provenance = record.get("provenance") or {}
    waiting = contract["official_source_guards"]["waiting_authority_state"]
    base = {
        "opportunity_id": record.get("id"),
        "title": record.get("title"),
        "programme": record.get("programme"),
        "score": 0,
        "score_semantics": semantics,
        "confidence": "LOW",
        "state": held,
        "authority_state": waiting,
        "official_fact_classes": [],
        "official_source_count": 0,
        "explanations": [],
        "hard_exclusion_reasons": [],
        "source_provenance": provenance,
    }
    guards = contract["source_guards"]
    if bridge.get("bridge_state") != guards["required_bridge_state"]:
        base["explanations"] = [f"bridge_state={bridge.get('bridge_state')} prevents matching"]
        return base
    if record.get("commercial_state") != guards["required_record_state"] or (guards["require_actionable"] and not record.get("actionable")):
        base["explanations"] = ["opportunity is not in a fresh actionable discovery state"]
        return base

    authority = official_authority_for_record(record, official_receipts, contract)
    base["authority_state"] = authority["state"]
    base["official_fact_classes"] = sorted(authority["official_fact_classes"])
    base["official_source_count"] = authority["official_source_count"]
    if authority["state"] != contract["official_source_guards"]["verified_authority_state"]:
        base["explanations"] = [authority["reason"], "PARTENER.EU remains discovery/intelligence only."]
        return base

    official_fact_classes = set(authority["official_fact_classes"])
    material = record.get("material_facts") or {}
    explicit_codes = extract_activity_codes({"eligibility": material.get("eligibility")}) if "eligibility" in official_fact_classes else set()
    profile_codes = {re.sub(r"\D", "", code) for code in profile.get("activity_codes", []) if re.sub(r"\D", "", code)}
    if explicit_codes and profile_codes and not (explicit_codes & profile_codes):
        base["state"] = contract["outputs"]["excluded"]
        base["hard_exclusion_reasons"] = [f"officially bound activity code mismatch: profile={sorted(profile_codes)} source={sorted(explicit_codes)}"]
        base["explanations"] = ["An officially bound activity-code rule conflicts with the supplied profile."]
        return base

    requested = profile.get("requested_grant_eur")
    verified_cap = extract_verified_grant_cap(material) if "grant" in official_fact_classes else None
    if requested is not None and verified_cap is not None and requested > verified_cap:
        base["state"] = contract["outputs"]["excluded"]
        base["hard_exclusion_reasons"] = [f"requested_grant_eur={requested:g} exceeds officially_bound_cap_eur={verified_cap:g}"]
        base["explanations"] = ["The requested grant exceeds an officially bound source cap."]
        return base

    blob = text_blob(record, official_fact_classes)
    weights = contract["weights"]
    score = 0
    dimensions = 0
    explanations: list[str] = []

    if explicit_codes and profile_codes and (explicit_codes & profile_codes):
        score += int(weights["activity_code"])
        dimensions += 1
        explanations.append(f"officially bound activity-code overlap: {', '.join(sorted(explicit_codes & profile_codes))}")

    investment_hits = matched_terms(profile.get("investment_terms", []), blob)
    if investment_hits:
        score += min(int(weights["investment_terms_max"]), 10 * len(investment_hits))
        dimensions += 1
        explanations.append("relevance terms found in discovery metadata or officially bound facts: " + ", ".join(investment_hits))

    organization_hits = matched_terms(profile.get("organization_labels", []), blob)
    if organization_hits:
        score += min(int(weights["organization_terms_max"]), 10 * len(organization_hits))
        dimensions += 1
        explanations.append("organization terms found in discovery metadata or officially bound facts: " + ", ".join(organization_hits))

    region_hits = matched_terms(profile.get("region_terms", []), blob)
    if region_hits:
        score += min(int(weights["region_terms_max"]), 5 * len(region_hits))
        dimensions += 1
        explanations.append("region terms found in discovery metadata or officially bound facts: " + ", ".join(region_hits))

    if requested is not None and verified_cap is not None and requested <= verified_cap:
        score += int(weights["grant_within_verified_cap"])
        dimensions += 1
        explanations.append(f"requested grant is within officially bound cap ({verified_cap:g} EUR)")

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
        "explanations": explanations or ["No sufficiently specific relevance signal was found; more project data is required."],
    })
    return base


def match(
    profile: dict[str, Any],
    bridge: dict[str, Any],
    contract: dict[str, Any],
    official_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_contract(contract)
    normalized = validate_profile(profile, contract)
    receipts = validate_official_registry(official_registry, contract)
    results = [score_record(record, normalized, bridge, contract, receipts) for record in bridge.get("opportunities") or []]
    results.sort(key=lambda row: (-row["score"], str(row.get("opportunity_id") or "")))
    verified_authority = contract["official_source_guards"]["verified_authority_state"]
    waiting_authority = contract["official_source_guards"]["waiting_authority_state"]
    blocked_authority = contract["official_source_guards"]["blocked_authority_state"]
    return {
        "schema_version": 2,
        "engine_id": contract["engine_id"],
        "profile_id": normalized["profile_id"],
        "score_semantics": contract["score_semantics"],
        "bridge_state": bridge.get("bridge_state"),
        "partener_role": contract["official_source_guards"]["partener_role"],
        "summary": {
            "evaluated": len(results),
            "candidates": sum(row["state"] == contract["outputs"]["candidate"] for row in results),
            "excluded_known_rule": sum(row["state"] == contract["outputs"]["excluded"] for row in results),
            "held_source_state": sum(row["state"] == contract["outputs"]["held"] for row in results),
            "requires_data": sum(row["state"] == contract["outputs"]["insufficient"] for row in results),
            "official_source_verified": sum(row["authority_state"] == verified_authority for row in results),
            "waiting_source": sum(row["authority_state"] == waiting_authority for row in results),
            "blocked_source_conflict": sum(row["authority_state"] == blocked_authority for row in results),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--official-verification-registry", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    registry = load_json(Path(args.official_verification_registry)) if args.official_verification_registry else None
    result = match(
        load_json(Path(args.profile)),
        load_json(Path(args.projection)),
        load_json(Path(args.contract)),
        registry,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
