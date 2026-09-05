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
        "src/public_presence_os/control.py","src/public_presence_os/cli.py",
        "scripts/build_release.py","tests/test_productization.py","docs/CP30_PRODUCTIZATION.md",
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
