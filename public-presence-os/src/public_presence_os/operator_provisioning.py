from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256

from .connection_preflight import (
    PASS_STATE as PREFLIGHT_PASS_STATE,
    SyntheticPreflightReceipt,
    validate_synthetic_preflight_receipt,
)
from .connection_profiles import ConnectionProfile, parse_secret_reference, validate_connection_profile
from .control import EXPECTED_ACTIVE, canonical_json

PROVISIONING_MODEL_VERSION = "PPOS_META_OPERATOR_PROVISIONING_PACKET_V1"
PROVISIONING_ENGINE_VERSION = "ppos-meta-operator-provisioning-packet-v1.0.0"
PACKET_STATE = "OFFLINE_OPERATOR_PACKET_READY"


class OperatorProvisioningError(ValueError):
    pass


class OperatorProvisioningHold(OperatorProvisioningError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProvisioningChecklistItem:
    item_id: str
    category: str
    instruction: str
    evidence_required: str
    state: str
    blocking_for_live_connection: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OperatorProvisioningPacket:
    packet_id: str
    packet_hash: str
    model_version: str
    engine_version: str
    preflight_receipt_id: str
    preflight_receipt_hash: str
    profile_id: str
    profile_hash: str
    platform: str
    mode: str
    auth_reference_kind: str
    secret_reference: str
    secret_reference_scheme: str
    required_permissions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    lane_prerequisites: tuple[str, ...]
    checklist: tuple[ProvisioningChecklistItem, ...]
    live_blockers: tuple[str, ...]
    secret_material_included: bool = False
    secret_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    network_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    live_entitlement_verified: bool = False
    live_connection_ready: bool = False
    pilot_publish_ready: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = PACKET_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["checklist"] = [item.to_dict() for item in self.checklist]
        return data


_LANE_PREREQUISITES = {
    "FACEBOOK_PAGE": (
        "FACEBOOK_PAGE_EXISTS",
        "OPERATOR_HAS_SUFFICIENT_PAGE_ACCESS",
        "META_APP_OR_SELF_USE_CONTEXT_DEFINED",
        "PAGE_PUBLISHING_PERMISSION_PATH_REVERIFIED_BEFORE_LIVE",
        "PAGE_ACCESS_TOKEN_MINT_PATH_DOCUMENTED_OUT_OF_BAND",
    ),
    "INSTAGRAM_PROFESSIONAL": (
        "INSTAGRAM_ACCOUNT_IS_PROFESSIONAL_BUSINESS_OR_CREATOR",
        "META_APP_OR_SELF_USE_CONTEXT_DEFINED",
        "INSTAGRAM_PUBLISHING_PRODUCT_OR_CURRENT_EQUIVALENT_CONFIGURED",
        "INSTAGRAM_PUBLISH_PERMISSIONS_REVERIFIED_BEFORE_LIVE",
        "LIVE_MEDIA_STAGING_REQUIREMENT_DOCUMENTED_FOR_IMAGE_MODE",
    ),
    "THREADS": (
        "THREADS_PROFILE_EXISTS",
        "META_APP_OR_SELF_USE_CONTEXT_DEFINED",
        "THREADS_API_USE_CASE_OR_CURRENT_EQUIVALENT_CONFIGURED",
        "THREADS_PUBLISH_PERMISSIONS_REVERIFIED_BEFORE_LIVE",
        "CREATE_THEN_PUBLISH_CONTAINER_FLOW_REVERIFIED_BEFORE_LIVE",
    ),
}

_LIVE_BLOCKERS = (
    "HOLD_OPERATOR_OWNERSHIP_AND_ROLE_UNVERIFIED",
    "HOLD_META_APP_CONFIGURATION_UNVERIFIED",
    "HOLD_LIVE_PERMISSION_AND_CAPABILITY_REVERIFICATION",
    "HOLD_TOKEN_EXPIRY_AND_ROTATION_EVIDENCE",
    "HOLD_REAL_DESTINATION_UNBOUND",
    "HOLD_LITERAL_API_VERSION_UNBOUND",
    "HOLD_SECRET_UNRESOLVED",
    "HOLD_READ_ONLY_CONNECTION_TEST_NOT_AUTHORIZED",
    "HOLD_ACCOUNT_NOT_CONNECTED",
    "HOLD_PILOT_FINAL_AUTHORIZATION_REQUIRED",
)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _checklist(platform: str) -> tuple[ProvisioningChecklistItem, ...]:
    common = (
        ProvisioningChecklistItem(
            "CP52_EXACT_PREFLIGHT",
            "offline_contract",
            "Retain the exact CP52 synthetic preflight receipt and its SHA-256 binding.",
            "CP52 receipt_id + receipt_hash",
            "PASS_OFFLINE_CONTRACT",
            False,
        ),
        ProvisioningChecklistItem(
            "CP51_PROFILE_EXACT",
            "offline_contract",
            "Retain the exact CP51 connection profile referenced by CP52.",
            "profile_id + profile_hash",
            "PASS_OFFLINE_CONTRACT",
            False,
        ),
        ProvisioningChecklistItem(
            "SECRET_REFERENCE_LOCATOR_STAGED",
            "secret_boundary",
            "Provision only the declared ENV: or OS_KEYCHAIN: locator; never place credential material in the packet.",
            "symbolic secret-reference locator",
            "PASS_SYMBOLIC_REFERENCE_ONLY",
            False,
        ),
        ProvisioningChecklistItem(
            "OPERATOR_OWNERSHIP_ROLE",
            "operator",
            "Verify the operator controls the intended destination and has the Meta role/access required for publishing.",
            "dated operator evidence captured outside this packet",
            "PENDING_OPERATOR_EVIDENCE",
            True,
        ),
        ProvisioningChecklistItem(
            "META_APP_CONFIGURATION",
            "meta_app",
            "Verify the Meta app/use-case configuration for this lane using current official documentation.",
            "dated configuration evidence + official-doc reference",
            "PENDING_OPERATOR_EVIDENCE",
            True,
        ),
        ProvisioningChecklistItem(
            "REQUIRED_PERMISSIONS_LIVE",
            "permissions",
            "Reverify every required permission immediately before any live connection attempt.",
            "live readback matching packet required_permissions",
            "PENDING_LIVE_REVERIFICATION",
            True,
        ),
        ProvisioningChecklistItem(
            "REQUIRED_CAPABILITIES_LIVE",
            "capabilities",
            "Reverify the exact publishing capability set immediately before any live connection attempt.",
            "live readback matching packet required_capabilities",
            "PENDING_LIVE_REVERIFICATION",
            True,
        ),
        ProvisioningChecklistItem(
            "TOKEN_EXPIRY_ROTATION",
            "credential_lifecycle",
            "Record credential expiry/rotation policy without recording the credential itself.",
            "expiry state + rotation/revocation procedure",
            "PENDING_OPERATOR_EVIDENCE",
            True,
        ),
        ProvisioningChecklistItem(
            "DESTINATION_BINDING",
            "destination",
            "Bind the real destination ID only inside the future live-connection checkpoint, never in CP53.",
            "future exact destination readback",
            "PENDING_FUTURE_CHECKPOINT",
            True,
        ),
        ProvisioningChecklistItem(
            "API_VERSION_BINDING",
            "api_version",
            "Pin and record the current supported API version only inside the future live-connection checkpoint.",
            "future official version evidence + exact value",
            "PENDING_FUTURE_CHECKPOINT",
            True,
        ),
        ProvisioningChecklistItem(
            "READ_ONLY_CONNECTION_TEST",
            "connection_test",
            "Run only an explicitly authorized read-only connection test before any publishing authority is considered.",
            "future read-only receipt with zero external writes",
            "PENDING_FUTURE_CHECKPOINT",
            True,
        ),
        ProvisioningChecklistItem(
            "RECOVERY_AND_REVOCATION",
            "recovery",
            "Confirm kill-switch, token revocation, local state rollback and account disconnect recovery steps.",
            "operator recovery checklist",
            "PENDING_OPERATOR_EVIDENCE",
            True,
        ),
        ProvisioningChecklistItem(
            "PILOT_FINAL_AUTHORIZATION",
            "governance",
            "Obtain a fresh explicit final authorization only after every pilot gate passes.",
            "fresh final pilot authorization",
            "PENDING_FINAL_AUTHORIZATION",
            True,
        ),
    )
    lane = tuple(
        ProvisioningChecklistItem(
            f"LANE_{i:02d}_{requirement}",
            "lane_prerequisite",
            requirement.replace("_", " ").capitalize() + ".",
            f"dated evidence for {requirement}",
            "PENDING_OPERATOR_EVIDENCE",
            True,
        )
        for i, requirement in enumerate(_LANE_PREREQUISITES[platform], start=1)
    )
    return common + lane


def compile_operator_provisioning_packet(
    preflight: SyntheticPreflightReceipt,
    profile: ConnectionProfile,
) -> OperatorProvisioningPacket:
    validate_synthetic_preflight_receipt(preflight)
    validate_connection_profile(profile)

    if preflight.state != PREFLIGHT_PASS_STATE:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PREFLIGHT_NOT_PASS")
    if preflight.profile_id != profile.profile_id or preflight.profile_hash != profile.profile_hash:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PROFILE_BINDING_MISMATCH")
    if preflight.readback.profile_id != profile.profile_id or preflight.readback.profile_hash != profile.profile_hash:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_READBACK_PROFILE_MISMATCH")
    if preflight.readback.platform != profile.platform:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PLATFORM_MISMATCH")
    if preflight.readback.mode != profile.mode:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_MODE_MISMATCH")
    if preflight.readback.auth_reference_kind != profile.auth_reference_kind:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_AUTH_REFERENCE_MISMATCH")
    if preflight.readback.required_permissions != profile.required_permissions:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PERMISSION_MISMATCH")
    if preflight.readback.required_capabilities != profile.required_capabilities:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_CAPABILITY_MISMATCH")
    if profile.platform not in EXPECTED_ACTIVE or profile.platform not in _LANE_PREREQUISITES:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PLATFORM_NOT_ACTIVE")
    if not preflight.synthetic_contract_pass or not preflight.offline_contract_evidence_complete:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_OFFLINE_CONTRACT_INCOMPLETE")
    if not preflight.live_reverification_required or not profile.live_reverification_required:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_LIVE_REVERIFICATION_GATE_DRIFT")

    secret_ref = parse_secret_reference(profile.secret_reference)
    checklist = _checklist(profile.platform)
    body = {
        "model_version": PROVISIONING_MODEL_VERSION,
        "engine_version": PROVISIONING_ENGINE_VERSION,
        "preflight_receipt_id": preflight.receipt_id,
        "preflight_receipt_hash": preflight.receipt_hash,
        "profile_id": profile.profile_id,
        "profile_hash": profile.profile_hash,
        "platform": profile.platform,
        "mode": profile.mode,
        "auth_reference_kind": profile.auth_reference_kind,
        "secret_reference": secret_ref.canonical,
        "secret_reference_scheme": secret_ref.scheme,
        "required_permissions": list(profile.required_permissions),
        "required_capabilities": list(profile.required_capabilities),
        "lane_prerequisites": list(_LANE_PREREQUISITES[profile.platform]),
        "checklist": [item.to_dict() for item in checklist],
        "live_blockers": list(_LIVE_BLOCKERS),
        "secret_material_included": False,
        "secret_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "network_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "live_entitlement_verified": False,
        "live_connection_ready": False,
        "pilot_publish_ready": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": PACKET_STATE,
    }
    packet_hash = _hash(body)
    packet = OperatorProvisioningPacket(
        packet_id="mopp_" + packet_hash[:24],
        packet_hash=packet_hash,
        model_version=PROVISIONING_MODEL_VERSION,
        engine_version=PROVISIONING_ENGINE_VERSION,
        preflight_receipt_id=preflight.receipt_id,
        preflight_receipt_hash=preflight.receipt_hash,
        profile_id=profile.profile_id,
        profile_hash=profile.profile_hash,
        platform=profile.platform,
        mode=profile.mode,
        auth_reference_kind=profile.auth_reference_kind,
        secret_reference=secret_ref.canonical,
        secret_reference_scheme=secret_ref.scheme,
        required_permissions=profile.required_permissions,
        required_capabilities=profile.required_capabilities,
        lane_prerequisites=_LANE_PREREQUISITES[profile.platform],
        checklist=checklist,
        live_blockers=_LIVE_BLOCKERS,
    )
    validate_operator_provisioning_packet(packet)
    return packet


def validate_operator_provisioning_packet(packet: OperatorProvisioningPacket) -> None:
    if not isinstance(packet, OperatorProvisioningPacket):
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PACKET_TYPE")
    if packet.model_version != PROVISIONING_MODEL_VERSION or packet.engine_version != PROVISIONING_ENGINE_VERSION:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PACKET_VERSION")
    if packet.platform not in EXPECTED_ACTIVE or packet.platform not in _LANE_PREREQUISITES:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PLATFORM_NOT_ACTIVE")
    if packet.lane_prerequisites != _LANE_PREREQUISITES[packet.platform]:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_LANE_PREREQUISITE_DRIFT")
    if packet.live_blockers != _LIVE_BLOCKERS:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_BLOCKER_DRIFT")
    secret_ref = parse_secret_reference(packet.secret_reference)
    if secret_ref.scheme != packet.secret_reference_scheme:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_SECRET_REFERENCE_DRIFT")
    if not packet.checklist or any(item.state.startswith("PASS") and item.blocking_for_live_connection for item in packet.checklist):
        raise OperatorProvisioningHold("HOLD_PROVISIONING_CHECKLIST_STATE_DRIFT")
    pending = [item for item in packet.checklist if item.blocking_for_live_connection]
    if not pending or any(not item.state.startswith("PENDING") for item in pending):
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PENDING_GATE_DRIFT")
    if any((
        packet.secret_material_included,
        packet.secret_resolved,
        packet.environment_read,
        packet.keychain_read,
        packet.network_attempted,
        packet.real_account_lookup_attempted,
        packet.account_connected,
        packet.publish_attempted,
        packet.external_write_performed,
        packet.deploy_performed,
        packet.live_entitlement_verified,
        packet.live_connection_ready,
        packet.pilot_publish_ready,
    )):
        raise OperatorProvisioningHold("HOLD_PROVISIONING_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not packet.global_kill_switch_required or not packet.live_reverification_required:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_SAFETY_GATE_DRIFT")
    if packet.state != PACKET_STATE:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PACKET_STATE")
    body = packet.to_dict()
    body.pop("packet_id")
    body.pop("packet_hash")
    expected_hash = _hash(body)
    if packet.packet_hash != expected_hash:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PACKET_HASH_MISMATCH")
    if packet.packet_id != "mopp_" + packet.packet_hash[:24]:
        raise OperatorProvisioningHold("HOLD_PROVISIONING_PACKET_ID_MISMATCH")


def render_operator_packet_json(packet: OperatorProvisioningPacket) -> str:
    validate_operator_provisioning_packet(packet)
    return canonical_json(packet.to_dict()) + "\n"
