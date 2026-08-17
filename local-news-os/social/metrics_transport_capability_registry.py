#!/usr/bin/env python3
"""Strict capability registry for fleet observed-metrics transports.

A social channel becomes eligible for fleet metrics harvest only when the transport
is explicitly registered here, matches an actually implemented native transport
profile, is native/free, requires verified access attestation, and remains subject
to the separate per-instance credential-binding gate.

This registry never reads credential values and analytics can never block editorial
publication.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import native_metrics_transport

SCHEMA_VERSION = "1.0"
REGISTRY_ID = "local-news-os-metrics-transport-capability-registry"
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("metrics_transport_capabilities.json")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,95}$")
METRIC_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,95}$")
READY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")

TOP_LEVEL_FIELDS = {"schema_version", "product", "policy", "capabilities"}
POLICY_FIELDS = {
    "explicit_transport_registration_required",
    "implementation_match_required",
    "verified_access_attestation_required",
    "explicit_credential_binding_required",
    "observed_only",
    "analytics_advisory_only",
    "zero_paid_dependency",
}
CAPABILITY_FIELDS = {
    "capability_id",
    "platform",
    "metric_source",
    "transport_module",
    "transport_profile",
    "network_boundary",
    "credential_ref_kind",
    "access_ready_key",
    "metric_candidates",
    "requires_remote_publication_proof",
    "observed_only",
    "zero_paid_dependency",
}
REQUIRED_TRUE_POLICIES = POLICY_FIELDS
SECRETISH_FIELD_FRAGMENTS = ("secret_value", "token_value", "password", "api_key", "credential_value")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("capability registry must contain a JSON object")
    return value


def load_default_registry() -> dict[str, Any]:
    return _load(DEFAULT_REGISTRY_PATH)


def _secretish_unknown_fields(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in record:
        lowered = _clean(key).lower()
        if any(fragment in lowered for fragment in SECRETISH_FIELD_FRAGMENTS):
            result.append(_clean(key))
    return sorted(set(result))


def validate_registry(
    registry: dict[str, Any],
    implemented_profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate declared capabilities against actual transport implementation."""
    if not isinstance(registry, dict):
        raise TypeError("registry must be a mapping")
    profiles = implemented_profiles if implemented_profiles is not None else native_metrics_transport.META_PROFILES
    blocks: list[str] = []

    unknown_top = sorted(set(registry) - TOP_LEVEL_FIELDS)
    if unknown_top:
        blocks.append("UNKNOWN_CAPABILITY_REGISTRY_FIELDS:" + ",".join(unknown_top))
    if _clean(registry.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("CAPABILITY_REGISTRY_SCHEMA_VERSION_MISMATCH")

    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    unknown_policy = sorted(set(policy) - POLICY_FIELDS)
    if unknown_policy:
        blocks.append("UNKNOWN_CAPABILITY_POLICY_FIELDS:" + ",".join(unknown_policy))
    for key in sorted(REQUIRED_TRUE_POLICIES):
        if policy.get(key) is not True:
            blocks.append(f"CAPABILITY_POLICY_REQUIRED:{key}")

    raw_rows = registry.get("capabilities")
    if not isinstance(raw_rows, list) or not raw_rows:
        blocks.append("CAPABILITIES_LIST_REQUIRED")
        raw_rows = []

    seen_ids: set[str] = set()
    seen_platforms: set[str] = set()
    seen_sources: set[str] = set()
    rows: list[dict[str, Any]] = []
    row_holds: list[dict[str, Any]] = []

    for raw in raw_rows:
        local: list[str] = []
        if not isinstance(raw, dict):
            row_holds.append({"capability_id": None, "platform": None, "hard_blocks": ["INVALID_CAPABILITY_RECORD"]})
            continue

        unknown = sorted(set(raw) - CAPABILITY_FIELDS)
        if unknown:
            local.append("UNKNOWN_CAPABILITY_FIELDS:" + ",".join(unknown))
        secretish = _secretish_unknown_fields(raw)
        if secretish:
            local.append("SECRET_MATERIAL_FIELD_FORBIDDEN:" + ",".join(secretish))

        capability_id = _clean(raw.get("capability_id")).lower()
        platform = _clean(raw.get("platform")).lower()
        source = _clean(raw.get("metric_source")).lower()
        transport_module = _clean(raw.get("transport_module"))
        transport_profile = _clean(raw.get("transport_profile")).lower()
        network_boundary = _clean(raw.get("network_boundary")).lower()
        credential_ref_kind = _clean(raw.get("credential_ref_kind")).lower()
        access_ready_key = _clean(raw.get("access_ready_key"))
        candidates_raw = raw.get("metric_candidates")

        if not ID_RE.fullmatch(capability_id):
            local.append("INVALID_CAPABILITY_ID")
        elif capability_id in seen_ids:
            local.append("DUPLICATE_CAPABILITY_ID")
        seen_ids.add(capability_id)

        if not PLATFORM_RE.fullmatch(platform):
            local.append("INVALID_CAPABILITY_PLATFORM")
        elif platform in seen_platforms:
            local.append("DUPLICATE_CAPABILITY_PLATFORM")
        seen_platforms.add(platform)

        if not SOURCE_RE.fullmatch(source):
            local.append("INVALID_CAPABILITY_METRIC_SOURCE")
        elif source in seen_sources:
            local.append("DUPLICATE_CAPABILITY_METRIC_SOURCE")
        seen_sources.add(source)

        if transport_module != "native_metrics_transport":
            local.append("UNSUPPORTED_TRANSPORT_MODULE")
        if transport_profile != platform:
            local.append("TRANSPORT_PROFILE_PLATFORM_MISMATCH")
        if network_boundary != "native_free_api":
            local.append("NON_NATIVE_FREE_NETWORK_BOUNDARY")
        if credential_ref_kind != "github-actions-secret":
            local.append("UNSUPPORTED_CREDENTIAL_REF_KIND")
        if not READY_KEY_RE.fullmatch(access_ready_key):
            local.append("INVALID_ACCESS_READY_KEY")
        if raw.get("requires_remote_publication_proof") is not True:
            local.append("REMOTE_PUBLICATION_PROOF_REQUIRED")
        if raw.get("observed_only") is not True:
            local.append("OBSERVED_ONLY_REQUIRED")
        if raw.get("zero_paid_dependency") is not True:
            local.append("ZERO_PAID_DEPENDENCY_REQUIRED")

        if not isinstance(candidates_raw, list) or not candidates_raw:
            candidates: list[str] = []
            local.append("METRIC_CANDIDATES_REQUIRED")
        else:
            candidates = [_clean(item).lower() for item in candidates_raw]
            if any(not METRIC_RE.fullmatch(item) for item in candidates):
                local.append("INVALID_METRIC_CANDIDATE")
            if len(set(candidates)) != len(candidates):
                local.append("DUPLICATE_METRIC_CANDIDATE")

        profile = profiles.get(platform) if isinstance(profiles, dict) else None
        if not isinstance(profile, dict):
            local.append("CAPABILITY_HAS_NO_IMPLEMENTED_TRANSPORT_PROFILE")
        else:
            implemented_source = _clean(profile.get("source")).lower()
            implemented_ready_key = _clean(profile.get("ready_key"))
            implemented_candidates = [_clean(item).lower() for item in profile.get("metric_candidates", ())]
            if source != implemented_source:
                local.append("CAPABILITY_SOURCE_IMPLEMENTATION_MISMATCH")
            if access_ready_key != implemented_ready_key:
                local.append("CAPABILITY_ACCESS_KEY_IMPLEMENTATION_MISMATCH")
            if candidates != implemented_candidates:
                local.append("CAPABILITY_METRICS_IMPLEMENTATION_MISMATCH")

        normalized = {
            "capability_id": capability_id or None,
            "platform": platform or None,
            "metric_source": source or None,
            "transport_module": transport_module or None,
            "transport_profile": transport_profile or None,
            "network_boundary": network_boundary or None,
            "credential_ref_kind": credential_ref_kind or None,
            "access_ready_key": access_ready_key or None,
            "metric_candidates": candidates,
            "requires_remote_publication_proof": raw.get("requires_remote_publication_proof") is True,
            "observed_only": raw.get("observed_only") is True,
            "zero_paid_dependency": raw.get("zero_paid_dependency") is True,
            "hard_blocks": sorted(set(local)),
        }
        if local:
            row_holds.append(normalized)
        else:
            rows.append(normalized)

    # If code implements a profile but it is not explicitly registered, it remains
    # intentionally ineligible rather than receiving implicit fleet access.
    implemented_unregistered = sorted(set(profiles) - {row["platform"] for row in rows if row.get("platform")})

    status = "PASS" if not blocks and not row_holds else "HOLD"
    if status != "PASS":
        rows = []

    return {
        "schema_version": SCHEMA_VERSION,
        "registry_id": REGISTRY_ID,
        "status": status,
        "hard_blocks": sorted(set(blocks)),
        "capability_holds": row_holds,
        "capabilities": sorted(rows, key=lambda row: (str(row.get("platform")), str(row.get("capability_id")))),
        "implemented_unregistered_platforms": implemented_unregistered,
        "publication_blocked": False,
        "guards": {
            "explicit_transport_registration_required": True,
            "implementation_match_required": True,
            "verified_access_attestation_required": True,
            "explicit_credential_binding_required": True,
            "implicit_transport_enablement_allowed": False,
            "secret_values_read": False,
            "secret_values_returned": False,
            "analytics_advisory_only": True,
            "publication_blocked_by_analytics": False,
            "native_free_transport_only": True,
            "zero_paid_dependency": True,
        },
    }


def capability_for_platform(validation: dict[str, Any], platform: str) -> dict[str, Any] | None:
    if not isinstance(validation, dict) or validation.get("status") != "PASS":
        return None
    wanted = _clean(platform).lower()
    rows = validation.get("capabilities") if isinstance(validation.get("capabilities"), list) else []
    for row in rows:
        if isinstance(row, dict) and _clean(row.get("platform")).lower() == wanted:
            return dict(row)
    return None


def validate_access_attestation(capability: dict[str, Any], attestation: dict[str, Any]) -> list[str]:
    """Verify access before a channel can enter the credential-binding matrix."""
    blocks: list[str] = []
    if not isinstance(capability, dict) or not isinstance(attestation, dict):
        return ["MISSING_VERIFIED_METRICS_ACCESS_ATTESTATION"]
    status = _clean(attestation.get("status")).upper()
    if status not in {"VALID", "VERIFIED"}:
        blocks.append("UNVERIFIED_NATIVE_METRICS_ACCESS")
    if attestation.get("secret_material_persisted") is True:
        blocks.append("SECRET_MATERIAL_PERSISTED_IN_ACCESS_ATTESTATION")
    ready_key = _clean(capability.get("access_ready_key"))
    generic_ready = attestation.get("verified_metrics_access") is True
    platform_ready = bool(ready_key and attestation.get(ready_key) is True)
    if not (generic_ready or platform_ready):
        blocks.append("NATIVE_METRICS_ACCESS_NOT_READY")
    return sorted(set(blocks))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path, nargs="?", default=DEFAULT_REGISTRY_PATH)
    args = parser.parse_args()
    result = validate_registry(_load(args.registry))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
