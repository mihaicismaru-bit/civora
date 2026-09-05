from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re

HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_CHECKPOINTS = tuple(f"CP{i}" for i in range(23, 30))


@dataclass(frozen=True)
class ImportRegistryValidation:
    ok: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_registry(registry: dict) -> ImportRegistryValidation:
    checks: list[str] = []
    errors: list[str] = []

    if registry.get("schema_version") == "PPOS_CHECKPOINT_SOURCE_REGISTRY_V1":
        checks.append("schema_version")
    else:
        errors.append("schema_version")

    authority = registry.get("authority", {})
    if (
        authority.get("checkpoint_evidence") == "GOOGLE_DRIVE"
        and authority.get("executable_source") == "GITHUB"
        and authority.get("import_policy") == "EXACT_SOURCE_BYTES_REQUIRED"
    ):
        checks.append("authority_split")
    else:
        errors.append("authority_split")

    packages = registry.get("packages", [])
    checkpoints = tuple(package.get("checkpoint") for package in packages)
    if checkpoints == EXPECTED_CHECKPOINTS:
        checks.append("checkpoint_range_exact")
    else:
        errors.append("checkpoint_range_exact")

    if len(checkpoints) == len(set(checkpoints)):
        checks.append("checkpoint_unique")
    else:
        errors.append("checkpoint_duplicate")

    for package in packages:
        checkpoint = package.get("checkpoint", "UNKNOWN")
        if not package.get("drive_document_id") or not package.get("drive_revision_id"):
            errors.append(f"{checkpoint}:drive_binding_missing")
        else:
            checks.append(f"{checkpoint}:drive_revision_bound")

        if package.get("checkpoint_evidence_state") != "BOUND_TO_EXACT_DRIVE_REVISION":
            errors.append(f"{checkpoint}:evidence_not_exact_revision")

        if package.get("checkpoint_state") != "PASS_CLOSED_PRE_PILOT":
            errors.append(f"{checkpoint}:checkpoint_not_pass")

        source_available = package.get("source_bytes_available") is True
        import_eligible = package.get("import_eligible") is True
        archive_hash = package.get("source_archive_sha256")
        paths = package.get("expected_source_paths") or []

        if source_available:
            if not (isinstance(archive_hash, str) and HEX64.fullmatch(archive_hash)):
                errors.append(f"{checkpoint}:source_hash_required")
            if not paths:
                errors.append(f"{checkpoint}:source_paths_required")
            if not import_eligible:
                errors.append(f"{checkpoint}:available_source_must_be_eligible")
        else:
            if archive_hash is not None:
                errors.append(f"{checkpoint}:unavailable_source_cannot_have_hash")
            if import_eligible:
                errors.append(f"{checkpoint}:unavailable_source_cannot_be_eligible")
            if package.get("import_state") != "HOLD_SOURCE_BYTES_UNAVAILABLE":
                errors.append(f"{checkpoint}:hold_state_required")
            checks.append(f"{checkpoint}:fail_closed_source_hold")

    return ImportRegistryValidation(not errors, tuple(checks), tuple(errors))


def import_candidates(registry: dict) -> tuple[str, ...]:
    result = validate_registry(registry)
    if not result.ok:
        raise ValueError("invalid import registry: " + ",".join(result.errors))
    return tuple(
        package["checkpoint"]
        for package in registry["packages"]
        if package["import_eligible"]
    )
