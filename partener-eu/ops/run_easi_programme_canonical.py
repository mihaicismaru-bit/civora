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
SNAPSHOT_SCHEMA = "PARTENER_EU_EASI_PROGRAMME_INTELLIGENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_EASI_PROGRAMME_RECONCILIATION_V1"
PROGRAMME_ID = "ESF_PLUS_EASI"
ARTIFACT_PREFIXES = (
    "partener-eu-eu-direct-programme-intelligence-",
    "partener-eu-easi-programme-history-",
    "partener-eu-easi-programme-proof-",
)


def run(cmd: list[str], *, stdout=None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def expected_inventory(registry: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("url") or ""),
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
        for row in snapshot.get("evidence") or []
    )


def candidate_priority(path: pathlib.Path) -> tuple[int, str]:
    text = path.as_posix().casefold()
    if "/history/" in text or text.endswith("/history/easi-programme-intelligence.json"):
        return (0, text)
    if "/current/" in text:
        return (1, text)
    return (2, text)


def restore_previous(root: pathlib.Path, registry: dict[str, Any]) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-easi-canonical-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    data = load(artifacts_json)
    rows: list[tuple[str, int, str]] = []
    for artifact in data.get("artifacts") or []:
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True or not name.startswith(ARTIFACT_PREFIXES):
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    rows.sort(reverse=True)

    expected = expected_inventory(registry)
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_ARTIFACT",
        "expected_source_inventory": expected,
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
        candidates = sorted(unpack.rglob("easi-programme-intelligence.json"), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                continue
            if candidate.get("schema") != SNAPSHOT_SCHEMA or candidate.get("programme_id") != PROGRAMME_ID:
                continue
            inventory = snapshot_inventory(candidate)
            if inventory != expected:
                continue
            dump(previous_dir / "easi-programme-intelligence.json", candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_reason": "SAME_PROGRAMME_SOURCE_IDENTITY",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    current = load(root / "current" / "easi-programme-intelligence.json")
    reconciliation = load(root / "current" / "easi-programme-reconciliation.json")
    if current.get("schema") != SNAPSHOT_SCHEMA or current.get("source_family") != "EU_DIRECT" or current.get("programme_id") != PROGRAMME_ID:
        raise SystemExit("FAIL EaSI canonical snapshot identity drift")
    if current.get("source_count") != 4 or int(current.get("healthy_source_count") or 0) + int(current.get("degraded_source_count") or 0) != 4:
        raise SystemExit("FAIL EaSI canonical source inventory/health accounting drift")
    if current.get("source_health_state") not in {"HEALTHY", "DEGRADED"}:
        raise SystemExit("FAIL EaSI canonical source health state drift")
    if current.get("market_intelligence_only") is not True or current.get("fit_score_is_not_eligibility") is not True or current.get("partner_intelligence_is_not_call_eligibility") is not True:
        raise SystemExit("FAIL EaSI canonical intelligence boundary weakened")
    if any(current.get(flag) is not False for flag in FLAGS) or any(reconciliation.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL EaSI canonical lane became materially authorizing")
    if current.get("publication_effect") != "NONE" or reconciliation.get("publication_effect") != "NONE":
        raise SystemExit("FAIL EaSI canonical publication boundary drift")
    states = {str(row.get("observation_state") or "") for row in current.get("evidence") or []}
    if states != {"PROGRAMME_INTELLIGENCE", "APPLICATION_ROUTE_INTELLIGENCE", "PROGRAMMING_PIPELINE", "PARTNER_INTELLIGENCE"}:
        raise SystemExit("FAIL EaSI canonical observation-state drift")
    for row in current.get("evidence") or []:
        if row.get("source_health") == "HEALTHY":
            if row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise SystemExit("FAIL healthy EaSI canonical receipt inconsistent")
            for key in ("raw_sha256", "normalized_visible_text_sha256", "source_semantic_fingerprint"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key) or "")):
                    raise SystemExit(f"FAIL healthy EaSI canonical receipt missing {key}")
        else:
            if row.get("source_health") != "DEGRADED" or row.get("lkg_required") is not True or row.get("source_semantic_fingerprint") is not None:
                raise SystemExit("FAIL degraded EaSI canonical receipt inconsistent")
    if reconciliation.get("schema") != RECONCILIATION_SCHEMA or reconciliation.get("programme_id") != PROGRAMME_ID:
        raise SystemExit("FAIL EaSI canonical reconciliation identity drift")
    if reconciliation.get("material_admission_ready_for_downstream_review") is not False or reconciliation.get("lkg_reference_is_current_truth") is not False:
        raise SystemExit("FAIL EaSI canonical material/LKG boundary drift")
    if current.get("source_health_state") == "DEGRADED":
        if reconciliation.get("reconciliation_state") != "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED":
            raise SystemExit("FAIL degraded EaSI current did not fail closed")
        if reconciliation.get("semantic_reconciliation_passed") is not False or reconciliation.get("semantic_change_count") != 0 or reconciliation.get("pipeline_watch_candidate") is not False or reconciliation.get("lkg_reference_required") is not True:
            raise SystemExit("FAIL degraded EaSI canonical reconciliation semantics drift")
    else:
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING", "NO_CHANGE",
            "EASI_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if reconciliation.get("reconciliation_state") not in allowed or reconciliation.get("semantic_reconciliation_passed") is not True:
            raise SystemExit("FAIL healthy EaSI canonical reconciliation state drift")
    return {
        "programme": "ESF+ EaSI",
        "source_health": current["source_health_state"],
        "healthy_sources": current["healthy_source_count"],
        "degraded_sources": current["degraded_source_count"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "pipeline_watch_candidate": reconciliation["pipeline_watch_candidate"],
        "open_call_authorized": False,
        "eligibility_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / "easi-programme-intelligence.json"
    previous_path = root / "previous" / "easi-programme-intelligence.json"
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY":
        shutil.copy2(current_path, history / "easi-programme-intelligence.json")
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists() and load(previous_path).get("source_health_state") == "HEALTHY":
        shutil.copy2(previous_path, history / "easi-programme-intelligence.json")
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


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    ops = repo_root / "partener-eu" / "ops"
    registry_path = ingest / "eu_direct_easi_programme_intelligence_registry.json"
    registry = load(registry_path)
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/easi-programme")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    run([sys.executable, str(ops / "test_eu_direct_easi_programme_intelligence.py"), "-v"])
    run([sys.executable, str(ops / "test_eu_direct_easi_programme_reconcile.py"), "-v"])

    restore = restore_previous(root, registry)
    run_id = os.environ.get("EASI_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-easi"
    current_path = root / "current" / "easi-programme-intelligence.json"
    run([
        sys.executable, str(ingest / "eu_direct_easi_programme_intelligence.py"),
        "--registry", str(registry_path), "--run-id", run_id, "--output", str(current_path),
    ])
    shutil.copy2(registry_path, root / "current" / "registry.json")

    reconcile_cmd = [
        sys.executable, str(ingest / "eu_direct_easi_programme_reconcile.py"),
        str(current_path),
    ]
    previous_path = root / "previous" / "easi-programme-intelligence.json"
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    reconcile_cmd += ["--output", str(root / "current" / "easi-programme-reconciliation.json")]
    run(reconcile_cmd)

    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
