from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authorized_session_request import (
    CHECKPOINT as CP67_CHECKPOINT, DECISION_VALUES, FUTURE_RECEIPT_SCHEMA,
    REQUESTED_SCOPE, REQUIRED_HANDOFF_FIELDS, build_authorized_session_request_packet,
    build_operator_authorization_handoff, compile_live_read_only_probe_authorized_session_request,
    validate_live_read_only_probe_authorized_session_request_contract,
)
from .live_read_only_probe_single_session_harness import compile_live_read_only_probe_single_session_harness

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-session-authorization-receipt-v1.0.0"
STATE = "PASS_CP68_SESSION_AUTHORIZATION_RECEIPT_INTAKE_VALIDATOR_DRY_RUN_LOCAL_ONLY_AUTHORITY_NOT_ACTIVATED_LIVE_HOLD"
CHECKPOINT = "CP68"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP69_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN"
RECEIPT_INPUT_FIELDS = (
    "schema_version","request_id","request_hash","handoff_id","handoff_hash",
    *REQUIRED_HANDOFF_FIELDS,
)
REQUIRED_BLOCKERS = (
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED","HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED","HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED","HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP68_VALIDATED_RECEIPT_IS_NOT_RUNTIME_AUTHORITY",
    "HOLD_CP68_CONTROL_PROMOTION_SEPARATE_UNIT_REQUIRED",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NONCE = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SENSITIVE = {"access_token","refresh_token","client_secret","authorization","authorization_header",
             "password","raw_token","raw_secret","bearer","account_id","page_id",
             "instagram_account_id","threads_user_id"}

class LiveReadOnlyProbeSessionAuthorizationReceiptHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason); self.reason = reason

@dataclass(frozen=True)
class ImmutableSessionAuthorizationReceipt:
    receipt_id: str; receipt_hash: str; cp67_contract_id: str; cp67_contract_hash: str
    request_id: str; request_hash: str; handoff_id: str; handoff_hash: str
    decision: str; scope: str; platform_subset: tuple[str,...]
    valid_from_utc: str; valid_until_utc: str
    human_reference_sha256: str; evidence_sha256: str; nonce_sha256: str
    synthetic_fixture: bool
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    immutable: bool = True
    receipt_shape_validated: bool = True
    runtime_authorization_effective: bool = False
    authority_activated: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    publish_allowed: bool = False
    deploy_allowed: bool = False
    state: str = "VALIDATED_IMMUTABLE_SESSION_AUTHORIZATION_RECEIPT_NO_RUNTIME_AUTHORITY"
    def to_dict(self):
        d=asdict(self); d["platform_subset"]=list(self.platform_subset); return d

@dataclass(frozen=True)
class SessionAuthorizationActivationDryRun:
    dry_run_id: str; dry_run_hash: str; receipt_id: str; receipt_hash: str
    decision: str; platform_subset: tuple[str,...]; outcome: str
    checkpoint: str = CHECKPOINT
    source_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    global_kill_switch_engaged: bool = True
    registry_mutated: bool = False; runtime_policy_mutated: bool = False
    environment_read: bool = False; keychain_read: bool = False; oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False; account_connected: bool = False
    network_attempted: bool = False; live_probe_attempted: bool = False
    publish_attempted: bool = False; external_write_performed: bool = False
    deploy_performed: bool = False; paid_service_used: bool = False
    authority_activated: bool = False; promotion_committed: bool = False
    state: str = "DRY_RUN_ONLY_ZERO_IO_NO_AUTHORITY_ACTIVATION"
    def to_dict(self):
        d=asdict(self); d["platform_subset"]=list(self.platform_subset); return d

