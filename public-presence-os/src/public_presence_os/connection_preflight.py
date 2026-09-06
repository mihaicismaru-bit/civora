from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3

from .connection_profiles import (
    ConnectionProfile,
    SecretReferenceVault,
    VaultReceipt,
    validate_connection_profile,
)
from .control import canonical_json
from .meta_adapters import OfflineRequestPlan, validate_request_plan

PREFLIGHT_MODEL_VERSION = "PPOS_META_CONNECTION_SYNTHETIC_PREFLIGHT_V1"
PREFLIGHT_ENGINE_VERSION = "ppos-meta-connection-synthetic-preflight-v1.0.0"
PREFLIGHT_LEDGER_SCHEMA_VERSION = "PPOS_META_CONNECTION_PREFLIGHT_LEDGER_V1"
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PASS_STATE = "PASS_SYNTHETIC_PREFLIGHT_ONLY"


class ConnectionPreflightError(ValueError):
    pass


class ConnectionPreflightHold(ConnectionPreflightError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SyntheticProvisioningReadback:
    profile_id: str
    profile_hash: str
    vault_event_hash: str
    stored_profile_payload_sha256: str
    platform: str
    mode: str
    auth_reference_kind: str
    required_permissions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    destination_binding_state: str = "SYMBOLIC_DESTINATION_ONLY"
    api_version_binding_state: str = "SYMBOLIC_API_VERSION_ONLY"
    entitlement_state: str = "SYNTHETIC_CONTRACT_ONLY"
    secret_material_observed: bool = False
    real_destination_observed: bool = False
    literal_api_version_observed: bool = False
    network_observed: bool = False
    account_connection_observed: bool = False
    external_write_observed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SyntheticPreflightReceipt:
    request_id: str
    receipt_id: str
    receipt_hash: str
    event_time_utc: str
    model_version: str
    engine_version: str
    plan_id: str
    plan_hash: str
    profile_id: str
    profile_hash: str
    readback: SyntheticProvisioningReadback
    checks: tuple[str, ...]
    offline_contract_evidence_complete: bool
    synthetic_contract_pass: bool
    live_entitlement_verified: bool = False
    secret_resolved: bool = False
    network_attempted: bool = False
    account_connected: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    live_transport_ready: bool = False
    pilot_publish_ready: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = PASS_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["readback"] = self.readback.to_dict()
        return data


@dataclass(frozen=True)
class PreflightLedgerReceipt:
    request_id: str
    preflight_receipt_id: str
    preflight_receipt_hash: str
    event_hash: str
    event_time_utc: str
    stored_new_receipt: bool
    state: str = "LOCAL_SYNTHETIC_PREFLIGHT_RECORDED"
    network_attempted: bool = False
    account_connected: bool = False
    external_write_performed: bool = False


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _payload_hash(value: dict) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_vault_receipt(receipt: VaultReceipt) -> None:
    if not isinstance(receipt, VaultReceipt):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_RECEIPT_TYPE")
    if not HEX64.fullmatch(receipt.profile_hash) or not HEX64.fullmatch(receipt.event_hash):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_RECEIPT_HASH")
    if receipt.state != "LOCAL_REFERENCE_STAGED":
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_RECEIPT_STATE")
    if any((
        receipt.secret_resolved,
        receipt.network_attempted,
        receipt.account_connected,
        receipt.external_write_performed,
    )):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_EXTERNAL_ACTION_FORBIDDEN")


def _build_readback(
    plan: OfflineRequestPlan,
    profile: ConnectionProfile,
    vault_receipt: VaultReceipt,
    stored_profile: dict,
) -> SyntheticProvisioningReadback:
    if not isinstance(stored_profile, dict):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_PROFILE_READBACK_MISSING")
    expected_profile = profile.to_dict()
    if canonical_json(stored_profile) != canonical_json(expected_profile):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_PROFILE_READBACK_DRIFT")
    if vault_receipt.profile_id != profile.profile_id or vault_receipt.profile_hash != profile.profile_hash:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_PROFILE_BINDING_MISMATCH")
    return SyntheticProvisioningReadback(
        profile_id=profile.profile_id,
        profile_hash=profile.profile_hash,
        vault_event_hash=vault_receipt.event_hash,
        stored_profile_payload_sha256=_payload_hash(stored_profile),
        platform=plan.platform,
        mode=plan.mode,
        auth_reference_kind=plan.auth_reference_kind,
        required_permissions=plan.required_permissions,
        required_capabilities=plan.required_capabilities,
    )


def compile_synthetic_preflight(
    plan: OfflineRequestPlan,
    profile: ConnectionProfile,
    *,
    vault: SecretReferenceVault,
    vault_receipt: VaultReceipt,
    request_id: str,
    event_time_utc: str,
) -> SyntheticPreflightReceipt:
    if not isinstance(vault, SecretReferenceVault):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_VAULT_TYPE")
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_REQUEST_ID")
    if not isinstance(event_time_utc, str) or not RFC3339_UTC.fullmatch(event_time_utc):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_EVENT_TIME")

    validate_request_plan(plan)
    validate_connection_profile(profile)
    _validate_vault_receipt(vault_receipt)

    if not profile.offline_contract_evidence_complete:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_OFFLINE_EVIDENCE_INCOMPLETE")
    if profile.real_entitlement_asserted:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_LIVE_ENTITLEMENT_ASSERTION_FORBIDDEN")

    exact_pairs = (
        ("platform", plan.platform, profile.platform),
        ("mode", plan.mode, profile.mode),
        ("auth_reference_kind", plan.auth_reference_kind, profile.auth_reference_kind),
        ("required_permissions", plan.required_permissions, profile.required_permissions),
        ("required_capabilities", plan.required_capabilities, profile.required_capabilities),
    )
    checks: list[str] = []
    for name, plan_value, profile_value in exact_pairs:
        if plan_value != profile_value:
            raise ConnectionPreflightHold(f"HOLD_PREFLIGHT_{name.upper()}_MISMATCH")
        checks.append(f"{name}_exact")

    stored_profile = vault.read_profile(profile.profile_id)
    readback = _build_readback(plan, profile, vault_receipt, stored_profile)
    checks.extend((
        "vault_profile_hash_exact",
        "vault_event_hash_bound",
        "profile_readback_exact",
        "offline_contract_evidence_complete",
        "symbolic_destination_only",
        "symbolic_api_version_only",
        "no_secret_resolution",
        "no_network",
        "no_account_connection",
        "no_publish",
        "no_external_write",
        "no_deploy",
        "live_reverification_required",
    ))

    body = {
        "request_id": request_id,
        "event_time_utc": event_time_utc,
        "model_version": PREFLIGHT_MODEL_VERSION,
        "engine_version": PREFLIGHT_ENGINE_VERSION,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "profile_id": profile.profile_id,
        "profile_hash": profile.profile_hash,
        "readback": readback.to_dict(),
        "checks": checks,
        "offline_contract_evidence_complete": True,
        "synthetic_contract_pass": True,
        "live_entitlement_verified": False,
        "secret_resolved": False,
        "network_attempted": False,
        "account_connected": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "live_transport_ready": False,
        "pilot_publish_ready": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": PASS_STATE,
    }
    receipt_hash = _hash(body)
    receipt = SyntheticPreflightReceipt(
        request_id=request_id,
        receipt_id="mcpf_" + receipt_hash[:24],
        receipt_hash=receipt_hash,
        event_time_utc=event_time_utc,
        model_version=PREFLIGHT_MODEL_VERSION,
        engine_version=PREFLIGHT_ENGINE_VERSION,
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        profile_id=profile.profile_id,
        profile_hash=profile.profile_hash,
        readback=readback,
        checks=tuple(checks),
        offline_contract_evidence_complete=True,
        synthetic_contract_pass=True,
    )
    validate_synthetic_preflight_receipt(receipt)
    return receipt


def validate_synthetic_preflight_receipt(receipt: SyntheticPreflightReceipt) -> None:
    if not isinstance(receipt, SyntheticPreflightReceipt):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_TYPE")
    if receipt.model_version != PREFLIGHT_MODEL_VERSION or receipt.engine_version != PREFLIGHT_ENGINE_VERSION:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_VERSION")
    if not REQUEST_ID.fullmatch(receipt.request_id) or not RFC3339_UTC.fullmatch(receipt.event_time_utc):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_METADATA")
    if not HEX64.fullmatch(receipt.plan_hash) or not HEX64.fullmatch(receipt.profile_hash):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_BINDING_HASH")
    if receipt.state != PASS_STATE or not receipt.synthetic_contract_pass or not receipt.offline_contract_evidence_complete:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_STATE")
    if any((
        receipt.live_entitlement_verified,
        receipt.secret_resolved,
        receipt.network_attempted,
        receipt.account_connected,
        receipt.publish_attempted,
        receipt.external_write_performed,
        receipt.deploy_performed,
        receipt.live_transport_ready,
        receipt.pilot_publish_ready,
    )):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not receipt.global_kill_switch_required or not receipt.live_reverification_required:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_SAFETY_GATE_DRIFT")
    readback = receipt.readback
    if any((
        readback.secret_material_observed,
        readback.real_destination_observed,
        readback.literal_api_version_observed,
        readback.network_observed,
        readback.account_connection_observed,
        readback.external_write_observed,
    )):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_READBACK_EXTERNAL_ACTION")
    if readback.entitlement_state != "SYNTHETIC_CONTRACT_ONLY":
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_READBACK_ENTITLEMENT_STATE")
    if not HEX64.fullmatch(readback.profile_hash) or not HEX64.fullmatch(readback.vault_event_hash):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_READBACK_HASH")
    if not HEX64.fullmatch(readback.stored_profile_payload_sha256):
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_READBACK_PAYLOAD_HASH")
    body = receipt.to_dict()
    body.pop("receipt_id")
    body.pop("receipt_hash")
    expected_hash = _hash(body)
    if receipt.receipt_hash != expected_hash:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_HASH_MISMATCH")
    if receipt.receipt_id != "mcpf_" + receipt.receipt_hash[:24]:
        raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_ID_MISMATCH")


class SyntheticPreflightLedger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    plan_hash TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    request_id TEXT PRIMARY KEY,
                    event_hash TEXT NOT NULL UNIQUE,
                    event_time_utc TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id)
                );
                """
            )

    def _connect(self):
        return sqlite3.connect(self.path)

    def record(self, receipt: SyntheticPreflightReceipt) -> PreflightLedgerReceipt:
        validate_synthetic_preflight_receipt(receipt)
        receipt_json = canonical_json(receipt.to_dict())
        event_body = {
            "schema_version": PREFLIGHT_LEDGER_SCHEMA_VERSION,
            "request_id": receipt.request_id,
            "event_time_utc": receipt.event_time_utc,
            "receipt_id": receipt.receipt_id,
            "receipt_hash": receipt.receipt_hash,
            "event_type": "RECORD_SYNTHETIC_CONNECTION_PREFLIGHT",
        }
        event_hash = _hash(event_body)
        with self._connect() as conn:
            existing_event = conn.execute(
                "SELECT event_hash, receipt_hash FROM events WHERE request_id = ?", (receipt.request_id,)
            ).fetchone()
            if existing_event is not None:
                if existing_event != (event_hash, receipt.receipt_hash):
                    raise ConnectionPreflightHold("HOLD_PREFLIGHT_IDEMPOTENCY_CONFLICT")
                return PreflightLedgerReceipt(
                    request_id=receipt.request_id,
                    preflight_receipt_id=receipt.receipt_id,
                    preflight_receipt_hash=receipt.receipt_hash,
                    event_hash=event_hash,
                    event_time_utc=receipt.event_time_utc,
                    stored_new_receipt=False,
                )

            existing_receipt = conn.execute(
                "SELECT receipt_hash, receipt_json FROM receipts WHERE receipt_id = ?", (receipt.receipt_id,)
            ).fetchone()
            stored_new = existing_receipt is None
            if existing_receipt is not None and existing_receipt != (receipt.receipt_hash, receipt_json):
                raise ConnectionPreflightHold("HOLD_PREFLIGHT_RECEIPT_IMMUTABILITY")
            if stored_new:
                conn.execute(
                    "INSERT INTO receipts(receipt_id, receipt_hash, plan_hash, profile_hash, receipt_json) VALUES(?,?,?,?,?)",
                    (receipt.receipt_id, receipt.receipt_hash, receipt.plan_hash, receipt.profile_hash, receipt_json),
                )
            conn.execute(
                "INSERT INTO events(request_id, event_hash, event_time_utc, receipt_id, receipt_hash, event_type) VALUES(?,?,?,?,?,?)",
                (
                    receipt.request_id,
                    event_hash,
                    receipt.event_time_utc,
                    receipt.receipt_id,
                    receipt.receipt_hash,
                    "RECORD_SYNTHETIC_CONNECTION_PREFLIGHT",
                ),
            )
        return PreflightLedgerReceipt(
            request_id=receipt.request_id,
            preflight_receipt_id=receipt.receipt_id,
            preflight_receipt_hash=receipt.receipt_hash,
            event_hash=event_hash,
            event_time_utc=receipt.event_time_utc,
            stored_new_receipt=stored_new,
        )

    def read_receipt(self, receipt_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT receipt_json FROM receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def event_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])
