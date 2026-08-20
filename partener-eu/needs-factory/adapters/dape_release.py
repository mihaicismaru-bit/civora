from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from . import dape


class DapeReleaseError(ValueError):
    """Raised when a Needs Factory result is not safe for DAPE release handoff."""


SEVEN_ARTIFACTS = (
    "CHECKPOINT_MANIFEST.json",
    "EVIDENCE_LEDGER.json",
    "ARTIFACT_BUNDLE.json",
    "TEST_REPORT.json",
    "BACKLOG_SNAPSHOT.json",
    "RESUME_MANIFEST.json",
    "RELEASE_PACKAGE.json",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(value), encoding="utf-8", newline="\n")


def _release_preflight(
    narrative_pack: Mapping[str, Any],
    compiled_analysis: Mapping[str, Any],
    export_manifest: Mapping[str, Any],
) -> List[str]:
    failures: List[str] = []
    release_gate = narrative_pack.get("release_gate") or {}
    if not release_gate.get("ready_for_narrative"):
        failures.append("narrative_pack_release_gate_not_ready")
    validation = compiled_analysis.get("validation") or {}
    if not validation.get("valid"):
        failures.append("compiled_analysis_not_valid")
    if compiled_analysis.get("source_pack_sha256") != narrative_pack.get("pack_sha256"):
        failures.append("compiled_analysis_pack_hash_mismatch")
    if export_manifest.get("source_pack_sha256") != narrative_pack.get("pack_sha256"):
        failures.append("export_manifest_pack_hash_mismatch")
    if export_manifest.get("source_markdown_sha256") != compiled_analysis.get("markdown_sha256"):
        failures.append("export_manifest_markdown_hash_mismatch")
    if export_manifest.get("source_register_sha256") != compiled_analysis.get("source_register_sha256"):
        failures.append("export_manifest_source_register_hash_mismatch")
    for name, result in (export_manifest.get("docx_validation") or {}).items():
        if not result.get("valid"):
            failures.append(f"docx_semantic_validation_failed:{name}")
    package_zip = export_manifest.get("package_zip") or {}
    if len(str(package_zip.get("sha256") or "")) != 64:
        failures.append("missing_final_package_zip_hash")
    return failures


def _evidence_ledger(narrative_pack: Mapping[str, Any]) -> Dict[str, Any]:
    needs = []
    evidence: Dict[str, Dict[str, Any]] = {}
    for claim in narrative_pack.get("claim_ledger", []) or []:
        need_id = str(claim.get("need_id"))
        evidence_ids = []
        for ref in claim.get("evidence_refs", []) or []:
            evidence_id = str(ref.get("evidence_id"))
            evidence_ids.append(evidence_id)
            evidence.setdefault(evidence_id, {
                "evidence_id": evidence_id,
                "source": ref.get("source"),
                "source_type": ref.get("source_type"),
                "source_url": ref.get("source_url"),
                "source_document_id": ref.get("source_document_id"),
                "territory": ref.get("territory"),
                "scope": ref.get("scope"),
                "period": ref.get("period"),
                "tier": ref.get("tier"),
                "constructs": list(ref.get("constructs") or []),
                "direct_measurement": ref.get("direct_measurement"),
                "population_snapshot_id": ref.get("population_snapshot_id"),
                "measures": [dict(item) for item in (ref.get("measures") or [])],
            })
        needs.append({
            "need_id": need_id,
            "rank": claim.get("rank"),
            "score": claim.get("score"),
            "scope": claim.get("scope"),
            "evidence_ids": evidence_ids,
            "prohibited_overclaim": claim.get("prohibited_overclaim"),
        })
    return {
        "schema_version": "nf.dape_evidence_ledger.v0.1",
        "source_pack_sha256": narrative_pack.get("pack_sha256"),
        "needs": needs,
        "evidence": [evidence[key] for key in sorted(evidence)],
        "claim_mutation_allowed": False,
        "canonical_source": "NARRATIVE_READY_PACK",
    }


