from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json, re

EXPECTED_ACTIVE = ("FACEBOOK_PAGE","INSTAGRAM_PROFESSIONAL","THREADS")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    checks: tuple[str,...]
    errors: tuple[str,...]

def validate_policy(policy: dict) -> ValidationResult:
    checks, errors = [], []
    if tuple(policy.get("active_platforms",())) == EXPECTED_ACTIVE:
        checks.append("active_platforms_exact")
    else:
        errors.append("active_platforms_mismatch")
    required_false = (
        "network_enabled","real_accounts_connected","publish_enabled","deploy_enabled",
        "scheduler_write_enabled","queue_mutation_enabled","publisher_write_enabled",
        "account_connection_enabled","external_paid_services_allowed","canva_runtime_dependency"
    )
    for key in required_false:
        if policy.get(key) is False:
            checks.append(f"{key}=false")
        else:
            errors.append(f"{key}_must_be_false")
    if policy.get("global_kill_switch_engaged") is True:
        checks.append("kill_switch_engaged")
    else:
        errors.append("kill_switch_must_be_engaged")
    if policy.get("source_authority") == "GITHUB_EXECUTABLE_SOURCE":
        checks.append("github_source_authority")
    else:
        errors.append("source_authority_invalid")
    if policy.get("evidence_authority") == "GOOGLE_DRIVE_CHECKPOINT_EVIDENCE":
        checks.append("drive_evidence_authority")
    else:
        errors.append("evidence_authority_invalid")
    return ValidationResult(not errors, tuple(checks), tuple(errors))

def build_source_manifest(root: Path) -> dict:
    include = []
    for rel in ("src","config","scripts","tests","docs",".github"):
        base = root/rel
        if base.exists():
            include.extend(p for p in base.rglob("*") if p.is_file())
    rows = {}
    for path in sorted(include, key=lambda p: str(p.relative_to(root))):
        rows[str(path.relative_to(root))] = sha256_file(path)
    return {"schema_version":"PPOS_SOURCE_MANIFEST_V1","files":rows}

def manifest_hash(manifest: dict) -> str:
    return sha256_bytes(canonical_json(manifest).encode("utf-8"))

