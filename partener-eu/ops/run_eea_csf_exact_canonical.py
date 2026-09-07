#!/usr/bin/env python3
"""Canonical runner for exact EEA Civil Society Fund Romania call identities.

The runner centralises restore -> acquire -> reconcile -> boundary -> history/LKG
for supported call-specific parsers. Call-specific modules retain responsibility
for exact page semantics; this runner never generalises call-specific fields or
widens material authority.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)
CANONICAL_ARTIFACT_PREFIX = "partener-eu-official-programme-intelligence-"


@dataclass(frozen=True)
class CallConfig:
    call_id: str
    exact_module: str
    reconcile_module: str
    evidence_filename: str
    reconciliation_filename: str
    legacy_artifact_prefixes: tuple[str, ...]


CONFIGS = {
    "5": CallConfig(
        call_id="5",
        exact_module="eea_civil_society_fund_call5_exact",
        reconcile_module="eea_civil_society_fund_call5_reconcile",
        evidence_filename="eea-csf-ro-call5-exact-evidence.json",
        reconciliation_filename="eea-csf-ro-call5-reconciliation.json",
        legacy_artifact_prefixes=(
            "partener-eu-eea-csf-call5-exact-proof-",
            "partener-eu-eea-csf-call5-exact-history",
        ),
    ),
    "7": CallConfig(
        call_id="7",
        exact_module="eea_civil_society_fund_call7_exact",
        reconcile_module="eea_civil_society_fund_call7_reconcile",
        evidence_filename="eea-csf-ro-call7-exact-evidence.json",
        reconciliation_filename="eea-csf-ro-call7-reconciliation.json",
        legacy_artifact_prefixes=("partener-eu-eea-csf-call7-exact-",),
    ),
}


def run(cmd: list[str], *, stdout=None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout, env=env)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EEA CSF exact runner requires timezone-aware timestamps")
    return parsed


def candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text:
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def healthy(value: Mapping[str, Any] | None) -> bool:
    return bool(
        value is not None
        and value.get("source_health_state") == "HEALTHY"
        and value.get("lkg_required") is False
    )


def compatible_previous(
    candidate: Mapping[str, Any],
    *,
    current: Mapping[str, Any],
    exact_module: Any,
    call_id: str,
) -> bool:
    try:
        exact_module.validate_evidence(candidate)
    except Exception:
        return False
    if candidate.get("official_call_identifier") != call_id:
        return False
    if candidate.get("identity_key") != current.get("identity_key"):
        return False
    if not healthy(candidate):
        return False
    try:
        if parse_time(candidate.get("fetched_at")) >= parse_time(current.get("fetched_at")):
            return False
    except Exception:
        return False
    return True


def acquire_current(
    cfg: CallConfig,
    *,
    root: pathlib.Path,
    repo_root: pathlib.Path,
    exact_module: Any,
) -> dict[str, Any]:
    ingest = repo_root / "partener-eu" / "ingest"
    current_dir = root / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    run_id = (
        os.environ.get("EEA_CSF_EXACT_RUN_ID")
        or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-eea-csf-call{cfg.call_id}"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ingest)
    run(
        [
            sys.executable,
            str(ingest / f"{cfg.exact_module}.py"),
            "--run-id",
            run_id,
            "--output-dir",
            str(current_dir),
        ],
        env=env,
    )
    current = load(current_dir / cfg.evidence_filename)
    exact_module.validate_evidence(current)
    if current.get("official_call_identifier") != cfg.call_id:
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} current identity drift")
    return current


def restore_previous(
    cfg: CallConfig,
    *,
    root: pathlib.Path,
    current: Mapping[str, Any],
    exact_module: Any,
    allow_legacy_history: bool,
) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = (
        os.environ.get("EXPECTED_HEAD_BRANCH")
        or os.environ.get("GITHUB_HEAD_REF")
        or os.environ.get("GITHUB_REF_NAME", "")
    )
    scratch = pathlib.Path(f"/tmp/partener-eu-eea-csf-call{cfg.call_id}-canonical-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_path = scratch / "artifacts.json"
    with artifacts_path.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    data = load(artifacts_path)

    rows: list[tuple[int, str, int, str]] = []
    for artifact in data.get("artifacts") or []:
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True:
            continue
        if name.startswith(CANONICAL_ARTIFACT_PREFIX):
            source_priority = 0
        elif allow_legacy_history and any(name.startswith(prefix) for prefix in cfg.legacy_artifact_prefixes):
            source_priority = 1
        else:
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append(
            (
                source_priority,
                str(artifact.get("created_at") or ""),
                int(artifact.get("id") or 0),
                name,
            )
        )
    rows.sort(key=lambda row: row[1], reverse=True)
    rows.sort(key=lambda row: row[0])

    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_source_kind": None,
        "restore_reason": "NO_PREVIOUS_HEALTHY_SAME_IDENTITY",
        "official_call_identifier": cfg.call_id,
        "lkg_is_current_truth": False,
    }

    for source_priority, _, artifact_id, artifact_name in rows[:30]:
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(unpack)
        except zipfile.BadZipFile:
            continue

        candidates = sorted(unpack.rglob(cfg.evidence_filename), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                continue
            if not compatible_previous(
                candidate,
                current=current,
                exact_module=exact_module,
                call_id=cfg.call_id,
            ):
                continue
            dump(previous_dir / cfg.evidence_filename, candidate)
            metadata.update(
                {
                    "previous_found": True,
                    "artifact_id": artifact_id,
                    "artifact_name": artifact_name,
                    "restore_source_kind": "OFFICIAL_PROGRAMME_CANONICAL" if source_priority == 0 else "LEGACY_CALL_PROOF",
                    "restore_reason": "SAME_IDENTITY_HEALTHY_STRICTLY_OLDER",
                    "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                    "restored_fetched_at": candidate.get("fetched_at"),
                    "restored_source_health_state": candidate.get("source_health_state"),
                }
            )
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata

    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def reconcile_current(
    cfg: CallConfig,
    *,
    root: pathlib.Path,
    repo_root: pathlib.Path,
    restore: Mapping[str, Any],
) -> None:
    ingest = repo_root / "partener-eu" / "ingest"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ingest)
    cmd = [
        sys.executable,
        str(ingest / f"{cfg.reconcile_module}.py"),
        str(root / "current" / cfg.evidence_filename),
    ]
    previous_path = root / "previous" / cfg.evidence_filename
    if restore.get("previous_found") is True and previous_path.exists():
        cmd += ["--previous", str(previous_path)]
    cmd += ["--output", str(root / "current" / cfg.reconciliation_filename)]
    run(cmd, env=env)


def enforce_boundary(
    cfg: CallConfig,
    *,
    root: pathlib.Path,
    exact_module: Any,
    reconcile_module: Any,
) -> dict[str, Any]:
    current = load(root / "current" / cfg.evidence_filename)
    previous_path = root / "previous" / cfg.evidence_filename
    previous = load(previous_path) if previous_path.exists() else None
    reconciliation = load(root / "current" / cfg.reconciliation_filename)

    exact_module.validate_evidence(current)
    reconcile_module.validate_receipt(reconciliation, current=current, previous=previous)

    if current.get("official_call_identifier") != cfg.call_id:
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} official identifier drift")
    if current.get("call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} identifier kind drift")
    if current.get("observation_state") != "EXACT_CURRENT_CALL_NON_AUTHORIZING":
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} observation-state drift")
    if not re.fullmatch(r"[0-9a-f]{64}", str(current.get("identity_key") or "")):
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} identity hash missing")
    if any(current.get(flag) is not False for flag in FLAGS) or any(
        reconciliation.get(flag) is not False for flag in FLAGS
    ):
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} crossed material boundary")
    for row in (current, reconciliation):
        if row.get("publication_effect") != "NONE" or row.get("canonical_corpus_mutation") is not False:
            raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} crossed publication boundary")
    if reconciliation.get("lkg_reference_is_current_truth") is not False:
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} promoted LKG to current truth")
    if reconciliation.get("field_scoped_material_admission_required") is not True:
        raise SystemExit(f"FAIL EEA CSF Call {cfg.call_id} skipped field-scoped material admission")

    if healthy(current):
        if current.get("discovery_link_verified") is not True:
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} lost discovery binding")
        if current.get("candidate_state") not in {"OPEN_CALL", "CLOSED_CALL", "UNKNOWN"}:
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} candidate state drift")
        if not re.fullmatch(r"[0-9a-f]{64}", str(current.get("exact_semantic_fingerprint") or "")):
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} semantic hash missing")
        receipts = current.get("source_receipts") or {}
        if set(receipts) != {"official_calls_index_discovery", "official_exact_call_detail"}:
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} receipt inventory drift")
        for name, receipt in receipts.items():
            if (
                receipt.get("health_state") != "HEALTHY"
                or receipt.get("http_status") != 200
                or receipt.get("lkg_required") is not False
            ):
                raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} source degraded: {name}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("raw_sha256") or "")):
                raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} raw hash missing: {name}")
        if reconciliation.get("semantic_reconciliation_passed") is not True:
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} reconciliation failed")
        if reconciliation.get("lkg_reference_required") is not False:
            raise SystemExit(f"FAIL healthy EEA CSF Call {cfg.call_id} incorrectly required LKG")
    else:
        if current.get("source_health_state") != "DEGRADED" or current.get("lkg_required") is not True:
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} health contract drift")
        if current.get("candidate_state") != "UNKNOWN":
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} retained candidate state")
        if reconciliation.get("reconciliation_state") != "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED":
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} did not fail closed")
        if reconciliation.get("semantic_reconciliation_passed") is not False:
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} fabricated reconciliation")
        if reconciliation.get("semantic_change_count") != 0 or reconciliation.get("semantic_changes") != []:
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} fabricated semantic changes")
        if reconciliation.get("lkg_reference_required") is not True:
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} did not require LKG")
        if reconciliation.get("material_admission_ready_for_downstream_review") is not False:
            raise SystemExit(f"FAIL degraded EEA CSF Call {cfg.call_id} reached material review")

    return {
        "official_call_identifier": cfg.call_id,
        "source_health_state": current.get("source_health_state"),
        "candidate_state": current.get("candidate_state"),
        "status_label": current.get("status_label"),
        "reconciliation_state": reconciliation.get("reconciliation_state"),
        "semantic_change_count": reconciliation.get("semantic_change_count"),
        "previous_same_identity_present": previous is not None,
        "material_admission_ready_for_downstream_review": reconciliation.get(
            "material_admission_ready_for_downstream_review"
        ),
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(cfg: CallConfig, *, root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / cfg.evidence_filename
    previous_path = root / "previous" / cfg.evidence_filename
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)

    if healthy(current):
        shutil.copy2(current_path, history / cfg.evidence_filename)
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists():
        previous = load(previous_path)
        if healthy(previous):
            shutil.copy2(previous_path, history / cfg.evidence_filename)
            selected = "PREVIOUS_HEALTHY_LKG"
        else:
            selected = "NO_HEALTHY_LKG_AVAILABLE"
    else:
        selected = "NO_HEALTHY_LKG_AVAILABLE"

    result = {
        "selected": selected,
        "official_call_identifier": cfg.call_id,
        "current_source_health_state": current.get("source_health_state"),
        "current_candidate_state": current.get("candidate_state"),
        "previous_same_identity_present": previous_path.exists(),
        "lkg_is_current_truth": False,
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }
    dump(history / "history-selection.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--call-id", required=True, choices=sorted(CONFIGS))
    parser.add_argument("--root", type=pathlib.Path)
    parser.add_argument("--allow-legacy-history", action="store_true")
    args = parser.parse_args()

    cfg = CONFIGS[args.call_id]
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    if str(ingest) not in sys.path:
        sys.path.insert(0, str(ingest))
    exact_module = importlib.import_module(cfg.exact_module)
    reconcile_module = importlib.import_module(cfg.reconcile_module)

    root = args.root or pathlib.Path(
        f"/tmp/partener-eu-official-programme-intelligence/eea-csf-call{cfg.call_id}"
    )
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    current = acquire_current(
        cfg,
        root=root,
        repo_root=repo_root,
        exact_module=exact_module,
    )
    restore = restore_previous(
        cfg,
        root=root,
        current=current,
        exact_module=exact_module,
        allow_legacy_history=args.allow_legacy_history,
    )
    reconcile_current(cfg, root=root, repo_root=repo_root, restore=restore)
    boundary = enforce_boundary(
        cfg,
        root=root,
        exact_module=exact_module,
        reconcile_module=reconcile_module,
    )
    history = stage_history(cfg, root=root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
