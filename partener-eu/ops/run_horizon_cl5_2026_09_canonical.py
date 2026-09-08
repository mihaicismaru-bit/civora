#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from typing import Any

FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)
EVIDENCE_SCHEMA = "PARTENER_EU_HORIZON_CL5_2026_09_EXACT_EVIDENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_HORIZON_CL5_2026_09_RECONCILIATION_V1"
CALL_IDENTIFIER = "HORIZON-CL5-2026-09"
PROGRAMME_FAMILY = "HORIZON_EUROPE_CLUSTER5"
AUTHORITY_CLASS = "EU_COMMISSION_CINEA_PLUS_FUNDING_TENDERS"
GENERIC_ARTIFACT_PREFIX = "partener-eu-eu-direct-programme-intelligence-"
PROOF_ARTIFACT_PREFIX = "partener-eu-horizon-cl5-2026-09-exact-proof"
EVIDENCE_NAME = "horizon-cl5-2026-09-exact-evidence.json"
RECONCILIATION_NAME = "horizon-cl5-2026-09-reconciliation.json"


def run(cmd: list[str], *, stdout=None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout, env=env)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text:
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def compatible(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("schema") == EVIDENCE_SCHEMA
        and candidate.get("source_family") == "EU_DIRECT"
        and candidate.get("programme_family") == PROGRAMME_FAMILY
        and candidate.get("authority_class") == AUTHORITY_CLASS
        and candidate.get("call_identifier") == CALL_IDENTIFIER
        and candidate.get("semantic_reconciliation_required") is True
        and candidate.get("field_scoped_material_admission_required") is True
    )


def _artifact_rows() -> list[tuple[int, str, int, str]]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-horizon-cl5-2026-09-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    rows: list[tuple[int, str, int, str]] = []
    for artifact in (load(artifacts_json).get("artifacts") or []):
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True:
            continue
        if name.startswith(GENERIC_ARTIFACT_PREFIX):
            kind_rank = 0
            kind = "GENERIC_EU_DIRECT"
        elif name.startswith(PROOF_ARTIFACT_PREFIX):
            kind_rank = 1
            kind = "HORIZON_CL5_EXACT_PROOF_BOOTSTRAP"
        else:
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((kind_rank, str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), kind))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=False)
    generic = sorted((row for row in rows if row[0] == 0), key=lambda row: row[1], reverse=True)
    proof = sorted((row for row in rows if row[0] == 1), key=lambda row: row[1], reverse=True)
    return generic + proof


