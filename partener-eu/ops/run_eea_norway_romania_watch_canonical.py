#!/usr/bin/env python3
"""Canonical history/LKG runner for the Romania EEA/Norway programme + call-discovery watch."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import zipfile
from typing import Any

from eea_norway_romania_programme_watch import (
    CIVIL_SOCIETY_CALLS_URL,
    EEA_MOU_URL,
    NFP_DIRECTORY_URL,
    NORWAY_MOU_URL,
    ROMANIA_COOPERATION_URL,
    collect,
)
from eea_norway_romania_programme_watch_reconcile import (
    MATERIAL_FLAGS,
    RECONCILIATION_SCHEMA,
    build_degraded_snapshot,
    prepare_healthy_snapshot,
    reconcile,
    validate_snapshot,
)

ARTIFACT_PREFIXES = (
    "partener-eu-official-programme-intelligence-",
)
ROOT = pathlib.Path(os.environ.get("EEA_NORWAY_WATCH_ROOT", "/tmp/partener-eu-eea-norway-romania-watch-proof"))
CURRENT_NAME = "eea-norway-romania-programme-watch.json"
RECON_NAME = "eea-norway-romania-programme-watch-reconciliation.json"
RAW_NAMES = {
    "romania-cooperation": "romania-cooperation.html",
    "eea-mou": "romania-eea-mou.html",
    "norway-mou": "romania-norway-mou.html",
    "nfp-directory": "fmo-national-focal-points.html",
    "civil-society-calls": "romania-civil-society-calls.html",
}
EXPECTED_AUTHORITY_URLS = (
    ROMANIA_COOPERATION_URL,
    EEA_MOU_URL,
    NORWAY_MOU_URL,
    NFP_DIRECTORY_URL,
    CIVIL_SOCIETY_CALLS_URL,
)


def run(cmd: list[str], *, stdout=None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


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
    if "ANCHOR" in text or "DRIFT" in text:
        return "SEMANTIC_AUTHORITY_DRIFT"
    return "ACQUISITION_ERROR"


def _candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text:
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def restore_previous(root: pathlib.Path, current: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_EEA_NORWAY_ROMANIA_WATCH_ARTIFACT",
    }
    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("GITHUB_REPOSITORY") or not os.environ.get("GH_TOKEN"):
        metadata["restore_reason"] = "GITHUB_HISTORY_CONTEXT_UNAVAILABLE"
        dump(previous_dir / "restore-metadata.json", metadata)
        return metadata

    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-eea-norway-romania-watch-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    rows: list[tuple[str, int, str]] = []
    for artifact in load(artifacts_json).get("artifacts") or []:
        name = str(artifact.get("name") or "")
        workflow_run = artifact.get("workflow_run") or {}
        if artifact.get("expired") is True or not any(name.startswith(prefix) for prefix in ARTIFACT_PREFIXES):
            continue
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    rows.sort(key=lambda row: row[0], reverse=True)

    for _, artifact_id, artifact_name in rows[:30]:
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        for candidate_path in sorted(unpack.rglob(CURRENT_NAME), key=_candidate_priority):
            try:
                candidate = load(candidate_path)
                validate_snapshot(candidate)
            except Exception:
                continue
            if candidate.get("source_health") != "HEALTHY":
                continue
            if tuple(candidate.get("authority_urls") or ()) != tuple(current.get("authority_urls") or ()):
                continue
            if candidate.get("source_family") != current.get("source_family") or candidate.get("programme_family") != current.get("programme_family"):
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
                "restore_reason": "SAME_BOUNDED_AUTHORITY_IDENTITY_HEALTHY_STRICTLY_OLDER",
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
    if current.get("source_health") == "HEALTHY":
        shutil.copy2(current_path, history / CURRENT_NAME)
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists() and load(previous_path).get("source_health") == "HEALTHY":
        shutil.copy2(previous_path, history / CURRENT_NAME)
        selected = "PREVIOUS_HEALTHY_LKG"
    else:
        selected = "NO_HEALTHY_LKG_AVAILABLE"
    result = {
        "selected": selected,
        "current_source_health": current.get("source_health"),
        "lkg_is_current_truth": False,
    }
    dump(history / "history-selection.json", result)
    return result


def enforce_boundary(current: dict[str, Any], rec: dict[str, Any], history: dict[str, Any]) -> None:
    validate_snapshot(current)
    if rec.get("schema") != RECONCILIATION_SCHEMA:
        raise SystemExit("FAIL EEA/Norway Romania watch reconciliation schema drift")
    if tuple(sorted(current.get("authority_urls") or ())) != tuple(sorted(EXPECTED_AUTHORITY_URLS)):
        raise SystemExit("FAIL EEA/Norway Romania watch authority inventory drift")
    for flag in MATERIAL_FLAGS:
        if current.get(flag) is not False or rec.get(flag) is not False:
            raise SystemExit(f"FAIL EEA/Norway Romania watch materially authorized {flag}")
    if current.get("current_material_truth_available") is not False or rec.get("current_material_truth_available") is not False:
        raise SystemExit("FAIL EEA/Norway Romania watch became current material truth")
    if rec.get("lkg_reference_is_current_truth") is not False or history.get("lkg_is_current_truth") is not False:
        raise SystemExit("FAIL EEA/Norway Romania watch LKG became current truth")
    if current.get("source_health") == "DEGRADED" and rec.get("reconciliation_state") != "CURRENT_EEA_NORWAY_ROMANIA_WATCH_DEGRADED_LKG_REQUIRED":
        raise SystemExit("FAIL EEA/Norway Romania watch degradation did not fail closed")


def main() -> int:
    root = ROOT
    shutil.rmtree(root, ignore_errors=True)
    (root / "current" / "raw").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)
    run_id = os.environ.get("EEA_NORWAY_WATCH_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-eea-norway-romania-watch"
    fetched_at = utc_now()
    try:
        receipt, raw = collect(run_id=run_id, fetched_at=fetched_at)
        current = prepare_healthy_snapshot(receipt)
        for key, body in raw.items():
            (root / "current" / "raw" / RAW_NAMES[key]).write_bytes(body)
    except Exception as exc:
        current = build_degraded_snapshot(
            run_id=run_id,
            fetched_at=fetched_at,
            failure_class=classify_failure(exc),
            failure_detail=f"{type(exc).__name__}: {exc}",
        )
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
        "source_health": current["source_health"],
        "programme_count": len(current.get("programmes") or []),
        "call_discovery_count": len(current.get("call_discovery") or []),
        "previous_artifact_id": restore.get("artifact_id"),
        "previous_artifact_name": restore.get("artifact_name"),
        "reconciliation_state": rec["reconciliation_state"],
        "semantic_change_count": rec["semantic_change_count"],
        "programming_watch_candidate": rec["programming_watch_candidate"],
        "call_index_discovery_watch_candidate": rec["call_index_discovery_watch_candidate"],
        "history_selected": history["selected"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
