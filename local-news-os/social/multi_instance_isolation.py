#!/usr/bin/env python3
"""Fleet-level multi-instance isolation for LOCAL NEWS OS social runtimes.

This module validates the social runtime as a set of independent CIVORA instances.
It composes the existing per-instance publishing-adapter contract, then adds guards
that prevent accidental sharing of repository paths, credential references, media
namespaces, observed-metrics namespaces, and correction targets across instances.

It performs no network calls, reads no credential values, and changes no runtime
state. The output is deterministic and therefore suitable for CI gating.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

import publishing_adapters as adapter_contract

SCHEMA_VERSION = "1.0"
RESOURCE_KEYS = ("outbox", "state", "media", "metrics", "corrections")
REQUIRED_TRUE_POLICIES = (
    "zero_paid_dependency",
    "cross_instance_resource_sharing_forbidden",
    "cross_instance_credentials_forbidden",
    "observed_metrics_instance_scoped",
    "correction_targets_instance_scoped",
)
INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
CREDENTIAL_NAMESPACE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}_$")
LOGICAL_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
CORRECTION_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}:$")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_rel(value: Any) -> str:
    text = _clean(value).replace("//", "/")
    if not text or "\\" in text:
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        return ""
    normalized = path.as_posix()
    if normalized in {"", "."}:
        return ""
    return normalized


def _within(path: str, root: str) -> bool:
    path_value = PurePosixPath(path)
    root_value = PurePosixPath(root)
    return path_value == root_value or root_value in path_value.parents


def _overlap(left: str, right: str) -> bool:
    a = PurePosixPath(left)
    b = PurePosixPath(right)
    return a == b or a in b.parents or b in a.parents


def _isolation_key(instance_id: str, instance_root: str, canonical_domain: str) -> str:
    value = f"{instance_id}|{instance_root}|{canonical_domain}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:20]


def validate_runtime(
    runtime: dict[str, Any],
    *,
    load_json: Callable[[str], dict[str, Any]],
    file_exists: Callable[[str], bool],
) -> dict[str, Any]:
    """Validate a fleet of independent social-publication instances."""
    if not isinstance(runtime, dict):
        raise TypeError("runtime registry must be a mapping")

    errors: list[str] = []
    warnings: list[str] = []
    policy = runtime.get("policy") if isinstance(runtime.get("policy"), dict) else {}
    for key in REQUIRED_TRUE_POLICIES:
        if policy.get(key) is not True:
            errors.append(f"POLICY_MUST_BE_TRUE:{key}")

    instances = runtime.get("instances")
    if not isinstance(instances, list) or not instances:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED",
            "errors": sorted(set(errors + ["MISSING_INSTANCES"])),
            "warnings": [],
            "instances": [],
            "guards": {
                "cross_instance_resource_sharing_forbidden": True,
                "credential_values_exposed": False,
            },
        }

    seen_ids: set[str] = set()
    seen_domains: dict[str, str] = {}
    instance_roots: list[tuple[str, str]] = []
    resource_roots: dict[str, list[tuple[str, str]]] = {key: [] for key in RESOURCE_KEYS}
    exact_path_owners: dict[str, dict[str, str]] = {"outbox": {}, "state": {}}
    credential_ref_owners: dict[str, str] = {}
    credential_namespaces: list[tuple[str, str]] = []
    metrics_namespaces: dict[str, str] = {}
    correction_namespaces: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []

    ordered = sorted(
        [item for item in instances if isinstance(item, dict)],
        key=lambda item: _clean(item.get("instance_id")),
    )
    if len(ordered) != len(instances):
        errors.append("INVALID_INSTANCE_ENTRY")

    for entry in ordered:
        instance_id = _clean(entry.get("instance_id")).lower()
        instance_root = _safe_rel(entry.get("instance_root"))
        registry_path = _safe_rel(entry.get("channel_registry"))
        canonical_domain = _clean(entry.get("canonical_domain")).lower()
        credential_namespace = _clean(entry.get("credential_namespace"))
        metrics_namespace = _clean(entry.get("metrics_namespace")).lower()
        correction_namespace = _clean(entry.get("correction_target_namespace")).lower()

        if not INSTANCE_ID_RE.fullmatch(instance_id):
            errors.append(f"INVALID_INSTANCE_ID:{instance_id or '<missing>'}")
        elif instance_id in seen_ids:
            errors.append(f"DUPLICATE_INSTANCE_ID:{instance_id}")
        else:
            seen_ids.add(instance_id)

        if not instance_root:
            errors.append(f"{instance_id}:INVALID_INSTANCE_ROOT")
        else:
            for owner, other_root in instance_roots:
                if owner != instance_id and _overlap(instance_root, other_root):
                    errors.append(f"INSTANCE_ROOT_COLLISION:{owner}:{instance_id}")
            instance_roots.append((instance_id, instance_root))

        if not canonical_domain:
            errors.append(f"{instance_id}:MISSING_CANONICAL_DOMAIN")
        else:
            owner = seen_domains.get(canonical_domain)
            if owner and owner != instance_id:
                errors.append(f"CANONICAL_DOMAIN_COLLISION:{owner}:{instance_id}:{canonical_domain}")
            else:
                seen_domains[canonical_domain] = instance_id

        if not registry_path:
            errors.append(f"{instance_id}:INVALID_CHANNEL_REGISTRY_PATH")
        elif instance_root and not _within(registry_path, instance_root):
            errors.append(f"{instance_id}:CHANNEL_REGISTRY_OUTSIDE_INSTANCE")
        elif not file_exists(registry_path):
            errors.append(f"{instance_id}:CHANNEL_REGISTRY_MISSING")

        if not CREDENTIAL_NAMESPACE_RE.fullmatch(credential_namespace):
            errors.append(f"{instance_id}:INVALID_CREDENTIAL_NAMESPACE")
        else:
            for owner, prefix in credential_namespaces:
                if owner != instance_id and (
                    credential_namespace.startswith(prefix) or prefix.startswith(credential_namespace)
                ):
                    errors.append(f"CREDENTIAL_NAMESPACE_OVERLAP:{owner}:{instance_id}")
            credential_namespaces.append((instance_id, credential_namespace))

        if not LOGICAL_NAMESPACE_RE.fullmatch(metrics_namespace):
            errors.append(f"{instance_id}:INVALID_METRICS_NAMESPACE")
        else:
            owner = metrics_namespaces.get(metrics_namespace)
            if owner and owner != instance_id:
                errors.append(f"METRICS_NAMESPACE_COLLISION:{owner}:{instance_id}:{metrics_namespace}")
            else:
                metrics_namespaces[metrics_namespace] = instance_id

        if not CORRECTION_NAMESPACE_RE.fullmatch(correction_namespace):
            errors.append(f"{instance_id}:INVALID_CORRECTION_TARGET_NAMESPACE")
        else:
            owner = correction_namespaces.get(correction_namespace)
            if owner and owner != instance_id:
                errors.append(
                    f"CORRECTION_TARGET_NAMESPACE_COLLISION:{owner}:{instance_id}:{correction_namespace}"
                )
            else:
                correction_namespaces[correction_namespace] = instance_id

        declared_roots = entry.get("resource_namespaces")
        if not isinstance(declared_roots, dict):
            declared_roots = {}
            errors.append(f"{instance_id}:MISSING_RESOURCE_NAMESPACES")

        clean_roots: dict[str, str] = {}
        for kind in RESOURCE_KEYS:
            root = _safe_rel(declared_roots.get(kind))
            clean_roots[kind] = root
            if not root:
                errors.append(f"{instance_id}:INVALID_{kind.upper()}_NAMESPACE")
                continue
            if instance_root and not _within(root, instance_root):
                errors.append(f"{instance_id}:{kind.upper()}_NAMESPACE_OUTSIDE_INSTANCE")
            for owner, other_root in resource_roots[kind]:
                if owner != instance_id and _overlap(root, other_root):
                    errors.append(f"CROSS_INSTANCE_{kind.upper()}_NAMESPACE_OVERLAP:{owner}:{instance_id}")
            resource_roots[kind].append((instance_id, root))

        adapter_result: dict[str, Any] | None = None
        credential_refs: set[str] = set()
        configured_channels = 0

        if registry_path and file_exists(registry_path):
            try:
                registry = load_json(registry_path)
            except Exception as exc:
                errors.append(f"{instance_id}:CHANNEL_REGISTRY_INVALID:{type(exc).__name__}")
                registry = None

            if isinstance(registry, dict):
                registry_instance_id = _clean(registry.get("instance_id")).lower()
                if registry_instance_id != instance_id:
                    errors.append(f"{instance_id}:REGISTRY_INSTANCE_MISMATCH")
                registry_domain = _clean(registry.get("canonical_domain")).lower()
                if registry_domain != canonical_domain:
                    errors.append(f"{instance_id}:REGISTRY_DOMAIN_MISMATCH")

                try:
                    adapter_result = adapter_contract.validate_registry(
                        registry,
                        load_channel=load_json,
                        file_exists=file_exists,
                        instance_root=instance_root,
                    )
                except Exception as exc:
                    errors.append(f"{instance_id}:ADAPTER_CONTRACT_EXCEPTION:{type(exc).__name__}")
                    adapter_result = None

                if adapter_result is not None:
                    if adapter_result.get("status") != "PASS":
                        for contract_error in adapter_result.get("errors", []):
                            errors.append(f"{instance_id}:ADAPTER_CONTRACT:{contract_error}")
                    for row in adapter_result.get("dispatch", []):
                        row_instance = _clean(row.get("instance_id")).lower()
                        if row_instance:
                            configured_channels += 1
                            if row_instance != instance_id:
                                errors.append(
                                    f"{instance_id}:CHANNEL_INSTANCE_MISMATCH:{_clean(row.get('registry_channel_id'))}"
                                )

                        for kind in ("outbox", "state"):
                            path = _safe_rel(row.get(kind))
                            if not path:
                                continue
                            namespace_root = clean_roots.get(kind, "")
                            if namespace_root and not _within(path, namespace_root):
                                errors.append(
                                    f"{instance_id}:{kind.upper()}_OUTSIDE_DECLARED_NAMESPACE:{path}"
                                )
                            owner = exact_path_owners[kind].get(path)
                            if owner and owner != instance_id:
                                errors.append(
                                    f"CROSS_INSTANCE_{kind.upper()}_COLLISION:{owner}:{instance_id}:{path}"
                                )
                            else:
                                exact_path_owners[kind][path] = instance_id

                        for ref in row.get("credential_references", []):
                            ref_name = _clean(ref)
                            if not ref_name:
                                continue
                            credential_refs.add(ref_name)
                            if credential_namespace and not ref_name.startswith(credential_namespace):
                                errors.append(
                                    f"{instance_id}:CREDENTIAL_OUTSIDE_NAMESPACE:{ref_name}"
                                )
                            owner = credential_ref_owners.get(ref_name)
                            if owner and owner != instance_id:
                                errors.append(
                                    f"CROSS_INSTANCE_CREDENTIAL_REFERENCE:{owner}:{instance_id}:{ref_name}"
                                )
                            else:
                                credential_ref_owners[ref_name] = instance_id

        summaries.append(
            {
                "instance_id": instance_id or None,
                "canonical_domain": canonical_domain or None,
                "instance_root": instance_root or None,
                "channel_registry": registry_path or None,
                "adapter_contract_status": adapter_result.get("status") if adapter_result else "BLOCKED",
                "configured_channels": configured_channels,
                "credential_namespace": credential_namespace or None,
                "credential_reference_names": sorted(credential_refs),
                "credential_values_exposed": False,
                "metrics_namespace": metrics_namespace or None,
                "correction_target_namespace": correction_namespace or None,
                "resource_namespaces": clean_roots,
                "isolation_key": (
                    _isolation_key(instance_id, instance_root, canonical_domain)
                    if instance_id and instance_root and canonical_domain
                    else None
                ),
            }
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not errors else "BLOCKED",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "instances": sorted(summaries, key=lambda item: item["instance_id"] or ""),
        "guards": {
            "cross_instance_resource_sharing_forbidden": True,
            "cross_instance_credentials_forbidden": True,
            "observed_metrics_instance_scoped": True,
            "correction_targets_instance_scoped": True,
            "credential_values_exposed": False,
            "zero_paid_dependency": True,
        },
    }
    return result


def validate_runtime_path(runtime_path: Path, repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    candidate = (repo_root / runtime_path).resolve() if not runtime_path.is_absolute() else runtime_path.resolve()
    if repo_root != candidate and repo_root not in candidate.parents:
        raise ValueError("runtime registry path must be inside repository root")

    runtime = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(runtime, dict):
        raise ValueError("runtime registry must be an object")

    def safe_candidate(rel: str) -> Path:
        safe = _safe_rel(rel)
        if not safe:
            raise ValueError("invalid repository-relative path")
        value = (repo_root / safe).resolve()
        if repo_root != value and repo_root not in value.parents:
            raise ValueError("path outside repository root")
        return value

    def exists(rel: str) -> bool:
        try:
            return safe_candidate(rel).is_file()
        except ValueError:
            return False

    def load(rel: str) -> dict[str, Any]:
        value = safe_candidate(rel)
        parsed = json.loads(value.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON resource must be an object")
        return parsed

    return validate_runtime(runtime, load_json=load, file_exists=exists)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_registry", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    result = validate_runtime_path(args.runtime_registry, args.repo_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