def validate_repo(root: Path) -> ValidationResult:
    checks, errors = [], []
    expected = [
        "README.md","pyproject.toml","config/runtime_policy.json","config/module_registry.json",
        "config/operator_profile.example.json","config/reimplementation_priority.json","config/visual_identity_policy.json",
        "config/qa_policy.json","config/approval_policy.json","config/queue_policy.json","config/publisher_policy.json",
        "config/analytics_policy.json","config/learning_policy.json","config/meta_adapter_policy.json","config/meta_connection_policy.json",
        "config/meta_preflight_policy.json","config/meta_operator_provisioning_policy.json","config/meta_transport_twin_policy.json",
        "config/meta_read_only_gate_policy.json","config/meta_live_read_only_probe_policy.json",
        "config/meta_offline_evidence_validator_policy.json","config/meta_pilot_readiness_policy.json",
        "config/pilot_package_acceptance_policy.json","config/operator_pilot_handoff_policy.json",
        "config/control_plane_authorization_intake_policy.json","config/authorization_receipt_validator_policy.json",
        "src/public_presence_os/control.py","src/public_presence_os/cli.py","src/public_presence_os/preflight.py",
        "src/public_presence_os/radar.py","src/public_presence_os/rehearsal.py","src/public_presence_os/rights.py",
        "src/public_presence_os/visual.py","src/public_presence_os/qa.py","src/public_presence_os/approval.py",
        "src/public_presence_os/queue.py","src/public_presence_os/publisher.py","src/public_presence_os/analytics.py",
        "src/public_presence_os/learning.py","src/public_presence_os/meta_adapters.py","src/public_presence_os/connection_profiles.py",
        "src/public_presence_os/connection_preflight.py","src/public_presence_os/operator_provisioning.py",
        "src/public_presence_os/meta_transport_twin.py","src/public_presence_os/meta_read_only_gate.py",
        "src/public_presence_os/meta_live_read_only_probe.py","src/public_presence_os/meta_offline_evidence.py",
        "src/public_presence_os/meta_pilot_readiness.py","src/public_presence_os/pilot_package_acceptance.py",
        "src/public_presence_os/operator_pilot_handoff.py","src/public_presence_os/control_plane_authorization_intake.py",
        "src/public_presence_os/authorization_receipt_validator.py",
        "scripts/build_release.py","scripts/preflight.py",
        "tests/test_productization.py","tests/test_preflight.py","tests/test_cp34_radar.py","tests/test_cp39_rights.py",
        "tests/test_cp40_visual.py","tests/test_cp41_qa.py","tests/test_cp42_approval.py","tests/test_cp43_queue.py",
        "tests/test_cp44_publisher.py","tests/test_cp45_analytics.py","tests/test_cp46_learning.py","tests/test_cp50_meta_adapters.py",
        "tests/test_cp51_connection_profiles.py","tests/test_cp52_connection_preflight.py","tests/test_cp53_operator_provisioning.py",
        "tests/test_cp54_meta_transport_twin.py","tests/test_cp55_meta_read_only_gate.py","tests/test_cp56_meta_live_read_only_probe.py",
        "tests/test_cp57_meta_offline_evidence.py","tests/test_cp58_meta_pilot_readiness.py",
        "tests/test_cp59_pilot_package_acceptance.py","tests/test_cp60_operator_pilot_handoff.py",
        "tests/test_cp61_control_plane_authorization_intake.py","tests/test_cp62_authorization_receipt_validator.py",
        "docs/CP30_PRODUCTIZATION.md","docs/OPERATOR_INSTALLATION_CONFIGURATION_RECOVERY.md",
        "docs/CP34_RADAR_MINIMAL_EXECUTABLE_SLICE.md","docs/CP39_IMAGE_RIGHTS_ASSET_PROVENANCE.md",
        "docs/CP40_VISUAL_RENDERER.md","docs/CP41_VISUAL_QA.md","docs/CP42_APPROVAL_DASHBOARD.md","docs/CP43_QUEUE.md",
        "docs/CP44_PUBLISHER.md","docs/CP45_ANALYTICS.md","docs/CP46_LEARNING.md","docs/CP50_META_ADAPTER_OFFLINE_COMPILER.md",
        "docs/CP51_META_CONNECTION_PROFILE_VAULT.md","docs/CP52_META_CONNECTION_SYNTHETIC_PREFLIGHT.md",
        "docs/CP53_META_OPERATOR_PROVISIONING_PACKET.md","docs/CP54_META_TRANSPORT_TEST_TWIN.md",
        "docs/CP55_META_READ_ONLY_CONNECTION_GATE.md","docs/CP56_META_LIVE_READ_ONLY_PROBE_RUNBOOK.md",
        "docs/CP57_META_OFFLINE_EVIDENCE_VALIDATOR_DRY_RUN.md","docs/CP58_META_PILOT_READINESS_AGGREGATOR.md",
        "docs/CP59_PILOT_PACKAGE_COMPLETENESS_ACCEPTANCE.md","docs/CP60_OPERATOR_PILOT_HANDOFF.md",
        "docs/CP61_CONTROL_PLANE_AUTHORIZATION_INTAKE.md","docs/CP62_AUTHORIZATION_RECEIPT_VALIDATOR.md",
        ".github/workflows/public-presence-os-ci.yml",
    ]
    for rel in expected:
        if (root/rel).is_file():
            checks.append(f"present:{rel}")
        else:
            errors.append(f"missing:{rel}")
    if not errors:
        policy_result = validate_policy(load_json(root/"config"/"runtime_policy.json"))
        checks.extend(policy_result.checks); errors.extend(policy_result.errors)
    return ValidationResult(not errors, tuple(checks), tuple(errors))