def _artifact_bundle(
    run_manifest: Mapping[str, Any],
    narrative_pack: Mapping[str, Any],
    compiled_analysis: Mapping[str, Any],
    export_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
) -> Dict[str, Any]:
    artifacts = [
        {"path": "NARRATIVE_READY_PACK.json", "role": "canonical_claim_ledger", "sha256": narrative_pack.get("pack_sha256")},
        {"path": "COMPILED_ANALYSIS.json", "role": "compiled_analysis", "sha256": compiled_analysis.get("markdown_sha256")},
        {"path": "SOURCE_REGISTER.md", "role": "source_register", "sha256": compiled_analysis.get("source_register_sha256")},
    ]
    for name, info in sorted((export_manifest.get("files") or {}).items()):
        artifacts.append({"path": name, "role": info.get("role"), "sha256": info.get("sha256")})
    package_zip = export_manifest.get("package_zip") or {}
    artifacts.append({"path": package_zip.get("path"), "role": "final_package_zip", "sha256": package_zip.get("sha256")})
    return {
        "schema_version": "1.0.0",
        "checkpoint_id": checkpoint_id,
        "status": "HANDOFF_READY",
        "source_run_id": run_manifest.get("run_id"),
        "artifacts": artifacts,
        "separation": {
            "core_evidence_separate": True,
            "core_changes": False,
            "generic_duplication": False,
            "single_control_plane_preserved": True,
        },
        "canonical": False,
    }


