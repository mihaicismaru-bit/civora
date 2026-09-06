from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from .control import EXPECTED_ACTIVE, canonical_json
from .meta_adapters import static_capability_contract

CONNECTION_PROFILE_MODEL_VERSION = "PPOS_META_CONNECTION_PROFILE_VAULT_V1"
CONNECTION_PROFILE_ENGINE_VERSION = "ppos-meta-connection-profile-vault-v1.0.0"
VAULT_SCHEMA_VERSION = "PPOS_SECRET_REFERENCE_VAULT_V1"
DESTINATION_REF = "DESTINATION_ID_REQUIRED"
API_VERSION_REF = "API_VERSION_REQUIRED"
ALLOWED_SECRET_REFERENCE_SCHEMES = ("ENV", "OS_KEYCHAIN")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
KEYCHAIN_NAME = re.compile(r"^[A-Za-z0-9._/-]{3,255}$")

_AUTH_REFERENCE_KIND = {
    "FACEBOOK_PAGE": "PAGE_ACCESS_TOKEN_REF",
    "INSTAGRAM_PROFESSIONAL": "INSTAGRAM_USER_TOKEN_REF",
    "THREADS": "THREADS_USER_TOKEN_REF",
}


class ConnectionProfileError(ValueError):
    pass


class ConnectionProfileHold(ConnectionProfileError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SecretReference:
    scheme: str
    locator: str

    @property
    def canonical(self) -> str:
        return f"{self.scheme}:{self.locator}"


@dataclass(frozen=True)
class OfflineCapabilityEvidence:
    state: str = "STAGED_UNVERIFIED"
    evidence_artifact_sha256: str | None = None
    observed_permissions: tuple[str, ...] = ()
    observed_capabilities: tuple[str, ...] = ()
    expiry_state: str = "UNKNOWN"
    expires_at_utc: str | None = None


@dataclass(frozen=True)
class ConnectionProfileSpec:
    platform: str
    mode: str
    secret_reference: str
    evidence: OfflineCapabilityEvidence = OfflineCapabilityEvidence()
    destination_ref: str = DESTINATION_REF
    api_version_ref: str = API_VERSION_REF


@dataclass(frozen=True)
class ConnectionProfile:
    profile_id: str
    profile_hash: str
    model_version: str
    engine_version: str
    platform: str
    mode: str
    auth_reference_kind: str
    secret_reference: str
    secret_reference_scheme: str
    destination_ref: str
    api_version_ref: str
    required_permissions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    evidence: OfflineCapabilityEvidence
    offline_contract_evidence_complete: bool
    real_entitlement_asserted: bool = False
    secret_resolution_allowed: bool = False
    environment_read_allowed: bool = False
    keychain_read_allowed: bool = False
    network_allowed: bool = False
    real_account_lookup_allowed: bool = False
    account_connection_allowed: bool = False
    publish_execution_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = "STAGED_SECRET_REFERENCE_ONLY"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VaultReceipt:
    request_id: str
    profile_id: str
    profile_hash: str
    event_hash: str
    event_time_utc: str
    stored_new_profile: bool
    state: str = "LOCAL_REFERENCE_STAGED"
    secret_resolved: bool = False
    network_attempted: bool = False
    account_connected: bool = False
    external_write_performed: bool = False


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_secret_reference(value: str) -> SecretReference:
    if not isinstance(value, str) or ":" not in value:
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_FORMAT")
    scheme, locator = value.split(":", 1)
    if scheme not in ALLOWED_SECRET_REFERENCE_SCHEMES:
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_SCHEME")
    if not locator or locator != locator.strip():
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_LOCATOR")
    if any(ch.isspace() for ch in locator) or "=" in locator or "://" in locator:
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_LOCATOR")
    if scheme == "ENV" and not ENV_NAME.fullmatch(locator):
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_ENV_NAME")
    if scheme == "OS_KEYCHAIN" and not KEYCHAIN_NAME.fullmatch(locator):
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_KEYCHAIN_NAME")
    return SecretReference(scheme=scheme, locator=locator)


def _validate_evidence(evidence: OfflineCapabilityEvidence, gate: dict) -> bool:
    if not isinstance(evidence, OfflineCapabilityEvidence):
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_TYPE")
    if evidence.expiry_state not in {"UNKNOWN", "KNOWN"}:
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_EXPIRY_STATE")
    if evidence.expiry_state == "KNOWN":
        if not isinstance(evidence.expires_at_utc, str) or not RFC3339_UTC.fullmatch(evidence.expires_at_utc):
            raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_EXPIRY_FORMAT")
    elif evidence.expires_at_utc is not None:
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_EXPIRY_CONTRADICTION")

    if evidence.state == "STAGED_UNVERIFIED":
        if evidence.evidence_artifact_sha256 is not None or evidence.observed_permissions or evidence.observed_capabilities:
            raise ConnectionProfileHold("HOLD_CONNECTION_UNVERIFIED_EVIDENCE_MUST_BE_EMPTY")
        return False

    if evidence.state != "OFFLINE_EVIDENCE_BOUND":
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_STATE")
    if not isinstance(evidence.evidence_artifact_sha256, str) or not HEX64.fullmatch(evidence.evidence_artifact_sha256):
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_HASH")
    if evidence.observed_permissions != tuple(gate["required_permissions"]):
        raise ConnectionProfileHold("HOLD_CONNECTION_PERMISSION_EVIDENCE_MISMATCH")
    if evidence.observed_capabilities != tuple(gate["required_capabilities"]):
        raise ConnectionProfileHold("HOLD_CONNECTION_CAPABILITY_EVIDENCE_MISMATCH")
    return True


def compile_connection_profile(spec: ConnectionProfileSpec) -> ConnectionProfile:
    if not isinstance(spec, ConnectionProfileSpec):
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_SPEC_TYPE")
    if spec.platform not in EXPECTED_ACTIVE or spec.platform not in _AUTH_REFERENCE_KIND:
        raise ConnectionProfileHold("HOLD_CONNECTION_PLATFORM_NOT_ACTIVE")
    if spec.destination_ref != DESTINATION_REF:
        raise ConnectionProfileHold("HOLD_CONNECTION_REAL_DESTINATION_FORBIDDEN")
    if spec.api_version_ref != API_VERSION_REF:
        raise ConnectionProfileHold("HOLD_CONNECTION_LITERAL_API_VERSION_FORBIDDEN")

    secret_ref = parse_secret_reference(spec.secret_reference)
    gate = static_capability_contract(spec.platform, spec.mode)
    evidence_complete = _validate_evidence(spec.evidence, gate)
    body = {
        "model_version": CONNECTION_PROFILE_MODEL_VERSION,
        "engine_version": CONNECTION_PROFILE_ENGINE_VERSION,
        "platform": spec.platform,
        "mode": spec.mode,
        "auth_reference_kind": _AUTH_REFERENCE_KIND[spec.platform],
        "secret_reference": secret_ref.canonical,
        "secret_reference_scheme": secret_ref.scheme,
        "destination_ref": spec.destination_ref,
        "api_version_ref": spec.api_version_ref,
        "required_permissions": list(gate["required_permissions"]),
        "required_capabilities": list(gate["required_capabilities"]),
        "evidence": asdict(spec.evidence),
        "offline_contract_evidence_complete": evidence_complete,
        "real_entitlement_asserted": False,
        "secret_resolution_allowed": False,
        "environment_read_allowed": False,
        "keychain_read_allowed": False,
        "network_allowed": False,
        "real_account_lookup_allowed": False,
        "account_connection_allowed": False,
        "publish_execution_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": "STAGED_SECRET_REFERENCE_ONLY",
    }
    profile_hash = _hash(body)
    profile = ConnectionProfile(
        profile_id="mcp_" + profile_hash[:24],
        profile_hash=profile_hash,
        model_version=CONNECTION_PROFILE_MODEL_VERSION,
        engine_version=CONNECTION_PROFILE_ENGINE_VERSION,
        platform=spec.platform,
        mode=spec.mode,
        auth_reference_kind=_AUTH_REFERENCE_KIND[spec.platform],
        secret_reference=secret_ref.canonical,
        secret_reference_scheme=secret_ref.scheme,
        destination_ref=spec.destination_ref,
        api_version_ref=spec.api_version_ref,
        required_permissions=tuple(gate["required_permissions"]),
        required_capabilities=tuple(gate["required_capabilities"]),
        evidence=spec.evidence,
        offline_contract_evidence_complete=evidence_complete,
    )
    validate_connection_profile(profile)
    return profile


def validate_connection_profile(profile: ConnectionProfile) -> None:
    if not isinstance(profile, ConnectionProfile):
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_TYPE")
    if profile.model_version != CONNECTION_PROFILE_MODEL_VERSION or profile.engine_version != CONNECTION_PROFILE_ENGINE_VERSION:
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_VERSION")
    if profile.platform not in EXPECTED_ACTIVE or profile.platform not in _AUTH_REFERENCE_KIND:
        raise ConnectionProfileHold("HOLD_CONNECTION_PLATFORM_NOT_ACTIVE")
    secret_ref = parse_secret_reference(profile.secret_reference)
    if secret_ref.scheme != profile.secret_reference_scheme:
        raise ConnectionProfileHold("HOLD_SECRET_REFERENCE_SCHEME_MISMATCH")
    if profile.auth_reference_kind != _AUTH_REFERENCE_KIND[profile.platform]:
        raise ConnectionProfileHold("HOLD_CONNECTION_AUTH_REFERENCE_KIND_MISMATCH")
    if profile.destination_ref != DESTINATION_REF or profile.api_version_ref != API_VERSION_REF:
        raise ConnectionProfileHold("HOLD_CONNECTION_SYMBOLIC_BINDING_DRIFT")
    gate = static_capability_contract(profile.platform, profile.mode)
    if profile.required_permissions != tuple(gate["required_permissions"]):
        raise ConnectionProfileHold("HOLD_CONNECTION_REQUIRED_PERMISSIONS_DRIFT")
    if profile.required_capabilities != tuple(gate["required_capabilities"]):
        raise ConnectionProfileHold("HOLD_CONNECTION_REQUIRED_CAPABILITIES_DRIFT")
    evidence_complete = _validate_evidence(profile.evidence, gate)
    if profile.offline_contract_evidence_complete is not evidence_complete:
        raise ConnectionProfileHold("HOLD_CONNECTION_EVIDENCE_COMPLETENESS_DRIFT")
    if any((
        profile.real_entitlement_asserted,
        profile.secret_resolution_allowed,
        profile.environment_read_allowed,
        profile.keychain_read_allowed,
        profile.network_allowed,
        profile.real_account_lookup_allowed,
        profile.account_connection_allowed,
        profile.publish_execution_allowed,
        profile.external_write_allowed,
        profile.deploy_allowed,
    )) or not profile.global_kill_switch_required or not profile.live_reverification_required:
        raise ConnectionProfileHold("HOLD_CONNECTION_EXTERNAL_AUTHORITY_FORBIDDEN")
    if profile.state != "STAGED_SECRET_REFERENCE_ONLY":
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_STATE")
    body = profile.to_dict()
    body.pop("profile_id")
    body.pop("profile_hash")
    expected_hash = _hash(body)
    if not HEX64.fullmatch(profile.profile_hash) or profile.profile_hash != expected_hash:
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_HASH_MISMATCH")
    if profile.profile_id != "mcp_" + profile.profile_hash[:24]:
        raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_ID_MISMATCH")


class SecretReferenceVault:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT PRIMARY KEY,
                    profile_hash TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    secret_reference TEXT NOT NULL,
                    profile_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    request_id TEXT PRIMARY KEY,
                    event_hash TEXT NOT NULL UNIQUE,
                    event_time_utc TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(profile_id)
                );
                """
            )

    def _connect(self):
        return sqlite3.connect(self.path)

    def stage(self, profile: ConnectionProfile, *, request_id: str, event_time_utc: str) -> VaultReceipt:
        validate_connection_profile(profile)
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", request_id):
            raise ConnectionProfileHold("HOLD_CONNECTION_REQUEST_ID")
        if not isinstance(event_time_utc, str) or not RFC3339_UTC.fullmatch(event_time_utc):
            raise ConnectionProfileHold("HOLD_CONNECTION_EVENT_TIME")
        profile_json = canonical_json(profile.to_dict())
        payload_hash = sha256(profile_json.encode("utf-8")).hexdigest()
        event_body = {
            "schema_version": VAULT_SCHEMA_VERSION,
            "request_id": request_id,
            "event_time_utc": event_time_utc,
            "profile_id": profile.profile_id,
            "profile_hash": profile.profile_hash,
            "payload_hash": payload_hash,
            "event_type": "STAGE_SECRET_REFERENCE_PROFILE",
        }
        event_hash = _hash(event_body)
        with self._connect() as conn:
            existing_event = conn.execute(
                "SELECT event_hash, profile_hash FROM events WHERE request_id = ?", (request_id,)
            ).fetchone()
            if existing_event is not None:
                if existing_event != (event_hash, profile.profile_hash):
                    raise ConnectionProfileHold("HOLD_CONNECTION_IDEMPOTENCY_CONFLICT")
                return VaultReceipt(
                    request_id=request_id,
                    profile_id=profile.profile_id,
                    profile_hash=profile.profile_hash,
                    event_hash=event_hash,
                    event_time_utc=event_time_utc,
                    stored_new_profile=False,
                )

            existing_profile = conn.execute(
                "SELECT profile_hash, profile_json FROM profiles WHERE profile_id = ?", (profile.profile_id,)
            ).fetchone()
            stored_new = existing_profile is None
            if existing_profile is not None and existing_profile != (profile.profile_hash, profile_json):
                raise ConnectionProfileHold("HOLD_CONNECTION_PROFILE_IMMUTABILITY")
            if stored_new:
                conn.execute(
                    "INSERT INTO profiles(profile_id, profile_hash, platform, mode, secret_reference, profile_json) VALUES(?,?,?,?,?,?)",
                    (profile.profile_id, profile.profile_hash, profile.platform, profile.mode, profile.secret_reference, profile_json),
                )
            conn.execute(
                "INSERT INTO events(request_id, event_hash, event_time_utc, profile_id, profile_hash, payload_hash, event_type) VALUES(?,?,?,?,?,?,?)",
                (
                    request_id,
                    event_hash,
                    event_time_utc,
                    profile.profile_id,
                    profile.profile_hash,
                    payload_hash,
                    "STAGE_SECRET_REFERENCE_PROFILE",
                ),
            )
        return VaultReceipt(
            request_id=request_id,
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            event_hash=event_hash,
            event_time_utc=event_time_utc,
            stored_new_profile=stored_new,
        )

    def read_profile(self, profile_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT profile_json FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def event_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])
