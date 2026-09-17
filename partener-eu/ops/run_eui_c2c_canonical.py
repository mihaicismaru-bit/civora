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
EVIDENCE_SCHEMA = "PARTENER_EU_EUI_C2C_EXACT_EVIDENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_EUI_C2C_RECONCILIATION_V1"
IDENTITY_SLUG = "eui-city-to-city-exchanges"
GENERIC_ARTIFACT_PREFIX = "partener-eu-eu-direct-programme-intelligence-"


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
        and candidate.get("opportunity_family") == "CITY_TO_CITY_EXCHANGES"
        and candidate.get("identity_slug") == IDENTITY_SLUG
        and candidate.get("authority_class") == "EUI_EXACT_C2C_PAGE_AND_CURRENT_GUIDANCE"
    )


def restore_previous(root: pathlib.Path) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-eui-c2c-history-scan")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    artifacts_json = scratch / "artifacts.json"
    with artifacts_json.open("wb") as output:
        run(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"], stdout=output)
    rows: list[tuple[str, int, str]] = []
    for artifact in (load(artifacts_json).get("artifacts") or []):
        name = str(artifact.get("name") or "")
        if artifact.get("expired") is True or not name.startswith(GENERIC_ARTIFACT_PREFIX):
            continue
        workflow_run = artifact.get("workflow_run") or {}
        if head and str(workflow_run.get("head_sha") or "") == head:
            continue
        if branch and str(workflow_run.get("head_branch") or "") != branch:
            continue
        rows.append((str(artifact.get("created_at") or ""), int(artifact.get("id") or 0), name))
    rows.sort(reverse=True)

    previous_dir = root / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "previous_found": False, "artifact_id": None, "artifact_name": None,
        "restore_source_kind": None,
        "restore_reason": "NO_PREVIOUS_COMPATIBLE_CANONICAL_ARTIFACT",
        "identity_slug": IDENTITY_SLUG,
    }
    for _, artifact_id, artifact_name in rows[:30]:
        archive_path = scratch / f"{artifact_id}.zip"
        with archive_path.open("wb") as output:
            run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
        unpack = scratch / f"unpack-{artifact_id}"
        unpack.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        candidates = sorted(unpack.rglob("eui-c2c-exact-evidence.json"), key=candidate_priority)
        for candidate_path in candidates:
            try:
                candidate = load(candidate_path)
            except Exception:
                continue
            if not compatible(candidate):
                continue
            dump(previous_dir / "eui-c2c-exact-evidence.json", candidate)
            metadata.update({
                "previous_found": True,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "restore_source_kind": "GENERIC_EU_DIRECT",
                "restore_reason": "SAME_EXACT_C2C_IDENTITY",
                "restored_candidate_path": candidate_path.relative_to(unpack).as_posix(),
                "restored_fetched_at": candidate.get("fetched_at"),
                "restored_source_health_state": candidate.get("source_health_state"),
            })
            dump(previous_dir / "restore-metadata.json", metadata)
            return metadata
    dump(previous_dir / "restore-metadata.json", metadata)
    return metadata


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    evidence = load(root / "current" / "eui-c2c-exact-evidence.json")
    reconciliation = load(root / "current" / "eui-c2c-reconciliation.json")
    if not compatible(evidence):
        raise SystemExit("FAIL canonical EUI C2C identity drift")
    if evidence.get("parser_version") != "EU_DIRECT_EUI_C2C_EXACT_V1":
        raise SystemExit("FAIL canonical EUI C2C parser drift")
    if reconciliation.get("schema") != RECONCILIATION_SCHEMA or reconciliation.get("parser_version") != "EU_DIRECT_EUI_C2C_RECONCILE_V1":
        raise SystemExit("FAIL canonical EUI C2C reconciliation drift")
    if reconciliation.get("identity_key") != evidence.get("identity_key"):
        raise SystemExit("FAIL canonical EUI C2C reconciliation lost identity")
    if evidence.get("official_call_identifier") is not None or evidence.get("deadline_candidate") is not None:
        raise SystemExit("FAIL canonical EUI C2C fabricated formal ID/deadline")
    if any(evidence.get(flag) is not False for flag in FLAGS) or any(reconciliation.get(flag) is not False for flag in FLAGS):
        raise SystemExit("FAIL canonical EUI C2C became materially authorizing")
    if reconciliation.get("material_admission_ready_for_downstream_review") is not False:
        raise SystemExit("FAIL canonical EUI C2C without formal ID reached material review")
    if reconciliation.get("lkg_reference_is_current_truth") is not False:
        raise SystemExit("FAIL canonical EUI C2C promoted LKG to current truth")
    if evidence.get("publication_effect") != "NONE" or reconciliation.get("publication_effect") != "NONE":
        raise SystemExit("FAIL canonical EUI C2C publication boundary drift")
    if evidence.get("canonical_corpus_mutation") is not False or reconciliation.get("canonical_corpus_mutation") is not False:
        raise SystemExit("FAIL canonical EUI C2C corpus mutation drift")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("identity_key") or "")):
        raise SystemExit("FAIL canonical EUI C2C identity hash missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("exact_semantic_fingerprint") or "")):
        raise SystemExit("FAIL canonical EUI C2C semantic hash missing")

    healthy = evidence.get("source_health_state") == "HEALTHY" and evidence.get("lkg_required") is False
    if healthy:
        if evidence.get("candidate_state") != "CONTINUOUS_OPPORTUNITY":
            raise SystemExit("FAIL healthy canonical EUI C2C candidate-state drift")
        if evidence.get("deadline_semantics") != "NO_CURRENTLY_FIXED_END_DATE":
            raise SystemExit("FAIL healthy canonical EUI C2C fixed-deadline precedence drift")
        for name in ("exact_c2c_page", "current_guidance"):
            row = (evidence.get("source_receipts") or {}).get(name) or {}
            if row.get("health_state") != "HEALTHY" or row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise SystemExit(f"FAIL healthy canonical EUI C2C receipt drift: {name}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("raw_sha256") or "")):
                raise SystemExit(f"FAIL healthy canonical EUI C2C raw hash missing: {name}")
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING", "NO_CHANGE",
            "EUI_C2C_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if reconciliation.get("reconciliation_state") not in allowed or reconciliation.get("semantic_reconciliation_passed") is not True:
            raise SystemExit("FAIL healthy canonical EUI C2C reconciliation-state drift")
        if reconciliation.get("lkg_reference_required") is not False:
            raise SystemExit("FAIL healthy canonical EUI C2C incorrectly requires LKG")
    else:
        if evidence.get("source_health_state") != "DEGRADED" or evidence.get("lkg_required") is not True:
            raise SystemExit("FAIL degraded canonical EUI C2C health drift")
        if evidence.get("candidate_state") != "UNKNOWN":
            raise SystemExit("FAIL degraded canonical EUI C2C retained current semantics")
        if reconciliation.get("reconciliation_state") != "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED":
            raise SystemExit("FAIL degraded canonical EUI C2C did not fail closed")
        if reconciliation.get("lkg_reference_required") is not True:
            raise SystemExit("FAIL degraded canonical EUI C2C did not require LKG/reference")

    return {
        "programme": "European Urban Initiative",
        "opportunity": "City-to-City Exchanges",
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "deadline_candidate": None,
        "portico_deadline_observed": (evidence.get("portico_metadata_observation") or {}).get("deadline_observed"),
        "authority_discrepancy": evidence.get("authority_discrepancy"),
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "lkg_reference_required": reconciliation["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": False,
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    current_path = root / "current" / "eui-c2c-exact-evidence.json"
    previous_path = root / "previous" / "eui-c2c-exact-evidence.json"
    current = load(current_path)
    history = root / "history"
    history.mkdir(parents=True, exist_ok=True)
    if current.get("source_health_state") == "HEALTHY" and current.get("lkg_required") is False:
        shutil.copy2(current_path, history / "eui-c2c-exact-evidence.json")
        selected = "CURRENT_HEALTHY"
    elif previous_path.exists():
        previous = load(previous_path)
        if previous.get("source_health_state") == "HEALTHY" and previous.get("lkg_required") is False:
            shutil.copy2(previous_path, history / "eui-c2c-exact-evidence.json")
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
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/eui-c2c")
    shutil.rmtree(root, ignore_errors=True)
    (root / "current").mkdir(parents=True)
    (root / "previous").mkdir(parents=True)
    (root / "history").mkdir(parents=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ingest}:{repo_root / 'partener-eu' / 'ops'}"
    run([sys.executable, str(repo_root / "partener-eu" / "ops" / "test_eu_direct_eui_c2c_exact.py")], env=env)

    restore = restore_previous(root)
    run_id = os.environ.get("EUI_C2C_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-eui-c2c"
    run([
        sys.executable, str(ingest / "eu_direct_eui_c2c_exact.py"),
        "--run-id", run_id, "--output-dir", str(root / "current"),
    ], env=env)

    reconcile_cmd = [
        sys.executable, str(ingest / "eu_direct_eui_c2c_reconcile.py"),
        str(root / "current" / "eui-c2c-exact-evidence.json"),
    ]
    previous_path = root / "previous" / "eui-c2c-exact-evidence.json"
    if restore.get("previous_found") is True and previous_path.exists():
        reconcile_cmd += ["--previous", str(previous_path)]
    reconcile_cmd += ["--output", str(root / "current" / "eui-c2c-reconciliation.json")]
    run(reconcile_cmd, env=env)

    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restore, "boundary": boundary, "history": history}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
