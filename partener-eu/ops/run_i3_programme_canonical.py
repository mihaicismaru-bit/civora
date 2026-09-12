#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
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
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)
SNAPSHOT_SCHEMA = "PARTENER_EU_I3_PROGRAMME_INTELLIGENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_I3_PROGRAMME_RECONCILIATION_V1"
PROGRAMME_ID = "I3"
ARTIFACT_PREFIXES = (
    "partener-eu-eu-direct-programme-intelligence-",
    "partener-eu-i3-programme-history-",
    "partener-eu-i3-programme-intelligence-proof-",
)


def run(cmd: list[str], *, stdout=None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def snapshot_inventory(snapshot: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
            str(row.get("call_reference_hint") or ""),
        )
        for row in snapshot.get("evidence") or []
    )


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
    scratch = pathlib.Path("/tmp/partener-eu-i3-canonical-history-scan")
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

    current_inventory = snapshot_inventory(current)
    current_time = parse_time(str(current["fetched_at"]))
    metadata: dict[str, Any] = {
        "previous_found": False,
        "artifact_id": None,
        "artifact_name": None,
        "restore_reason": "NO_PREVIOUS_HEALTHY_SAME_IDENTITY_STRICTLY_OLDER_ARTIFACT",
        "current_source_inventory": current_inventory,
        "current_fetched_at": current["fetched_at"],
        "rejected_candidates": [],
    }
    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)

    for _, artifact_id, artifact_name in rows:
        archive_path = scratch / f"{artifact_id}.zip"
        try:
            with archive_path.open("wb") as output:
                run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
            unpack = scratch / f"unpack-{artifact_id}"
            unpack.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(unpack)
        except Exception as exc:
            metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": f"ARTIFACT_READ_FAILED:{type(exc).__name__}"})
            continue
        candidates = sorted(unpack.rglob("i3-programme-intelligence.json"), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": "CANDIDATE_JSON_INVALID"})
                continue
            if candidate.get("schema") != SNAPSHOT_SCHEMA or candidate.get("programme_id") != PROGRAMME_ID:
                continue
            if snapshot_inventory(candidate) != current_inventory:
                metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": "SOURCE_IDENTITY_MISMATCH"})
                continue
            if candidate.get("source_health_state") != "HEALTHY" or int(candidate.get("degraded_source_count") or 0) != 0:
                metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": "PREVIOUS_NOT_HEALTHY"})
                continue
            try:
                candidate_time = parse_time(str(candidate.get("fetched_at") or ""))
            except Exception:
                metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": "PREVIOUS_FETCHED_AT_INVALID"})
                continue
            if candidate_time >= current_time:
                metadata["rejected_candidates"].append({"artifact_id": artifact_id, "reason": "PREVIOUS_NOT_STRICTLY_OLDER"})
                continue
            dump(previous_dir / "i3-programme-intelligence.json", candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_reason": "HEALTHY_SAME_PROGRAMME_SOURCE_IDENTITY_STRICTLY_OLDER",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    current = load(root / "current" / "i3-programme-intelligence.json")
    reconciliation = load(root / "current" / "i3-programme-reconciliation.json")
    if current.get("schema") != SNAPSHOT_SCHEMA or current.get("source_family") != "EU_DIRECT" or current.get("programme_id") != PROGRAMME_ID:
        raise SystemExit("FAIL I3 canonical snapshot identity drift")
    if current.get("programme_family") != "Interregional Innovation Investments (I3) Instrument":
        raise SystemExit("FAIL I3 canonical programme family drift")
    if current.get("authority_class") != "T1_EISMEA_OFFICIAL":
        raise SystemExit("FAIL I3 canonical authority drift")
    if current.get("source_count") != 5 or int(current.get("healthy_source_count") or 0) + int(current.get("degraded_source_count") or 0) != 5:
        raise SystemExit("FAIL I3 canonical source inventory/health accounting drift")
    if current.get("source_health_state") not in {"HEALTHY", "DEGRADED"}:
        raise SystemExit("FAIL I3 canonical source health state drift")
    for key in (
        "market_intelligence_only",
        "fit_score_is_not_eligibility",
        "geography_fit_is_not_eligibility",
        "partner_intelligence_is_not_call_eligibility",
        "structured_funding_tenders_reconciliation_required",
    ):
        if current.get(key) is not True:
            raise SystemExit(f"FAIL I3 canonical intelligence boundary weakened: {key}")
    if any(current.get(flag) is not False for flag in FLAGS) or any(reconciliation.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL I3 canonical lane became materially authorizing")
    if current.get("publication_effect") != "NONE" or reconciliation.get("publication_effect") != "NONE":
        raise SystemExit("FAIL I3 canonical publication boundary drift")
    states = {str(row.get("observation_state") or "") for row in current.get("evidence") or []}
    if states != {"PROGRAMME_INTELLIGENCE", "PROGRAMMING_PIPELINE", "PARTNER_INTELLIGENCE", "CALL_INDEX_DISCOVERY"}:
        raise SystemExit("FAIL I3 canonical observation-state drift")
    hints = set()
    for row in current.get("evidence") or []:
        if row.get("call_reference_hint"):
            if row.get("observation_state") != "CALL_INDEX_DISCOVERY" or row.get("call_reference_hint_authority") != "DISCOVERY_HINT_ONLY_NOT_CALL_IDENTIFIER":
                raise SystemExit("FAIL I3 canonical call hint widened beyond discovery")
            hints.add(str(row.get("call_reference_hint")))
        if row.get("source_health") == "HEALTHY":
            if row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise SystemExit("FAIL healthy I3 canonical receipt inconsistent")
            for key in ("raw_sha256", "normalized_visible_text_sha256", "source_semantic_fingerprint"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key) or "")):
                    raise SystemExit(f"FAIL healthy I3 canonical receipt missing {key}")
        else:
            if row.get("source_health") != "DEGRADED" or row.get("lkg_required") is not True or row.get("source_semantic_fingerprint") is not None:
                raise SystemExit("FAIL degraded I3 canonical receipt inconsistent")
    if hints != {"I3-2026-INV1", "I3-2026-INV2a"}:
        raise SystemExit("FAIL I3 canonical discovery hint inventory drift")
    if reconciliation.get("schema") != RECONCILIATION_SCHEMA or reconciliation.get("programme_id") != PROGRAMME_ID:
        raise SystemExit("FAIL I3 canonical reconciliation identity drift")
    if reconciliation.get("material_admission_ready_for_downstream_review") is not False or reconciliation.get("lkg_reference_is_current_truth") is not False:
        raise SystemExit("FAIL I3 canonical material/LKG boundary drift")
    if reconciliation.get("call_alert_authorized") is not False or reconciliation.get("distribution_authorized") is not False:
        raise SystemExit("FAIL I3 canonical watch became distribution authority")
    if current.get("source_health_state") == "DEGRADED":
        if reconciliation.get("reconciliation_state") != "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED":
            raise SystemExit("FAIL degraded I3 current did not fail closed")
        if reconciliation.get("semantic_reconciliation_passed") is not False or reconciliation.get("semantic_change_count") != 0 or reconciliation.get("market_watch_candidate") is not False or reconciliation.get("pipeline_watch_candidate") is not False or reconciliation.get("lkg_reference_required") is not True:
            raise SystemExit("FAIL degraded I3 canonical reconciliation semantics drift")
    else:
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "I3_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if reconciliation.get("reconciliation_state") not in allowed or reconciliation.get("semantic_reconciliation_passed") is not True:
            raise SystemExit("FAIL healthy I3 canonical reconciliation state drift")
    return {
        "programme": "I3",
        "source_health": current["source_health_state"],
        "healthy_sources": current["healthy_source_count"],
        "degraded_sources": current["degraded_source_count"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "market_watch_candidate": reconciliation["market_watch_candidate"],
        "pipeline_watch_candidate": reconciliation["pipeline_watch_candidate"],
        "open_call_authorized": False,
        "eligibility_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / "i3-programme-intelligence.json"
    previous_path = root / "previous" / "i3-programme-intelligence.json"
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY":
        shutil.copy2(current_path, history / "i3-programme-intelligence.json")
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists() and load(previous_path).get("source_health_state") == "HEALTHY":
        shutil.copy2(previous_path, history / "i3-programme-intelligence.json")
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
    registry_path = ingest / "eu_direct_i3_programme_intelligence_registry.json"
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/i3-programme")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    run_id = os.environ.get("I3_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-i3"
    current_path = root / "current" / "i3-programme-intelligence.json"
    run([
        sys.executable,
        str(ingest / "eu_direct_i3_programme_intelligence.py"),
        "--registry", str(registry_path),
        "--run-id", run_id,
        "--output", str(current_path),
    ])
    shutil.copy2(registry_path, root / "current" / "registry.json")
    current = load(current_path)
    restore = restore_previous(root, current)

    reconcile_cmd = [
        sys.executable,
        str(ingest / "eu_direct_i3_programme_reconcile.py"),
        str(current_path),
    ]
    previous_path = root / "previous" / "i3-programme-intelligence.json"
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    reconcile_cmd += ["--output", str(root / "current" / "i3-programme-reconciliation.json")]
    run(reconcile_cmd)

    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
