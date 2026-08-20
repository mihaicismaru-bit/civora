from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


DAPE_REQUIRED_CHECKPOINT_ARTIFACTS = [
    "CHECKPOINT_MANIFEST",
    "EVIDENCE_LEDGER",
    "ARTIFACT_BUNDLE",
    "TEST_REPORT",
    "BACKLOG_SNAPSHOT",
    "RESUME_MANIFEST",
    "RELEASE_PACKAGE",
]


def build_artifact_bundle(
    run_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
    artifact_roles: Mapping[str, str],
    status: str = "HANDOFF_CANDIDATE",
) -> Dict[str, Any]:
    hashes = run_manifest.get("artifact_hashes") or {}
    artifacts = []
    for path, role in sorted(artifact_roles.items()):
        item = {"path": path, "role": role}
        if path in hashes:
            item["sha256"] = hashes[path]
        artifacts.append(item)
    return {
        "schema_version": "1.0.0",
        "checkpoint_id": checkpoint_id,
        "status": status,
        "artifacts": artifacts,
        "source_run_id": run_manifest.get("run_id"),
        "separation": {
            "core_evidence_separate": True,
            "core_changes": False,
            "generic_duplication": False,
            "single_control_plane_preserved": True,
        },
        "canonical": False,
    }


def build_checkpoint_manifest(
    run_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
    project_id: str,
    scope: str,
    required_artifact_paths: Mapping[str, str],
    status: str = "IN_PROGRESS",
    source_issue: Optional[int] = None,
) -> Dict[str, Any]:
    manifest = {
        "schema_version": "1.0.0",
        "checkpoint_id": checkpoint_id,
        "project_id": project_id,
        "status": status,
        "scope": scope,
        "canonical_on_merge": False,
        "classification": "DOMAIN_SPECIFIC",
        "required_artifacts": dict(required_artifact_paths),
        "integration": {
            "single_control_plane_preserved": True,
            "core_changes": False,
            "result": "PASS",
        },
        "validation": {
            "fail_closed_conflicting_evidence": True,
            "needs_factory_run_id": run_manifest.get("run_id"),
            "result": "PASS" if "NF11_ADVERSARIAL_QA" in set(run_manifest.get("closed_checkpoints") or []) else "PENDING",
        },
        "separation_guards": {
            "core_changes_allowed": False,
            "generic_duplication_allowed": False,
            "external_capability_inference_allowed": False,
            "single_control_plane_required": True,
        },
        "closure_eligibility": "NOT_ELIGIBLE",
        "closure_blockers": ["DAPE host validation and canonical integration not complete"],
    }
    if source_issue is not None:
        manifest["source_issue"] = source_issue
    return manifest


def build_resume_manifest(
    run_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
    resume_phase: str,
    canonical_base_checkpoint: str,
    checkpoint_manifest_path: str,
    required_next_gate: str,
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "checkpoint_id": checkpoint_id,
        "resume_phase": resume_phase,
        "canonical_base_checkpoint": canonical_base_checkpoint,
        "resume_from": checkpoint_manifest_path,
        "required_next_gate": required_next_gate,
        "guards": {
            "core_first": True,
            "no_generic_duplication": True,
            "single_control_plane": True,
            "core_checkpoint_evidence_separate": True,
            "external_state_inference_allowed": False,
        },
        "needs_factory_run_id": run_manifest.get("run_id"),
        "source_snapshot_ids": list(run_manifest.get("source_snapshot_ids") or []),
        "canonical": False,
    }


def build_handoff_package(
    run_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
    project_id: str,
    scope: str,
    artifact_roles: Mapping[str, str],
    canonical_base_checkpoint: str,
    checkpoint_root: str,
) -> Dict[str, Any]:
    required_paths = {
        "checkpoint_manifest": f"{checkpoint_root}/CHECKPOINT_MANIFEST.json",
        "evidence_ledger": f"{checkpoint_root}/EVIDENCE_LEDGER.json",
        "artifact_bundle": f"{checkpoint_root}/ARTIFACT_BUNDLE.json",
        "test_report": f"{checkpoint_root}/TEST_REPORT.json",
        "backlog_snapshot": f"{checkpoint_root}/BACKLOG_SNAPSHOT.json",
        "resume_manifest": f"{checkpoint_root}/RESUME_MANIFEST.json",
        "release_package": f"{checkpoint_root}/RELEASE_PACKAGE.json",
    }
    return {
        "checkpoint_manifest": build_checkpoint_manifest(
            run_manifest,
            checkpoint_id=checkpoint_id,
            project_id=project_id,
            scope=scope,
            required_artifact_paths=required_paths,
        ),
        "artifact_bundle": build_artifact_bundle(
            run_manifest,
            checkpoint_id=checkpoint_id,
            artifact_roles=artifact_roles,
        ),
        "resume_manifest": build_resume_manifest(
            run_manifest,
            checkpoint_id=checkpoint_id,
            resume_phase="DAPE_HOST_INTEGRATION",
            canonical_base_checkpoint=canonical_base_checkpoint,
            checkpoint_manifest_path=required_paths["checkpoint_manifest"],
            required_next_gate="DAPE host validates the seven-artifact checkpoint set and integrates it through the canonical single control plane",
        ),
        "required_checkpoint_artifacts": list(DAPE_REQUIRED_CHECKPOINT_ARTIFACTS),
        "host_action_required": True,
        "canonical": False,
    }