def _test_report(
    run_manifest: Mapping[str, Any],
    narrative_pack: Mapping[str, Any],
    compiled_analysis: Mapping[str, Any],
    export_manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    docx_validation = export_manifest.get("docx_validation") or {}
    return {
        "schema_version": "nf.dape_test_report.v0.1",
        "run_id": run_manifest.get("run_id"),
        "result": "PASS",
        "release_gate_ready": bool((narrative_pack.get("release_gate") or {}).get("ready_for_narrative")),
        "compiled_narrative_valid": bool((compiled_analysis.get("validation") or {}).get("valid")),
        "docx_semantic_validation": {name: bool(result.get("valid")) for name, result in sorted(docx_validation.items())},
        "closed_checkpoints": list(run_manifest.get("closed_checkpoints") or []),
        "required_closed_checkpoint": "NF12_PACKAGE",
        "required_closed_checkpoint_present": "NF12_PACKAGE" in set(run_manifest.get("closed_checkpoints") or []),
        "fail_closed": True,
    }


def _backlog_snapshot() -> Dict[str, Any]:
    return {
        "schema_version": "nf.dape_backlog_snapshot.v0.1",
        "blocking_items": [],
        "nonblocking_items": [
            "DAPE host must validate the seven-artifact set before canonical promotion",
            "Merge/integration requires explicit approval",
        ],
        "next_gate": "DAPE_HOST_ACCEPTANCE",
        "release_state": "HANDOFF_READY_NOT_CANONICAL",
    }


def _release_package(
    run_manifest: Mapping[str, Any],
    narrative_pack: Mapping[str, Any],
    compiled_analysis: Mapping[str, Any],
    export_manifest: Mapping[str, Any],
    *,
    checkpoint_id: str,
) -> Dict[str, Any]:
    return {
        "schema_version": "nf.dape_release_package.v0.1",
        "checkpoint_id": checkpoint_id,
        "run_id": run_manifest.get("run_id"),
        "project_id": run_manifest.get("project_id"),
        "state": "HANDOFF_READY_NOT_CANONICAL",
        "canonical": False,
        "source_pack_sha256": narrative_pack.get("pack_sha256"),
        "compiled_analysis_sha256": compiled_analysis.get("markdown_sha256"),
        "source_register_sha256": compiled_analysis.get("source_register_sha256"),
        "final_package_zip": dict(export_manifest.get("package_zip") or {}),
        "downstream_only": True,
        "claim_mutation_allowed": False,
        "merge_allowed": False,
        "host_action_required": True,
    }


def export_dape_checkpoint(
    run_manifest: Mapping[str, Any],
    narrative_pack: Mapping[str, Any],
    compiled_analysis: Mapping[str, Any],
    export_manifest: Mapping[str, Any],
    output_dir: Path,
    *,
    checkpoint_id: str,
    project_id: str,
    canonical_base_checkpoint: str,
) -> Dict[str, Any]:
    failures = _release_preflight(narrative_pack, compiled_analysis, export_manifest)
    if "NF12_PACKAGE" not in set(run_manifest.get("closed_checkpoints") or []):
        failures.append("nf12_not_closed")
    if failures:
        raise DapeReleaseError(";".join(failures))

    root = output_dir.as_posix()
    required_paths = {
        "checkpoint_manifest": f"{root}/CHECKPOINT_MANIFEST.json",
        "evidence_ledger": f"{root}/EVIDENCE_LEDGER.json",
        "artifact_bundle": f"{root}/ARTIFACT_BUNDLE.json",
        "test_report": f"{root}/TEST_REPORT.json",
        "backlog_snapshot": f"{root}/BACKLOG_SNAPSHOT.json",
        "resume_manifest": f"{root}/RESUME_MANIFEST.json",
        "release_package": f"{root}/RELEASE_PACKAGE.json",
    }
    checkpoint_manifest = dape.build_checkpoint_manifest(
        run_manifest,
        checkpoint_id=checkpoint_id,
        project_id=project_id,
        scope="Needs Factory final release handoff into the canonical DAPE single control plane.",
        required_artifact_paths=required_paths,
        status="HANDOFF_READY",
    )
    checkpoint_manifest["validation"]["result"] = "PASS"
    checkpoint_manifest["closure_eligibility"] = "HOST_VALIDATION_REQUIRED"
    checkpoint_manifest["closure_blockers"] = ["DAPE host acceptance not yet recorded"]

    evidence_ledger = _evidence_ledger(narrative_pack)
    artifact_bundle = _artifact_bundle(run_manifest, narrative_pack, compiled_analysis, export_manifest, checkpoint_id=checkpoint_id)
    test_report = _test_report(run_manifest, narrative_pack, compiled_analysis, export_manifest)
    backlog_snapshot = _backlog_snapshot()
    resume_manifest = dape.build_resume_manifest(
        run_manifest,
        checkpoint_id=checkpoint_id,
        resume_phase="DAPE_HOST_ACCEPTANCE",
        canonical_base_checkpoint=canonical_base_checkpoint,
        checkpoint_manifest_path=required_paths["checkpoint_manifest"],
        required_next_gate="DAPE host validates seven artifacts and records canonical checkpoint acceptance",
    )
    release_package = _release_package(run_manifest, narrative_pack, compiled_analysis, export_manifest, checkpoint_id=checkpoint_id)

    payloads = {
        "CHECKPOINT_MANIFEST.json": checkpoint_manifest,
        "EVIDENCE_LEDGER.json": evidence_ledger,
        "ARTIFACT_BUNDLE.json": artifact_bundle,
        "TEST_REPORT.json": test_report,
        "BACKLOG_SNAPSHOT.json": backlog_snapshot,
        "RESUME_MANIFEST.json": resume_manifest,
        "RELEASE_PACKAGE.json": release_package,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in SEVEN_ARTIFACTS:
        _write_json(output_dir / name, payloads[name])

    file_hashes = {}
    import hashlib
    for name in SEVEN_ARTIFACTS:
        file_hashes[name] = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()

    return {
        "schema_version": "nf.dape_handoff_export.v0.1",
        "checkpoint_id": checkpoint_id,
        "state": "HANDOFF_READY_NOT_CANONICAL",
        "canonical": False,
        "artifact_count": len(SEVEN_ARTIFACTS),
        "artifacts": list(SEVEN_ARTIFACTS),
        "file_hashes": file_hashes,
        "host_action_required": True,
    }
