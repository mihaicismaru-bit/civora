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
SNAPSHOT_SCHEMA = "PARTENER_EU_MFF_2028_2034_PROGRAMMING_PIPELINE_V2"
RECONCILIATION_SCHEMA = "PARTENER_EU_MFF_2028_2034_PROGRAMMING_RECONCILIATION_V2"
PARSER_VERSION = "MFF_2028_2034_PROGRAMMING_PIPELINE_V2"
PROGRAMME_FAMILY = "MFF_2028_2034"
CANONICAL_ARTIFACT_PREFIX = "partener-eu-programming-pipeline-"
LEGACY_ARTIFACT_PREFIXES = (
    "partener-eu-mff-2028-2034-programming-history-",
    "partener-eu-mff-2028-2034-programming-proof-",
)


def run(cmd: list[str], *, stdout=None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout, env=env)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def expected_inventory(registry: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
        )
        for row in registry.get("sources") or []
    )


def snapshot_inventory(snapshot: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
        )
        for row in snapshot.get("sources") or []
    )


def candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text:
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def restore_previous(root: pathlib.Path, registry: dict[str, Any]) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-mff-programming-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    data = load(artifacts_json)
    rows: list[tuple[int, str, int, str]] = []
    for artifact in data.get("artifacts") or []:
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True:
            continue
        if name.startswith(CANONICAL_ARTIFACT_PREFIX):
            source_rank = 0
        elif name.startswith(LEGACY_ARTIFACT_PREFIXES):
            source_rank = 1
        else:
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((source_rank, str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    rows.sort(key=lambda row: (row[0], "".join(chr(255 - ord(c)) for c in row[1])))

    expected = expected_inventory(registry)
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_source_kind": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_V2_ARTIFACT",
        "expected_source_inventory": expected,
    }
    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)

    # Re-sort each rank newest-first without relying on artifact listing order.
    for source_rank in (0, 1):
        ranked = [row for row in rows if row[0] == source_rank]
        ranked.sort(key=lambda row: row[1], reverse=True)
        for _, _, artifact_id, artifact_name in ranked:
            archive_path = scratch / f"{artifact_id}.zip"
            with archive_path.open("wb") as output:
                run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
            unpack = scratch / f"unpack-{artifact_id}"
            unpack.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(unpack)
            candidates = sorted(unpack.rglob("mff-2028-2034-programming-pipeline.json"), key=candidate_priority)
            for candidate_path in candidates:
                try:
                    candidate = load(candidate_path)
                except Exception:
                    continue
                if candidate.get("schema") != SNAPSHOT_SCHEMA or candidate.get("parser_version") != PARSER_VERSION:
                    continue
                if candidate.get("source_family") != "PROGRAMMING_PIPELINE" or candidate.get("programme_family") != PROGRAMME_FAMILY:
                    continue
                if snapshot_inventory(candidate) != expected:
                    continue
                dump(previous_dir / "mff-2028-2034-programming-pipeline.json", candidate)
                metadata.update({
                    "previous_found": True,
                    "artifact_id": artifact_id,
                    "artifact_name": artifact_name,
                    "restore_source_kind": "CANONICAL_PROGRAMMING_PIPELINE" if source_rank == 0 else "LEGACY_MFF_PROOF_OR_HISTORY",
                    "restore_reason": "SAME_PROGRAMMING_SOURCE_IDENTITY",
                    "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                    "restored_fetched_at": candidate.get("fetched_at"),
                    "restored_parser_version": candidate.get("parser_version"),
                })
                dump(previous_dir / "restore-metadata.json", metadata)
                return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    current = load(root / "current" / "mff-2028-2034-programming-pipeline.json")
    rec = load(root / "current" / "mff-2028-2034-programming-reconciliation.json")
    if current.get("schema") != SNAPSHOT_SCHEMA or current.get("parser_version") != PARSER_VERSION:
        raise SystemExit("FAIL MFF canonical schema/parser drift")
    if current.get("source_family") != "PROGRAMMING_PIPELINE" or current.get("programme_family") != PROGRAMME_FAMILY:
        raise SystemExit("FAIL MFF canonical family drift")
    if current.get("programme_period") != "2028-2034" or current.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise SystemExit("FAIL MFF canonical programme/observation drift")
    if current.get("source_count") != 9:
        raise SystemExit("FAIL MFF canonical bounded source inventory drift")
    if int(current.get("healthy_source_count") or 0) + int(current.get("degraded_source_count") or 0) != 9:
        raise SystemExit("FAIL MFF canonical health accounting drift")
    if current.get("market_intelligence_only") is not True or current.get("fit_is_not_eligibility") is not True:
        raise SystemExit("FAIL MFF canonical market/fit boundary weakened")
    if any(current.get(flag) is not False for flag in FLAGS) or any(rec.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL MFF canonical lane became materially authorizing")
    if current.get("publication_effect") != "NONE" or rec.get("publication_effect") != "NONE":
        raise SystemExit("FAIL MFF canonical publication boundary drift")
    states = {str(row.get("observation_state") or "") for row in current.get("sources") or []}
    if not states or not states.issubset({"PROPOSAL", "CONSULTATION", "PLANNED", "PROGRAMMING_PROCESS"}):
        raise SystemExit("FAIL MFF canonical source crossed programming-only states")
    if "PROGRAMMING_PROCESS" not in states:
        raise SystemExit("FAIL MFF canonical source expansion lost Council programming progress")
    for row in current.get("sources") or []:
        if row.get("fit_is_not_eligibility") is not True or row.get("market_intelligence_only") is not True:
            raise SystemExit("FAIL MFF source fit boundary weakened")
        if row.get("source_health") == "HEALTHY":
            if row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise SystemExit("FAIL healthy MFF source receipt inconsistent")
            for key in ("raw_sha256", "normalized_visible_text_sha256", "source_semantic_fingerprint"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key) or "")):
                    raise SystemExit(f"FAIL healthy MFF source missing {key}")
        elif row.get("source_health") == "DEGRADED":
            if row.get("lkg_required") is not True or row.get("source_semantic_fingerprint") is not None:
                raise SystemExit("FAIL degraded MFF source weakened fail-closed state")
        else:
            raise SystemExit("FAIL MFF source health state drift")
    if rec.get("schema") != RECONCILIATION_SCHEMA:
        raise SystemExit("FAIL MFF reconciliation schema drift")
    if rec.get("lkg_reference_is_current_truth") is not False or rec.get("material_admission_ready_for_downstream_review") is not False:
        raise SystemExit("FAIL MFF LKG/material boundary drift")
    if current.get("source_health_state") == "DEGRADED":
        if current.get("semantic_fingerprint") is not None:
            raise SystemExit("FAIL degraded MFF current emitted semantic fingerprint")
        if rec.get("reconciliation_state") != "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED":
            raise SystemExit("FAIL degraded MFF current did not fail closed")
        if rec.get("semantic_reconciliation_passed") is not False or rec.get("semantic_change_count") != 0 or rec.get("pipeline_watch_candidate") is not False:
            raise SystemExit("FAIL degraded MFF current generated semantic change")
    else:
        if not re.fullmatch(r"[0-9a-f]{64}", str(current.get("semantic_fingerprint") or "")):
            raise SystemExit("FAIL healthy MFF canonical semantic fingerprint missing")
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "MFF_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
            "PARSER_VERSION_CHANGED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if rec.get("reconciliation_state") not in allowed or rec.get("semantic_reconciliation_passed") is not True:
            raise SystemExit("FAIL healthy MFF canonical reconciliation drift")
    return {
        "programme_family": PROGRAMME_FAMILY,
        "source_health_state": current["source_health_state"],
        "healthy_source_count": current["healthy_source_count"],
        "degraded_source_count": current["degraded_source_count"],
        "reconciliation_state": rec["reconciliation_state"],
        "semantic_change_count": rec["semantic_change_count"],
        "pipeline_watch_candidate": rec["pipeline_watch_candidate"],
        "source_health_watch_candidate": rec["source_health_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / "mff-2028-2034-programming-pipeline.json"
    previous_path = root / "previous" / "mff-2028-2034-programming-pipeline.json"
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY":
        shutil.copy2(current_path, history / "mff-2028-2034-programming-pipeline.json")
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists() and load(previous_path).get("source_health_state") == "HEALTHY":
        shutil.copy2(previous_path, history / "mff-2028-2034-programming-pipeline.json")
        selected = "PREVIOUS_HEALTHY_LKG"
    else:
        selected = "NO_HEALTHY_LKG_AVAILABLE"
    result = {
        "selected": selected,
        "current_source_health_state": current.get("source_health_state"),
        "lkg_is_current_truth": False,
    }
    dump(history / "history-selection.json", result)
    return result


def run_regressions(repo_root: pathlib.Path) -> None:
    env = os.environ.copy()
    paths = [str(repo_root / "partener-eu" / "ingest"), str(repo_root / "partener-eu" / "ops")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    run([sys.executable, str(repo_root / "partener-eu" / "ops" / "test_mff_2028_2034_programming_pipeline.py")], env=env)


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    registry_path = ingest / "mff_2028_2034_programming_pipeline_registry.json"
    registry = load(registry_path)
    root = pathlib.Path("/tmp/partener-eu-programming-pipeline/mff-2028-2034")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    run_regressions(repo_root)
    restore = restore_previous(root, registry)
    run_id = os.environ.get("MFF_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-mff"
    run([
        sys.executable,
        str(ingest / "mff_2028_2034_programming_pipeline.py"),
        "--registry", str(registry_path),
        "--output-dir", str(root / "current"),
        "--run-id", run_id,
    ])
    shutil.copy2(registry_path, root / "current" / "registry.json")

    current_path = root / "current" / "mff-2028-2034-programming-pipeline.json"
    reconcile_cmd = [
        sys.executable,
        str(ingest / "mff_2028_2034_programming_pipeline_reconcile.py"),
        str(current_path),
    ]
    previous_path = root / "previous" / "mff-2028-2034-programming-pipeline.json"
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    reconcile_cmd += ["--output", str(root / "current" / "mff-2028-2034-programming-reconciliation.json")]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ingest), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    run(reconcile_cmd, env=env)

    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history, "regressions": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
