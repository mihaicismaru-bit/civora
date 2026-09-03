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
)
EVIDENCE_SCHEMA = "PARTENER_EU_EUI_EXACT_CALL_EVIDENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_EUI_EXACT_CALL_RECONCILIATION_V1"
IDENTITY_SLUG = "fourth-call-proposals-innovative-actions"
GENERIC_ARTIFACT_PREFIX = "partener-eu-eu-direct-programme-intelligence-"
LEGACY_PROOF_ARTIFACT_PREFIX = "partener-eu-eui-exact-call-proof-"
ARTIFACT_PREFIXES = (
    GENERIC_ARTIFACT_PREFIX,
    LEGACY_PROOF_ARTIFACT_PREFIX,
)


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
        and candidate.get("programme_family") == "EUROPEAN_URBAN_INITIATIVE"
        and candidate.get("identity_slug") == IDENTITY_SLUG
        and candidate.get("authority_class") == "EUI_EXACT_CALL_DETAIL_AND_TOR"
    )


def restore_previous(root: pathlib.Path) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-eui-exact-canonical-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    data = load(artifacts_json)
    rows: list[tuple[int, str, int, str]] = []
    for artifact in data.get("artifacts") or []:
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True or not name.startswith(ARTIFACT_PREFIXES):
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        source_priority = 0 if name.startswith(GENERIC_ARTIFACT_PREFIX) else 1
        rows.append((source_priority, str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    # Prefer canonical generic EU_DIRECT history over legacy proof artifacts even if
    # a proof artifact is slightly newer. Within each source kind, prefer newest.
    rows.sort(key=lambda row: row[1], reverse=True)
    rows.sort(key=lambda row: row[0])

    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_source_kind": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_ARTIFACT",
        "identity_slug": IDENTITY_SLUG,
    }
    for source_priority, _, artifact_id, artifact_name in rows[:30]:
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        candidates = sorted(unpack.rglob("eui-call4-exact-evidence.json"), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                continue
            if not compatible(candidate):
                continue
            dump(previous_dir / "eui-call4-exact-evidence.json", candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_source_kind": "GENERIC_EU_DIRECT" if source_priority == 0 else "LEGACY_EUI_PROOF",
                "restore_reason": "SAME_EXACT_CALL_IDENTITY",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
                "restored_source_health_state": candidate.get("source_health_state"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    evidence = load(root / "current" / "eui-call4-exact-evidence.json")
    reconciliation = load(root / "current" / "eui-call4-reconciliation.json")
    if not compatible(evidence):
        raise SystemExit("FAIL canonical EUI exact identity drift")
    if evidence.get("parser_version") != "EU_DIRECT_EUI_EXACT_CALL_V1_1":
        raise SystemExit("FAIL canonical EUI exact parser drift")
    if reconciliation.get("schema") != RECONCILIATION_SCHEMA or reconciliation.get("parser_version") != "EU_DIRECT_EUI_EXACT_CALL_RECONCILE_V1_1":
        raise SystemExit("FAIL canonical EUI exact reconciliation identity drift")
    if reconciliation.get("identity_slug") != IDENTITY_SLUG or reconciliation.get("identity_key") != evidence.get("identity_key"):
        raise SystemExit("FAIL canonical EUI reconciliation lost exact identity binding")
    if any(evidence.get(flag) is not False for flag in FLAGS) or any(reconciliation.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL canonical EUI exact lane became materially authorizing")
    if evidence.get("publication_effect") != "NONE" or reconciliation.get("publication_effect") != "NONE":
        raise SystemExit("FAIL canonical EUI exact publication boundary drift")
    if evidence.get("canonical_corpus_mutation") is not False or reconciliation.get("canonical_corpus_mutation") is not False:
        raise SystemExit("FAIL canonical EUI exact corpus mutation drift")
    if evidence.get("observation_state") != "EXACT_CURRENT_CALL_NON_AUTHORIZING":
        raise SystemExit("FAIL canonical EUI exact observation-state drift")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("identity_key") or "")):
        raise SystemExit("FAIL canonical EUI exact identity hash missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("exact_semantic_fingerprint") or "")):
        raise SystemExit("FAIL canonical EUI exact semantic hash missing")
    if evidence.get("official_call_identifier") is not None:
        raise SystemExit("FAIL canonical EUI exact lane fabricated official identifier")
    if reconciliation.get("field_scoped_material_admission_required") is not True:
        raise SystemExit("FAIL canonical EUI exact lane skipped field-scoped admission")
    if reconciliation.get("lkg_reference_is_current_truth") is not False:
        raise SystemExit("FAIL canonical EUI exact lane promoted LKG to current truth")

    healthy = evidence.get("source_health_state") == "HEALTHY" and evidence.get("lkg_required") is False
    if healthy:
        if evidence.get("discovery_link_verified") is not True:
            raise SystemExit("FAIL healthy canonical EUI exact chain lost discovery binding")
        if evidence.get("candidate_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
            raise SystemExit("FAIL healthy canonical EUI candidate state drift")
        receipts = evidence.get("source_receipts") or {}
        if set(receipts) != {"portico_call_index", "exact_call_detail", "terms_of_reference"}:
            raise SystemExit("FAIL healthy canonical EUI source receipt inventory drift")
        for row in receipts.values():
            if row.get("health_state") != "HEALTHY" or row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise SystemExit("FAIL healthy canonical EUI source receipt inconsistent")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("raw_sha256") or "")):
                raise SystemExit("FAIL healthy canonical EUI source receipt raw hash missing")
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("tor_raw_sha256") or "")):
            raise SystemExit("FAIL healthy canonical EUI Terms of Reference hash missing")
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "EUI_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if reconciliation.get("reconciliation_state") not in allowed or reconciliation.get("semantic_reconciliation_passed") is not True:
            raise SystemExit("FAIL healthy canonical EUI reconciliation state drift")
        if reconciliation.get("lkg_reference_required") is not False:
            raise SystemExit("FAIL healthy canonical EUI exact current incorrectly requires LKG")
        if evidence.get("candidate_state") == "OPEN_CALL" and reconciliation.get("material_admission_ready_for_downstream_review") is not False:
            raise SystemExit("FAIL EUI OPEN without official identifier reached material review gate")
    else:
        if evidence.get("source_health_state") != "DEGRADED" or evidence.get("lkg_required") is not True:
            raise SystemExit("FAIL degraded canonical EUI exact health contract drift")
        if evidence.get("candidate_state") != "UNKNOWN":
            raise SystemExit("FAIL degraded canonical EUI exact current retained material candidate state")
        if reconciliation.get("reconciliation_state") != "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED":
            raise SystemExit("FAIL degraded canonical EUI exact current did not fail closed")
        if reconciliation.get("semantic_reconciliation_passed") is not False or reconciliation.get("semantic_change_count") != 0 or reconciliation.get("semantic_changes") != []:
            raise SystemExit("FAIL degraded canonical EUI exact current fabricated semantic reconciliation")
        if reconciliation.get("lkg_reference_required") is not True or reconciliation.get("material_admission_ready_for_downstream_review") is not False:
            raise SystemExit("FAIL degraded canonical EUI exact LKG/admission boundary drift")

    return {
        "programme": "European Urban Initiative",
        "identity_slug": evidence["identity_slug"],
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "official_call_identifier": evidence["official_call_identifier"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "lkg_reference_required": reconciliation["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": reconciliation["material_admission_ready_for_downstream_review"],
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / "eui-call4-exact-evidence.json"
    previous_path = root / "previous" / "eui-call4-exact-evidence.json"
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY" and current.get("lkg_required") is False:
        shutil.copy2(current_path, history / "eui-call4-exact-evidence.json")
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists():
        previous = load(previous_path)
        if previous.get("source_health_state") == "HEALTHY" and previous.get("lkg_required") is False:
            shutil.copy2(previous_path, history / "eui-call4-exact-evidence.json")
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
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/eui-exact")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    restore = restore_previous(root)
    run_id = os.environ.get("EUI_EXACT_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-eui-call4"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ingest)
    run([
        sys.executable,
        str(ingest / "eu_direct_eui_exact_call.py"),
        "--run-id", run_id,
        "--output-dir", str(root / "current"),
    ], env=env)

    reconcile_cmd = [
        sys.executable,
        str(ingest / "eu_direct_eui_exact_call_reconcile.py"),
        str(root / "current" / "eui-call4-exact-evidence.json"),
    ]
    previous_path = root / "previous" / "eui-call4-exact-evidence.json"
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    reconcile_cmd += ["--output", str(root / "current" / "eui-call4-reconciliation.json")]
    run(reconcile_cmd, env=env)

    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
