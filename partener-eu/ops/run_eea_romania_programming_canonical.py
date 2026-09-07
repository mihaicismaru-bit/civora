#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile
from typing import Any

from eea_romania_programming_intelligence import (
    AUTHORITY_CLASS,
    PARSER_VERSION,
    PROGRAMME_FAMILY,
    SOURCE_FAMILY,
    SOURCE_URL,
    collect_live,
)
from eea_romania_programming_intelligence_reconcile import (
    EXPECTED_PROGRAMME_COUNT,
    MATERIAL_FLAGS,
    RECONCILIATION_SCHEMA,
    SNAPSHOT_SCHEMA,
    reconcile,
    validate_snapshot,
)

CANONICAL_ARTIFACT_PREFIX = "partener-eu-programming-pipeline-"
ROOT = pathlib.Path("/tmp/partener-eu-programming-pipeline/eea-romania")
CURRENT_NAME = "eea-romania-programming-intelligence.json"
RECON_NAME = "eea-romania-programming-reconciliation.json"
# Replay marker: this canonical lane intentionally persists EEA programming history inside the shared artifact.


def run(cmd: list[str], *, stdout=None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout, env=env)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def classify_failure(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".upper()
    if "HTTP ERROR 403" in text or "HTTP 403" in text:
        return "HTTP_403_FORBIDDEN"
    if "HTTP ERROR 404" in text or "HTTP 404" in text:
        return "HTTP_404_NOT_FOUND"
    if "CERTIFICATE" in text or "SSL" in text:
        return "TLS_ERROR"
    if "TIMEOUT" in text or "TIMED OUT" in text:
        return "TIMEOUT"
    if "PROGRAMME" in text and "DRIFT" in text:
        return "SEMANTIC_PROGRAMME_MAP_DRIFT"
    return "ACQUISITION_ERROR"


def augment_healthy(payload: dict[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    fingerprints = [
        {"programme_id": row.get("programme_id"), "semantic_fingerprint": row.get("semantic_fingerprint")}
        for row in sorted(value.get("records") or [], key=lambda row: str(row.get("programme_id") or ""))
    ]
    value.update({
        "source_health_state": "HEALTHY",
        "healthy_source_count": 1,
        "degraded_source_count": 0,
        "evidence_usable_for_reconciliation": True,
        "lkg_required": False,
        "semantic_fingerprint": sha256_json(fingerprints),
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "current_material_truth_available": False,
        "closed_call_authorized": False,
        "call_alert_authorized": False,
    })
    for flag in MATERIAL_FLAGS:
        value[flag] = False
    return value


def degraded_receipt(*, run_id: str, exc: BaseException) -> dict[str, Any]:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "source": {
            "id": "SRC-EEA-FMO-ROMANIA-2021-2028-PROGRAMMES",
            "url": SOURCE_URL,
            "published_date": "2026-05-12",
            "http_status": None,
            "content_type": None,
            "raw_hash": None,
            "bytes": None,
        },
        "fetched_at": utc_now(),
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "records": [],
        "stats": {"programme_records": 0, "open_calls_authorized": 0},
        "observation_state": "PROGRAMMING_PIPELINE",
        "source_health_state": "DEGRADED",
        "healthy_source_count": 0,
        "degraded_source_count": 1,
        "evidence_usable_for_reconciliation": False,
        "lkg_required": True,
        "semantic_fingerprint": None,
        "failure_class": classify_failure(exc),
        "failure_detail": f"{type(exc).__name__}: {exc}"[:1000],
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "current_material_truth_available": False,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "requires_reconciliation": True,
        "publication_effect": "NONE",
    }


def candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text:
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def restore_previous(root: pathlib.Path, current: dict[str, Any]) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-eea-programming-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    artifacts = load(artifacts_json).get("artifacts") or []
    rows: list[tuple[str, int, str]] = []
    for artifact in artifacts:
        name = str(artifact.get("name") or "")
        workflow_run = artifact.get("workflow_run") or {}
        if artifact.get("expired") is True or not name.startswith(CANONICAL_ARTIFACT_PREFIX):
            continue
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    rows.sort(key=lambda row: row[0], reverse=True)
    metadata = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_EEA_PROGRAMMING_ARTIFACT",
    }
    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)

    for _, artifact_id, artifact_name in rows:
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        candidates = sorted(unpack.rglob(CURRENT_NAME), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
                validate_snapshot(candidate)
            except Exception:
                continue
            if candidate.get("source_health_state") != "HEALTHY":
                continue
            if candidate.get("source_family") != current.get("source_family") or candidate.get("programme_family") != current.get("programme_family"):
                continue
            if (candidate.get("source") or {}).get("id") != (current.get("source") or {}).get("id"):
                continue
            if (candidate.get("source") or {}).get("url") != (current.get("source") or {}).get("url"):
                continue
            try:
                old = dt.datetime.fromisoformat(str(candidate.get("fetched_at") or "").replace("Z", "+00:00"))
                new = dt.datetime.fromisoformat(str(current.get("fetched_at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if old.tzinfo is None or new.tzinfo is None or old >= new:
                continue
            dump(previous_dir / CURRENT_NAME, candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_reason": "SAME_EEA_PROGRAMMING_SOURCE_IDENTITY_HEALTHY_STRICTLY_OLDER",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / CURRENT_NAME
    previous_path = root / "previous" / CURRENT_NAME
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY":
        shutil.copy2(current_path, history / CURRENT_NAME)
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists() and load(previous_path).get("source_health_state") == "HEALTHY":
        shutil.copy2(previous_path, history / CURRENT_NAME)
        selected = "PREVIOUS_HEALTHY_LKG"
    else:
        selected = "NO_HEALTHY_LKG_AVAILABLE"
    result = {"selected": selected, "current_source_health_state": current.get("source_health_state"), "lkg_is_current_truth": False}
    dump(history / "history-selection.json", result)
    return result


def enforce_boundary(current: dict[str, Any], rec: dict[str, Any], history: dict[str, Any]) -> None:
    validate_snapshot(current)
    if rec.get("schema") != RECONCILIATION_SCHEMA:
        raise SystemExit("FAIL EEA programming reconciliation schema drift")
    for flag in MATERIAL_FLAGS:
        if current.get(flag) is not False or rec.get(flag) is not False:
            raise SystemExit(f"FAIL EEA programming materially authorized {flag}")
    if current.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise SystemExit("FAIL EEA programming observation crossed pipeline boundary")
    if current.get("publication_effect") != "NONE" or rec.get("publication_effect") != "NONE":
        raise SystemExit("FAIL EEA programming publication boundary drift")
    if rec.get("lkg_reference_is_current_truth") is not False or history.get("lkg_is_current_truth") is not False:
        raise SystemExit("FAIL EEA programming LKG became current truth")
    if current.get("source_health_state") == "HEALTHY":
        if len(current.get("records") or []) != EXPECTED_PROGRAMME_COUNT:
            raise SystemExit("FAIL EEA programming healthy inventory drift")
    elif rec.get("reconciliation_state") != "CURRENT_PROGRAMMING_AUTHORITY_DEGRADED_LKG_REQUIRED":
        raise SystemExit("FAIL EEA programming degraded source did not fail closed")


def main() -> int:
    root = ROOT
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)
    run_id = os.environ.get("EEA_PROGRAMMING_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-eea-romania"
    try:
        current = augment_healthy(collect_live(run_id=run_id))
    except Exception as exc:
        current = degraded_receipt(run_id=run_id, exc=exc)
    validate_snapshot(current)
    dump(root / "current" / CURRENT_NAME, current)

    restore = restore_previous(root, current)
    previous_path = root / "previous" / CURRENT_NAME
    previous = load(previous_path) if restore.get("previous_found") is True and previous_path.exists() else None
    rec = reconcile(current, previous)
    dump(root / "current" / RECON_NAME, rec)
    history = stage_history(root)
    enforce_boundary(current, rec, history)
    print(json.dumps({
        "source_health_state": current["source_health_state"],
        "programme_records": len(current.get("records") or []),
        "reconciliation_state": rec["reconciliation_state"],
        "semantic_change_count": rec["semantic_change_count"],
        "programming_watch_candidate": rec["programming_watch_candidate"],
        "history_selected": history["selected"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