def restore_previous(root: pathlib.Path) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    scratch = pathlib.Path("/tmp/partener-eu-horizon-cl5-2026-09-history-scan")
    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_source_kind": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_CANONICAL_OR_BOOTSTRAP_ARTIFACT",
        "call_identifier": CALL_IDENTIFIER,
    }
    for _, _, artifact_id, kind in _artifact_rows()[:40]:
        artifact_meta_path = scratch / f"meta-{artifact_id}.json"
        with artifact_meta_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}"], stdout=output)
        artifact_meta = load(artifact_meta_path)
        artifact_name = str(artifact_meta.get("name") or "")
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        candidates = sorted(unpack.rglob(EVIDENCE_NAME), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                continue
            if not compatible(candidate):
                continue
            dump(previous_dir / EVIDENCE_NAME, candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_source_kind": kind,
                "restore_reason": "SAME_EXACT_HORIZON_CL5_CALL_IDENTITY",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
                "restored_source_health_state": candidate.get("source_health_state"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path, restore: dict[str, Any]) -> dict[str, Any]:
    evidence = load(root / "current" / EVIDENCE_NAME)
    reconciliation = load(root / "current" / RECONCILIATION_NAME)
    if not compatible(evidence):
        raise SystemExit("FAIL canonical Horizon CL5 exact identity drift")
    if evidence.get("parser_version") != "EU_DIRECT_HORIZON_CL5_2026_09_EXACT_V1":
        raise SystemExit("FAIL canonical Horizon CL5 exact parser drift")
    if reconciliation.get("schema") != RECONCILIATION_SCHEMA or reconciliation.get("parser_version") != "EU_DIRECT_HORIZON_CL5_2026_09_RECONCILE_V1":
        raise SystemExit("FAIL canonical Horizon CL5 reconciliation identity drift")
    if reconciliation.get("call_identifier") != CALL_IDENTIFIER:
        raise SystemExit("FAIL canonical Horizon CL5 reconciliation lost exact identity")
    if any(evidence.get(flag) is not False for flag in FLAGS) or any(reconciliation.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL canonical Horizon CL5 lane became materially authorizing")
    if evidence.get("publication_effect") != "NONE" or reconciliation.get("publication_effect") != "NONE":
        raise SystemExit("FAIL canonical Horizon CL5 publication boundary drift")
    if reconciliation.get("lkg_is_current_truth") is not False:
        raise SystemExit("FAIL canonical Horizon CL5 promoted LKG to current truth")
    if reconciliation.get("field_scoped_material_admission_required") is not True:
        raise SystemExit("FAIL canonical Horizon CL5 skipped field-scoped admission")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("exact_semantic_fingerprint") or "")):
        raise SystemExit("FAIL canonical Horizon CL5 semantic fingerprint missing")

    healthy = evidence.get("source_health_state") == "HEALTHY" and evidence.get("lkg_required") is False
    if healthy:
        if evidence.get("authority_agreement_verified") is not True or evidence.get("evidence_usable_for_reconciliation") is not True:
            raise SystemExit("FAIL healthy canonical Horizon CL5 lacks authority agreement")
        structured = evidence.get("structured_snapshot") or {}
        if structured.get("programme_reference") != "43108390" or "horizon europe" not in str(structured.get("programme_label") or "").casefold():
            raise SystemExit("FAIL healthy canonical Horizon CL5 lost programme binding")
        if not structured.get("topic_identifiers"):
            raise SystemExit("FAIL healthy canonical Horizon CL5 lacks exact topic inventory")
        state = reconciliation.get("reconciliation_state")
        if restore.get("previous_found") is True:
            if state not in {"NO_CHANGE", "SEMANTIC_CHANGE_REVIEW_REQUIRED", "CURRENT_HEALTHY_PREVIOUS_UNUSABLE_BASELINE_RESET_NON_AUTHORIZING"}:
                raise SystemExit("FAIL canonical Horizon CL5 replay state drift")
        elif state != "BASELINE_CURRENT_HEALTHY_NON_AUTHORIZING":
            raise SystemExit("FAIL canonical Horizon CL5 baseline state drift")
        if state == "NO_CHANGE":
            if reconciliation.get("semantic_change_count") != 0:
                raise SystemExit("FAIL canonical Horizon CL5 NO_CHANGE semantic count drift")
            if reconciliation.get("previous_same_identity_restored") is not True or reconciliation.get("previous_strictly_older") is not True:
                raise SystemExit("FAIL canonical Horizon CL5 NO_CHANGE lacks strict same-identity history")
            if reconciliation.get("material_admission_ready_for_downstream_review") is not True:
                raise SystemExit("FAIL stable canonical Horizon CL5 replay did not reach downstream review readiness")
        else:
            if reconciliation.get("material_admission_ready_for_downstream_review") is not False:
                raise SystemExit("FAIL unstable canonical Horizon CL5 became review-ready")
    else:
        if evidence.get("source_health_state") != "DEGRADED_SEMANTIC_OR_TRANSPORT" or evidence.get("lkg_required") is not True:
            raise SystemExit("FAIL degraded canonical Horizon CL5 health contract drift")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("deadline_candidate") is not None:
            raise SystemExit("FAIL degraded canonical Horizon CL5 leaked material candidate state")
        if reconciliation.get("reconciliation_state") != "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING":
            raise SystemExit("FAIL degraded canonical Horizon CL5 did not fail closed")
        if reconciliation.get("material_admission_ready_for_downstream_review") is not False:
            raise SystemExit("FAIL degraded canonical Horizon CL5 became review-ready")

    return {
        "programme": "Horizon Europe Cluster 5",
        "call_identifier": CALL_IDENTIFIER,
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "deadline_candidate": evidence["deadline_candidate"],
        "topic_count": (evidence.get("structured_snapshot") or {}).get("topic_count"),
        "programme_reference": (evidence.get("structured_snapshot") or {}).get("programme_reference"),
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "restore_source_kind": restore.get("restore_source_kind"),
        "material_admission_ready_for_downstream_review": reconciliation["material_admission_ready_for_downstream_review"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / EVIDENCE_NAME
    previous_path = root / "previous" / EVIDENCE_NAME
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY" and current.get("lkg_required") is False:
        shutil.copy2(current_path, history / EVIDENCE_NAME)
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists():
        previous = load(previous_path)
        if previous.get("source_health_state") == "HEALTHY" and previous.get("lkg_required") is False:
            shutil.copy2(previous_path, history / EVIDENCE_NAME)
            selected = "PREVIOUS_HEALTHY_LKG"
        else:
            selected = "NO_HEALTHY_LKG_AVAILABLE"
    else:
        selected = "NO_HEALTHY_LKG_AVAILABLE"
    result = {
        "selected": selected,
        "current_source_health_state": current.get("source_health_state"),
        "lkg_is_current_truth": False,
    }
    dump(history / "history-selection.json", result)
    return result


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    ops = repo_root / "partener-eu" / "ops"
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/horizon-cl5-2026-09")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ingest}:{ops}"
    run([sys.executable, str(ops / "test_eu_direct_horizon_cl5_2026_09_exact.py")], env=env)

    restore = restore_previous(root)
    run_id = os.environ.get("HORIZON_CL5_EXACT_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-horizon-cl5-2026-09"
    run([
        sys.executable, str(ingest / "eu_direct_horizon_cl5_2026_09_exact.py"),
        "--run-id", run_id,
        "--output-dir", str(root / "current"),
    ], env=env)

    reconcile_cmd = [
        sys.executable, str(ingest / "eu_direct_horizon_cl5_2026_09_reconcile.py"),
        "--current", str(root / "current" / EVIDENCE_NAME),
        "--output", str(root / "current" / RECONCILIATION_NAME),
    ]
    previous_path = root / "previous" / EVIDENCE_NAME
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    run(reconcile_cmd, env=env)

    boundary = enforce_boundary(root, restore)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