@dataclass(frozen=True)
class LiveReadOnlyProbeSessionAuthorizationReceiptContract:
    contract_id: str; contract_hash: str; cp67_contract_id: str; cp67_contract_hash: str
    request_id: str; request_hash: str; handoff_id: str; handoff_hash: str
    receipt_id: str; receipt_hash: str; dry_run_id: str; dry_run_hash: str
    policy_sha256: str; cp67_policy_sha256: str; runtime_policy_sha256: str; module_registry_sha256: str
    active_platforms: tuple[str,...]; blockers: tuple[str,...]; next_unit: str
    model_version: str = MODEL_VERSION; engine_version: str = ENGINE_VERSION
    checkpoint: str = CHECKPOINT; parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    synthetic_submission_validated: bool = True; exact_cp67_binding_validated: bool = True
    immutable_receipt_validated: bool = True; activation_dry_run_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False; authorization_granted: bool = False
    runtime_authorization_effective: bool = False; secret_reference_resolved: bool = False
    environment_read: bool = False; keychain_read: bool = False; oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False; account_connected: bool = False
    network_allowed: bool = False; network_attempted: bool = False
    live_probe_allowed: bool = False; live_probe_attempted: bool = False
    publish_allowed: bool = False; publish_attempted: bool = False
    external_write_allowed: bool = False; external_write_performed: bool = False
    control_plane_promoted: bool = False; deploy_allowed: bool = False; deploy_performed: bool = False
    paid_service_used: bool = False; authority_activated: bool = False; state: str = STATE
    def to_dict(self):
        d=asdict(self); d["active_platforms"]=list(self.active_platforms); d["blockers"]=list(self.blockers); return d

def _hash(v: Any) -> str: return sha256(canonical_json(v).encode()).hexdigest()
def _hex(v: Any) -> bool: return isinstance(v,str) and HEX64.fullmatch(v) is not None
def _without(d: dict,*keys): return {k:v for k,v in d.items() if k not in keys}

def _no_sensitive(v: Any) -> None:
    if isinstance(v,dict):
        for k,x in v.items():
            if str(k).lower() in SENSITIVE: raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_SENSITIVE_FIELD")
            _no_sensitive(x)
    elif isinstance(v,(list,tuple)):
        for x in v: _no_sensitive(x)
    elif isinstance(v,str) and ("://" in v or "bearer " in v.lower() or "authorization:" in v.lower()):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RAW_URL_OR_CREDENTIAL")

