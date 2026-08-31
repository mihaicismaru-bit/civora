from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
REGISTER_SCHEMA = "eucons.ai4work_collection_channel_register.v0.2"
CATALOG_SCHEMA = "eucons.ai4work_research_invitation_catalog.v0.1"
TARGET_REGIONS = {"Centru", "Sud-Muntenia", "Sud-Vest Oltenia"}
TARGET_AUDIENCES = {"adults", "employers"}
CHANNEL_ID_RE = re.compile(r"^CH-[A-Z0-9]{8,32}$")
CHANNEL_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
INVITATION_VERSION_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{5,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REGISTER_KEYS = {"schema_version", "research_id", "invitation_catalog", "entries"}
CATALOG_BINDING_KEYS = {"reference", "sha256"}
ENTRY_KEYS = {
    "channel_id",
    "channel_type",
    "region_scope",
    "audience_scope",
    "invitation_version",
    "opened_at",
    "closed_at",
    "distributor_role",
    "non_coercion_confirmed",
}
CATALOG_KEYS = {
    "schema_version",
    "research_id",
    "status",
    "evidence_class",
    "approved_for_prod",
    "purpose",
    "entries",
    "transport_policy",
    "approval",
    "test_twin_policy",
    "merge_authorized",
    "deploy_authorized",
    "real_dissemination_authorized",
}
CATALOG_ENTRY_KEYS = {
    "invitation_version",
    "audience_scope",
    "invitation_text",
    "required_safeguards",
}
REQUIRED_SAFEGUARDS = {
    "voluntary_participation",
    "no_disadvantage",
    "no_project_enrolment_condition",
    "no_commercial_marketing",
    "no_direct_identifier_request",
    "no_incentive_condition",
    "privacy_notice_before_form",
    "one_response_request",
}
FORBIDDEN_TRACKING_TOKENS = (
    "utm_",
    "gclid=",
    "fbclid=",
    "msclkid=",
    "crm_id=",
    "contact_id=",
    "email=",
    "phone=",
)


class CollectionChannelRegisterError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CollectionChannelRegisterError(f"{field} must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CollectionChannelRegisterError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CollectionChannelRegisterError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _validate_catalog_binding(binding: Any) -> dict[str, str]:
    if not isinstance(binding, dict) or set(binding) != CATALOG_BINDING_KEYS:
        raise CollectionChannelRegisterError(
            f"invitation_catalog fields must be exactly {sorted(CATALOG_BINDING_KEYS)}"
        )
    reference = binding.get("reference")
    digest = binding.get("sha256")
    if not isinstance(reference, str) or not reference.strip() or Path(reference).name != reference:
        raise CollectionChannelRegisterError("invitation catalog reference must be one local filename")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise CollectionChannelRegisterError("invitation catalog sha256 must be lowercase SHA-256 hex")
    return {"reference": reference, "sha256": digest}


def validate_invitation_catalog(catalog: Any, *, require_approved: bool) -> dict[str, dict[str, Any]]:
    if not isinstance(catalog, dict) or set(catalog) != CATALOG_KEYS:
        raise CollectionChannelRegisterError(
            f"invitation catalog fields must be exactly {sorted(CATALOG_KEYS)}"
        )
    if catalog.get("schema_version") != CATALOG_SCHEMA:
        raise CollectionChannelRegisterError("unsupported invitation catalog schema")
    if catalog.get("research_id") != RESEARCH_ID:
        raise CollectionChannelRegisterError("invitation catalog research_id mismatch")
    if catalog.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        raise CollectionChannelRegisterError("invitation catalog must remain CONTROL_ARTIFACT_NOT_EVIDENCE")
    if catalog.get("test_twin_policy") != "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE":
        raise CollectionChannelRegisterError("invitation catalog test-twin boundary is not fail-closed")
    if catalog.get("merge_authorized") is not False or catalog.get("deploy_authorized") is not False:
        raise CollectionChannelRegisterError("invitation catalog cannot authorize merge or deploy")
    if catalog.get("real_dissemination_authorized") is not False:
        raise CollectionChannelRegisterError("draft invitation catalog cannot authorize real dissemination")

    policy = catalog.get("transport_policy")
    if not isinstance(policy, dict):
        raise CollectionChannelRegisterError("invitation catalog transport_policy is required")
    expected_policy = {
        "channel_identifier_mode": "OPAQUE_URL_FRAGMENT_ONLY",
        "channel_identifier_format": "CH-[A-Z0-9]{8,32}",
        "query_tracking_parameters_allowed": False,
        "commercial_tracking_allowed": False,
        "crm_identifier_allowed": False,
        "referrer_derived_channel_allowed": False,
    }
    if policy != expected_policy:
        raise CollectionChannelRegisterError("invitation catalog transport policy is not fail-closed")

    entries = catalog.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CollectionChannelRegisterError("invitation catalog must contain controlled adult/employer copy")
    by_version: dict[str, dict[str, Any]] = {}
    covered: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != CATALOG_ENTRY_KEYS:
            raise CollectionChannelRegisterError(
                f"invitation catalog entry fields must be exactly {sorted(CATALOG_ENTRY_KEYS)}"
            )
        version = entry.get("invitation_version")
        if not isinstance(version, str) or not INVITATION_VERSION_RE.fullmatch(version):
            raise CollectionChannelRegisterError("invitation_version format invalid")
        if version in by_version:
            raise CollectionChannelRegisterError("duplicate invitation_version in catalog")
        audiences = entry.get("audience_scope")
        if (
            not isinstance(audiences, list)
            or not audiences
            or any(item not in TARGET_AUDIENCES for item in audiences)
            or len(audiences) != len(set(audiences))
        ):
            raise CollectionChannelRegisterError("invitation catalog audience_scope invalid")
        text = entry.get("invitation_text")
        if not isinstance(text, str) or len(text.strip()) < 120:
            raise CollectionChannelRegisterError("invitation_text must contain frozen neutral copy")
        lowered = text.casefold()
        if any(token in lowered for token in FORBIDDEN_TRACKING_TOKENS):
            raise CollectionChannelRegisterError("invitation_text contains a forbidden tracking/direct-id token")
        safeguards = entry.get("required_safeguards")
        if not isinstance(safeguards, dict) or set(safeguards) != REQUIRED_SAFEGUARDS:
            raise CollectionChannelRegisterError("invitation safeguards set is incomplete")
        if any(safeguards[key] is not True for key in REQUIRED_SAFEGUARDS):
            raise CollectionChannelRegisterError("all invitation safeguards must be true")
        covered.update(audiences)
        by_version[version] = entry
    if covered != TARGET_AUDIENCES:
        raise CollectionChannelRegisterError("invitation catalog must cover adults and employers")

    approval = catalog.get("approval")
    if not isinstance(approval, dict) or approval.get("approved_for_prod") is not catalog.get("approved_for_prod"):
        raise CollectionChannelRegisterError("invitation catalog approval fields are inconsistent")
    if require_approved:
        if catalog.get("status") != "APPROVED_FOR_PROD" or catalog.get("approved_for_prod") is not True:
            raise CollectionChannelRegisterError("invitation catalog is not approved for PROD")
        if not str(approval.get("approver_name_or_role") or "").strip():
            raise CollectionChannelRegisterError("invitation catalog PROD approval lacks approver")
        if not str(approval.get("approval_date") or "").strip():
            raise CollectionChannelRegisterError("invitation catalog PROD approval lacks approval_date")
    return by_version


def validate_register(register: Any, *, require_nonempty: bool) -> dict[str, dict[str, Any]]:
    if not isinstance(register, dict) or set(register) != REGISTER_KEYS:
        raise CollectionChannelRegisterError(f"channel register fields must be exactly {sorted(REGISTER_KEYS)}")
    if register.get("schema_version") != REGISTER_SCHEMA:
        raise CollectionChannelRegisterError("unsupported collection-channel register schema")
    if register.get("research_id") != RESEARCH_ID:
        raise CollectionChannelRegisterError("channel register research_id mismatch")
    _validate_catalog_binding(register.get("invitation_catalog"))
    entries = register.get("entries")
    if not isinstance(entries, list):
        raise CollectionChannelRegisterError("channel register entries must be a list")
    if require_nonempty and not entries:
        raise CollectionChannelRegisterError("channel register must contain at least one approved dissemination batch before PROD")

    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise CollectionChannelRegisterError(f"channel register entry fields must be exactly {sorted(ENTRY_KEYS)}")
        channel_id = entry.get("channel_id")
        if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
            raise CollectionChannelRegisterError("channel_id must match CH-[A-Z0-9]{8,32}")
        if channel_id in by_id:
            raise CollectionChannelRegisterError("duplicate channel_id in channel register")
        channel_type = entry.get("channel_type")
        if not isinstance(channel_type, str) or not CHANNEL_TYPE_RE.fullmatch(channel_type):
            raise CollectionChannelRegisterError("channel_type must be a bounded lowercase code")

        regions = entry.get("region_scope")
        if not isinstance(regions, list) or not regions or any(region not in TARGET_REGIONS for region in regions):
            raise CollectionChannelRegisterError("region_scope must contain only target regions")
        if len(regions) != len(set(regions)):
            raise CollectionChannelRegisterError("region_scope contains duplicates")

        audiences = entry.get("audience_scope")
        if not isinstance(audiences, list) or not audiences or any(item not in TARGET_AUDIENCES for item in audiences):
            raise CollectionChannelRegisterError("audience_scope must contain adults and/or employers")
        if len(audiences) != len(set(audiences)):
            raise CollectionChannelRegisterError("audience_scope contains duplicates")

        invitation_version = entry.get("invitation_version")
        if not isinstance(invitation_version, str) or not INVITATION_VERSION_RE.fullmatch(invitation_version):
            raise CollectionChannelRegisterError("invitation_version format invalid")
        if not isinstance(entry.get("distributor_role"), str) or not entry["distributor_role"].strip():
            raise CollectionChannelRegisterError("distributor_role is required")

        opened = _parse_ts(entry.get("opened_at"), field="opened_at")
        closed = _parse_ts(entry.get("closed_at"), field="closed_at")
        if closed < opened:
            raise CollectionChannelRegisterError("channel collection window is inverted")
        if entry.get("non_coercion_confirmed") is not True:
            raise CollectionChannelRegisterError("non_coercion_confirmed must be true")
        by_id[channel_id] = entry
    return by_id


def validate_invitation_catalog_binding(*, register_path: Path, register: dict[str, Any], require_approved: bool) -> list[str]:
    errors: list[str] = []
    try:
        binding = _validate_catalog_binding(register.get("invitation_catalog"))
        catalog_path = register_path.parent / binding["reference"]
        actual = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        if actual != binding["sha256"]:
            raise CollectionChannelRegisterError("invitation catalog sha256 mismatch")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        by_version = validate_invitation_catalog(catalog, require_approved=require_approved)
        for entry in register.get("entries") or []:
            version = entry["invitation_version"]
            if version not in by_version:
                raise CollectionChannelRegisterError("channel invitation_version absent from frozen catalog")
            allowed_audiences = set(by_version[version]["audience_scope"])
            if not set(entry["audience_scope"]).issubset(allowed_audiences):
                raise CollectionChannelRegisterError("channel audience_scope exceeds invitation catalog scope")
    except (OSError, ValueError, CollectionChannelRegisterError) as exc:
        errors.append(f"invitation_catalog_binding_invalid:{exc}")
    return errors


def validate_prod_binding(*, register_path: Path, collection_frame: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        register = json.loads(register_path.read_text(encoding="utf-8"))
        validate_register(register, require_nonempty=True)
    except (OSError, ValueError, CollectionChannelRegisterError) as exc:
        errors.append(f"collection_channel_register_invalid:{exc}")
        return errors

    errors.extend(
        validate_invitation_catalog_binding(
            register_path=register_path,
            register=register,
            require_approved=True,
        )
    )
    approval = collection_frame.get("approval")
    if not isinstance(approval, dict):
        errors.append("collection_channel_register_frame_approval_missing")
        return errors
    declared = approval.get("collection_channel_register_sha256")
    actual = hashlib.sha256(register_path.read_bytes()).hexdigest()
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        errors.append("collection_channel_register_sha256_missing")
    elif declared != actual:
        errors.append("collection_channel_register_sha256_mismatch")
    return errors