def _utc(v: Any) -> datetime:
    if not isinstance(v,str) or UTC.fullmatch(v) is None:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_UTC_INVALID")
    try: return datetime.strptime(v,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as e: raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_UTC_INVALID") from e

def _validate_policy(p: dict) -> None:
    _no_sensitive(p)
    if (p.get("schema_version"),p.get("checkpoint"),p.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT_POLICY_V1",CHECKPOINT,
        "M37_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT"):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_POLICY_IDENTITY")
    if p.get("parent_authorized_session_request_checkpoint") != CP67_CHECKPOINT or p.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_PARENT_DRIFT")
    if tuple(p.get("active_platforms",())) != EXPECTED_ACTIVE or tuple(p.get("required_blockers",())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_SCOPE_OR_BLOCKER_DRIFT")
    if p.get("rollback_target") != CP67_CHECKPOINT or p.get("next_after_cp68") != NEXT_UNIT:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTINUITY_DRIFT")
    i=p.get("receipt_intake",{})
    required=("local_validator_only","exact_cp67_contract_binding_required","exact_cp67_request_binding_required",
      "exact_cp67_handoff_binding_required","exact_field_set_required","canonical_json_required",
      "sha256_binding_required","immutable_receipt_required","decision_required","scope_exact_match_required",
      "platform_subset_nonempty_required","platform_subset_of_active_lanes_required","canonical_utc_window_required",
      "positive_validity_window_required","human_reference_sha256_required","evidence_sha256_required",
      "nonce_required","nonce_hash_before_persistence_required","raw_nonce_persistence_forbidden",
      "raw_credentials_forbidden","raw_urls_forbidden","real_account_identifiers_forbidden",
      "grant_does_not_activate_runtime_authority","deny_does_not_activate_runtime_authority",
      "secret_resolution_forbidden","environment_read_forbidden","keychain_read_forbidden","oauth_forbidden",
      "real_account_lookup_forbidden","account_connection_forbidden","network_forbidden",
      "live_probe_execution_forbidden","publish_forbidden","external_write_forbidden",
      "control_plane_promotion_forbidden","deploy_forbidden","paid_service_forbidden",
      "global_kill_switch_must_remain_engaged")
    if any(i.get(k) is not True for k in required): raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_GUARD")
    if i.get("receipt_schema_must_equal") != FUTURE_RECEIPT_SCHEMA or tuple(i.get("input_fields",())) != RECEIPT_INPUT_FIELDS:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_SCHEMA")
    if tuple(i.get("decision_values",())) != DECISION_VALUES or i.get("scope_must_equal") != REQUESTED_SCOPE or tuple(i.get("method_allowlist",())) != ("GET",):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_SCOPE")
    d=p.get("activation_dry_run",{})
    if any(d.get(k) is not True for k in ("enabled","local_only","registry_mutation_forbidden","runtime_policy_mutation_forbidden","authority_activation_forbidden","promotion_commit_forbidden","global_kill_switch_must_remain_engaged")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DRY_RUN_GUARD")
    if d.get("grant_outcome") != "VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY" or d.get("deny_outcome") != "HOLD_EXTERNAL_AUTHORIZATION_DENIED":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DRY_RUN_OUTCOME")
    if not p.get("authority") or any(x is not False for x in p["authority"].values()):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_AUTHORITY_NOT_ZERO")
    if p.get("excluded_platforms") != {"LINKEDIN":"HOLD_UNTIL_PRODUCTION_API_ACCESS","X":"EXCLUDED_WHILE_API_IS_PAID","BLUESKY":"HOLD_UNTIL_LOCAL_ROI_TEST_PASSES"}:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DEFERRED_LANE_DRIFT")

def _validate_root(root: Path) -> None:
    runtime=load_json(root/"config/runtime_policy.json"); registry=load_json(root/"config/module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RUNTIME")
    if any(runtime.get(k) is not False for k in ("network_enabled","account_connection_enabled","publish_enabled","deploy_enabled")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RUNTIME_LIVE_BOUNDARY")
    states={r.get("id"):r.get("status") for r in registry.get("modules",[])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTROL_PROMOTION")
    if states.get("M36_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST") != "CP67_AUTHORIZED_SESSION_REQUEST_PACKET_HANDOFF_LOCAL_ONLY_AUTHORIZATION_NOT_GRANTED_LIVE_HOLD":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CP67_STATE")
    if states.get("M37_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT") != "CP68_SESSION_AUTHORIZATION_RECEIPT_INTAKE_VALIDATOR_DRY_RUN_LOCAL_ONLY_AUTHORITY_NOT_ACTIVATED_LIVE_HOLD":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_MODULE_STATE")

def validate_session_authorization_submission(s: dict, cp67, packet, handoff) -> dict:
    validate_live_read_only_probe_authorized_session_request_contract(cp67)
    if set(s) != set(RECEIPT_INPUT_FIELDS): raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_EXACT_FIELDS")
    _no_sensitive(s)
    if s.get("schema_version") != FUTURE_RECEIPT_SCHEMA: raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_SCHEMA")
    if (s.get("request_id"),s.get("request_hash")) != (packet.request_id,packet.request_hash) or (s.get("handoff_id"),s.get("handoff_hash")) != (handoff.handoff_id,handoff.handoff_hash):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_PARENT_BINDING")
    if (cp67.request_id,cp67.request_hash,cp67.handoff_id,cp67.handoff_hash) != (packet.request_id,packet.request_hash,handoff.handoff_id,handoff.handoff_hash):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CP67_BINDING")
    if s.get("decision") not in DECISION_VALUES or s.get("scope") != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DECISION_SCOPE")
    raw=s.get("platform_subset")
    if not isinstance(raw,list) or not raw: raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_PLATFORM_SUBSET")
    subset=tuple(raw)
    if len(set(subset)) != len(subset) or subset != tuple(p for p in EXPECTED_ACTIVE if p in subset) or not set(subset).issubset(set(EXPECTED_ACTIVE)):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_PLATFORM_SUBSET")
    if _utc(s.get("valid_until_utc")) <= _utc(s.get("valid_from_utc")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_VALIDITY_WINDOW")
    if not _hex(s.get("human_reference_sha256")) or not _hex(s.get("evidence_sha256")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_EVIDENCE_HASH")
    if not isinstance(s.get("nonce"),str) or NONCE.fullmatch(s["nonce"]) is None:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_NONCE")
    return {"decision":s["decision"],"scope":s["scope"],"platform_subset":subset,
      "valid_from_utc":s["valid_from_utc"],"valid_until_utc":s["valid_until_utc"],
      "human_reference_sha256":s["human_reference_sha256"],"evidence_sha256":s["evidence_sha256"],
      "nonce_sha256":sha256(s["nonce"].encode()).hexdigest()}

def compile_immutable_session_authorization_receipt(cp67,packet,handoff,submission:dict,*,synthetic_fixture:bool):
    n=validate_session_authorization_submission(submission,cp67,packet,handoff)
    body={"cp67_contract_id":cp67.contract_id,"cp67_contract_hash":cp67.contract_hash,
      "request_id":packet.request_id,"request_hash":packet.request_hash,"handoff_id":handoff.handoff_id,
      "handoff_hash":handoff.handoff_hash,"decision":n["decision"],"scope":n["scope"],
      "platform_subset":list(n["platform_subset"]),"valid_from_utc":n["valid_from_utc"],
      "valid_until_utc":n["valid_until_utc"],"human_reference_sha256":n["human_reference_sha256"],
      "evidence_sha256":n["evidence_sha256"],"nonce_sha256":n["nonce_sha256"],
      "synthetic_fixture":synthetic_fixture,"checkpoint":CHECKPOINT,"parent_control_checkpoint":PARENT_CONTROL_CHECKPOINT,
      "immutable":True,"receipt_shape_validated":True,"runtime_authorization_effective":False,
      "authority_activated":False,"network_allowed":False,"live_probe_allowed":False,"publish_allowed":False,
      "deploy_allowed":False,"state":"VALIDATED_IMMUTABLE_SESSION_AUTHORIZATION_RECEIPT_NO_RUNTIME_AUTHORITY"}
    h=_hash(body); body["platform_subset"]=tuple(body["platform_subset"])
    r=ImmutableSessionAuthorizationReceipt(receipt_id=f"cp68_receipt_{h[:24]}",receipt_hash=h,**body)
    validate_immutable_session_authorization_receipt(r,cp67); return r

def validate_immutable_session_authorization_receipt(r,cp67) -> None:
    validate_live_read_only_probe_authorized_session_request_contract(cp67)
    if (r.cp67_contract_id,r.cp67_contract_hash,r.request_id,r.request_hash,r.handoff_id,r.handoff_hash) != (cp67.contract_id,cp67.contract_hash,cp67.request_id,cp67.request_hash,cp67.handoff_id,cp67.handoff_hash):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_BINDING")
    if r.decision not in DECISION_VALUES or r.scope != REQUESTED_SCOPE or not r.platform_subset:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_SCOPE")
    if any(getattr(r,k) is not False for k in ("runtime_authorization_effective","authority_activated","network_allowed","live_probe_allowed","publish_allowed","deploy_allowed")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_AUTHORITY")
    if not all(_hex(x) for x in (r.receipt_hash,r.cp67_contract_hash,r.request_hash,r.handoff_hash,r.human_reference_sha256,r.evidence_sha256,r.nonce_sha256)):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_DIGEST")
    h=_hash(_without(r.to_dict(),"receipt_id","receipt_hash"))
    if r.receipt_hash != h or r.receipt_id != f"cp68_receipt_{h[:24]}":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_RECEIPT_HASH")

def build_activation_dry_run(r,cp67):
    validate_immutable_session_authorization_receipt(r,cp67)
    outcome="VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY" if r.decision=="GRANT" else "HOLD_EXTERNAL_AUTHORIZATION_DENIED"
    body={"receipt_id":r.receipt_id,"receipt_hash":r.receipt_hash,"decision":r.decision,
      "platform_subset":list(r.platform_subset),"outcome":outcome,"checkpoint":CHECKPOINT,
      "source_control_checkpoint":PARENT_CONTROL_CHECKPOINT,"global_kill_switch_engaged":True,
      "registry_mutated":False,"runtime_policy_mutated":False,"environment_read":False,"keychain_read":False,
      "oauth_attempted":False,"real_account_lookup_attempted":False,"account_connected":False,
      "network_attempted":False,"live_probe_attempted":False,"publish_attempted":False,
      "external_write_performed":False,"deploy_performed":False,"paid_service_used":False,
      "authority_activated":False,"promotion_committed":False,"state":"DRY_RUN_ONLY_ZERO_IO_NO_AUTHORITY_ACTIVATION"}
    h=_hash(body); body["platform_subset"]=tuple(body["platform_subset"])
    d=SessionAuthorizationActivationDryRun(dry_run_id=f"cp68_dryrun_{h[:24]}",dry_run_hash=h,**body)
    validate_activation_dry_run(d,r); return d

def validate_activation_dry_run(d,r) -> None:
    expected="VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY" if r.decision=="GRANT" else "HOLD_EXTERNAL_AUTHORIZATION_DENIED"
    if (d.receipt_id,d.receipt_hash,d.decision,d.platform_subset,d.outcome) != (r.receipt_id,r.receipt_hash,r.decision,r.platform_subset,expected):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DRY_RUN_BINDING")
    if not d.global_kill_switch_engaged or any(getattr(d,k) is not False for k in ("registry_mutated","runtime_policy_mutated","environment_read","keychain_read","oauth_attempted","real_account_lookup_attempted","account_connected","network_attempted","live_probe_attempted","publish_attempted","external_write_performed","deploy_performed","paid_service_used","authority_activated","promotion_committed")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DRY_RUN_SIDE_EFFECT")
    h=_hash(_without(d.to_dict(),"dry_run_id","dry_run_hash"))
    if d.dry_run_hash != h or d.dry_run_id != f"cp68_dryrun_{h[:24]}":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_DRY_RUN_HASH")

def _synthetic(packet,handoff):
    return {"schema_version":FUTURE_RECEIPT_SCHEMA,"request_id":packet.request_id,"request_hash":packet.request_hash,
      "handoff_id":handoff.handoff_id,"handoff_hash":handoff.handoff_hash,"decision":"GRANT",
      "scope":REQUESTED_SCOPE,"platform_subset":list(EXPECTED_ACTIVE),"valid_from_utc":"2030-01-01T00:00:00Z",
      "valid_until_utc":"2030-01-01T01:00:00Z","human_reference_sha256":sha256(b"cp68-human").hexdigest(),
      "evidence_sha256":sha256(b"cp68-evidence").hexdigest(),"nonce":"cp68-synthetic-nonce-0001"}

def compile_live_read_only_probe_session_authorization_receipt(root:Path,policy:dict):
    root=root.resolve(); _validate_policy(policy); _validate_root(root)
    cp67p=root/"config/live_read_only_probe_authorized_session_request_policy.json"
    cp67=compile_live_read_only_probe_authorized_session_request(root,load_json(cp67p))
    cp66=compile_live_read_only_probe_single_session_harness(root,load_json(root/"config/live_read_only_probe_single_session_harness_policy.json"))
    packet=build_authorized_session_request_packet(cp66); handoff=build_operator_authorization_handoff(packet,cp66)
    if (cp67.request_id,cp67.request_hash,cp67.handoff_id,cp67.handoff_hash)!=(packet.request_id,packet.request_hash,handoff.handoff_id,handoff.handoff_hash):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_REBUILD_BINDING")
    receipt=compile_immutable_session_authorization_receipt(cp67,packet,handoff,_synthetic(packet,handoff),synthetic_fixture=True)
    dry=build_activation_dry_run(receipt,cp67)
    pp=root/"config/live_read_only_probe_session_authorization_receipt_policy.json"; rp=root/"config/runtime_policy.json"; mr=root/"config/module_registry.json"
    body={"cp67_contract_id":cp67.contract_id,"cp67_contract_hash":cp67.contract_hash,
      "request_id":packet.request_id,"request_hash":packet.request_hash,"handoff_id":handoff.handoff_id,"handoff_hash":handoff.handoff_hash,
      "receipt_id":receipt.receipt_id,"receipt_hash":receipt.receipt_hash,"dry_run_id":dry.dry_run_id,"dry_run_hash":dry.dry_run_hash,
      "policy_sha256":sha256(pp.read_bytes()).hexdigest(),"cp67_policy_sha256":sha256(cp67p.read_bytes()).hexdigest(),
      "runtime_policy_sha256":sha256(rp.read_bytes()).hexdigest(),"module_registry_sha256":sha256(mr.read_bytes()).hexdigest(),
      "active_platforms":list(EXPECTED_ACTIVE),"blockers":list(REQUIRED_BLOCKERS),"next_unit":NEXT_UNIT}
    defaults={"model_version":MODEL_VERSION,"engine_version":ENGINE_VERSION,"checkpoint":CHECKPOINT,
      "parent_control_checkpoint":PARENT_CONTROL_CHECKPOINT,"synthetic_submission_validated":True,
      "exact_cp67_binding_validated":True,"immutable_receipt_validated":True,"activation_dry_run_validated":True,
      "global_kill_switch_engaged":True,"external_authorization_ingested":False,"authorization_granted":False,
      "runtime_authorization_effective":False,"secret_reference_resolved":False,"environment_read":False,"keychain_read":False,
      "oauth_attempted":False,"real_account_lookup_attempted":False,"account_connected":False,"network_allowed":False,
      "network_attempted":False,"live_probe_allowed":False,"live_probe_attempted":False,"publish_allowed":False,
      "publish_attempted":False,"external_write_allowed":False,"external_write_performed":False,"control_plane_promoted":False,
      "deploy_allowed":False,"deploy_performed":False,"paid_service_used":False,"authority_activated":False,"state":STATE}
    body.update(defaults); h=_hash(body); body["active_platforms"]=EXPECTED_ACTIVE; body["blockers"]=REQUIRED_BLOCKERS
    c=LiveReadOnlyProbeSessionAuthorizationReceiptContract(contract_id=f"cp68_contract_{h[:24]}",contract_hash=h,**body)
    validate_live_read_only_probe_session_authorization_receipt_contract(c); return c

def validate_live_read_only_probe_session_authorization_receipt_contract(c) -> None:
    if (c.model_version,c.engine_version,c.checkpoint,c.parent_control_checkpoint,c.state,c.next_unit)!=(MODEL_VERSION,ENGINE_VERSION,CHECKPOINT,PARENT_CONTROL_CHECKPOINT,STATE,NEXT_UNIT):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_IDENTITY")
    if c.active_platforms != EXPECTED_ACTIVE or c.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_SCOPE")
    if any(getattr(c,k) is not True for k in ("synthetic_submission_validated","exact_cp67_binding_validated","immutable_receipt_validated","activation_dry_run_validated","global_kill_switch_engaged")):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_GUARD")
    falses=("external_authorization_ingested","authorization_granted","runtime_authorization_effective","secret_reference_resolved","environment_read","keychain_read","oauth_attempted","real_account_lookup_attempted","account_connected","network_allowed","network_attempted","live_probe_allowed","live_probe_attempted","publish_allowed","publish_attempted","external_write_allowed","external_write_performed","control_plane_promoted","deploy_allowed","deploy_performed","paid_service_used","authority_activated")
    if any(getattr(c,k) is not False for k in falses): raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_AUTHORITY")
    if not all(_hex(x) for x in (c.contract_hash,c.cp67_contract_hash,c.request_hash,c.handoff_hash,c.receipt_hash,c.dry_run_hash,c.policy_sha256,c.cp67_policy_sha256,c.runtime_policy_sha256,c.module_registry_sha256)):
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_DIGEST")
    h=_hash(_without(c.to_dict(),"contract_id","contract_hash"))
    if c.contract_hash != h or c.contract_id != f"cp68_contract_{h[:24]}":
        raise LiveReadOnlyProbeSessionAuthorizationReceiptHold("HOLD_CP68_CONTRACT_HASH")
