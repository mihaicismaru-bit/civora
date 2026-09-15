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
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
)
EXACT_SCHEMA = "PARTENER_EU_I3_FT_EXACT_EVIDENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_I3_FT_RECONCILIATION_V1"
PROGRAMME_FAMILY = "I3"
ARTIFACT_PREFIXES = (
    "partener-eu-eu-direct-programme-intelligence-",
    "partener-eu-i3-exact-call-proof-",
    "partener-eu-i3-exact-history-",
)
CALLS = {
    "I3-2026-INV1": {
        "folder": "inv1",
        "eismea_url": "https://eismea.ec.europa.eu/funding-opportunities/calls-proposals/interregional-innovation-investments-strand-1-i3-2026-inv1_en",
    },
    "I3-2026-INV2A": {
        "folder": "inv2a",
        "eismea_url": "https://eismea.ec.europa.eu/funding-opportunities/calls-proposals/interregional-innovation-investments-strand-2a-i3-2026-inv2a_en",
    },
}


def run(cmd: list[str], *, stdout=None) -> None:
    subprocess.run(cmd, check=True, stdout=stdout)


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def when(value: Any) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("I3 canonical history timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def healthy_same_identity(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous.get("schema") != EXACT_SCHEMA:
        return False
    if str(previous.get("reference") or "").upper() != str(current.get("reference") or "").upper():
        return False
    if previous.get("source_family") != "EU_DIRECT" or previous.get("programme_family") != PROGRAMME_FAMILY:
        return False
    if previous.get("source_health_state") != "HEALTHY" or previous.get("lkg_required") is not False:
        return False
    if previous.get("evidence_usable_for_reconciliation") is not True:
        return False
    if previous.get("funding_tenders_authority_verified") is not True:
        return False
    if (previous.get("eismea_receipt") or {}).get("health_state") != "HEALTHY":
        return False
    if previous.get("cross_authority_status_consistent") is not True:
        return False
    if previous.get("funding_tenders_authority_url") != current.get("funding_tenders_authority_url"):
        return False
    if previous.get("eismea_authority_url") != current.get("eismea_authority_url"):
        return False
    try:
        return when(previous.get("fetched_at")) < when(current.get("fetched_at"))
    except Exception:
        return False


def acquire_current(root: pathlib.Path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    run_base = os.environ.get("I3_EXACT_RUN_ID") or f"{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-i3-exact"
    for reference, config in CALLS.items():
        current = root / str(config["folder"]) / "current"
        current.mkdir(parents=True, exist_ok=True)
        run([
            sys.executable,
            str(ingest / "eu_direct_i3_ft_exact.py"),
            "--reference", reference,
            "--eismea-url", str(config["eismea_url"]),
            "--run-id", f"{run_base}-{str(config['folder'])}",
            "--output-dir", str(current),
        ])


def restore_previous(root: pathlib.Path) -> dict[str, Any]:
    repo = os.environ["GITHUB_REPOSITORY"]
    head = os.environ.get("EXPECTED_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    branch = os.environ.get("EXPECTED_HEAD_BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    scratch = pathlib.Path("/tmp/partener-eu-i3-exact-canonical-history-scan")
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

    current = {
        ref: load(root / str(cfg["folder"]) / "current" / "ft-i3-exact-evidence.json")
        for ref, cfg in CALLS.items()
    }
    best: dict[str, tuple[dt.datetime, pathlib.Path, int, str] | None] = {ref: None for ref in CALLS}

    for _, artifact_id, artifact_name in rows:
        archive_path = scratch / f"{artifact_id}.zip"
        try:
            with archive_path.open("wb") as output:
                run(["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], stdout=output)
            unpack = scratch / f"unpack-{artifact_id}"
            unpack.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(unpack)
        except Exception:
            continue
        for path in unpack.rglob("ft-i3-exact-evidence.json"):
            try:
                row = load(path)
                ref = str(row.get("reference") or "").upper()
                if ref not in CALLS or not healthy_same_identity(row, current[ref]):
                    continue
                stamp = when(row.get("fetched_at"))
            except Exception:
                continue
            existing = best[ref]
            if existing is None or stamp > existing[0]:
                best[ref] = (stamp, path, artifact_id, artifact_name)
        if all(best.values()):
            break

    restored: dict[str, Any] = {}
    for ref, cfg in CALLS.items():
        previous_dir = root / str(cfg["folder"]) / "previous"
        previous_dir.mkdir(parents=True, exist_ok=True)
        selected = best[ref]
        if selected is None:
            restored[ref] = {"previous_found": False, "reason": "NO_HEALTHY_SAME_IDENTITY_STRICTLY_OLDER_RECEIPT"}
            continue
        stamp, source, artifact_id, artifact_name = selected
        target = previous_dir / "ft-i3-exact-evidence.json"
        shutil.copy2(source, target)
        restored[ref] = {
            "previous_found": True,
            "fetched_at": stamp.isoformat(),
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "source_path": source.as_posix(),
        }
    dump(root / "restore-metadata.json", restored)
    return restored


def reconcile(root: pathlib.Path, restored: dict[str, Any]) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    ingest = repo_root / "partener-eu" / "ingest"
    for reference, config in CALLS.items():
        folder = root / str(config["folder"])
        current = folder / "current" / "ft-i3-exact-evidence.json"
        output = folder / "current" / "i3-exact-reconciliation.json"
        cmd = [sys.executable, str(ingest / "eu_direct_i3_ft_reconcile.py"), str(current)]
        previous = folder / "previous" / "ft-i3-exact-evidence.json"
        if restored.get(reference, {}).get("previous_found") is True and previous.exists():
            cmd += ["--previous", str(previous)]
        cmd += ["--output", str(output)]
        run(cmd)


def enforce_boundary(root: pathlib.Path) -> dict[str, Any]:
    summaries = []
    for reference, config in CALLS.items():
        folder = root / str(config["folder"])
        current = load(folder / "current" / "ft-i3-exact-evidence.json")
        rec = load(folder / "current" / "i3-exact-reconciliation.json")
        previous_path = folder / "previous" / "ft-i3-exact-evidence.json"
        if current.get("schema") != EXACT_SCHEMA or current.get("reference") != reference:
            raise SystemExit(f"FAIL I3 canonical exact identity drift: {reference}")
        if current.get("source_family") != "EU_DIRECT" or current.get("programme_family") != PROGRAMME_FAMILY:
            raise SystemExit(f"FAIL I3 canonical family drift: {reference}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(current.get("exact_semantic_fingerprint") or "")):
            raise SystemExit(f"FAIL I3 canonical semantic fingerprint missing: {reference}")
        if any(current.get(flag) is not False for flag in FLAGS):
            raise SystemExit(f"FAIL I3 canonical evidence became authorizing: {reference}")
        if current.get("publication_effect") != "NONE" or current.get("canonical_corpus_mutation") is not False:
            raise SystemExit(f"FAIL I3 canonical evidence crossed publication boundary: {reference}")
        if rec.get("schema") != RECONCILIATION_SCHEMA or rec.get("reference") != reference:
            raise SystemExit(f"FAIL I3 canonical reconciliation identity drift: {reference}")
        if rec.get("field_scoped_material_admission_required") is not True or "field_scoped_material_admission" not in set(rec.get("missing_for_material_admission") or []):
            raise SystemExit(f"FAIL I3 canonical final material gate relaxed: {reference}")
        if rec.get("lkg_reference_is_current_truth") is not False:
            raise SystemExit(f"FAIL I3 canonical LKG promoted to current truth: {reference}")
        if any(rec.get(flag) is not False for flag in FLAGS):
            raise SystemExit(f"FAIL I3 canonical reconciliation became authorizing: {reference}")
        if rec.get("publication_effect") != "NONE" or rec.get("canonical_corpus_mutation") is not False:
            raise SystemExit(f"FAIL I3 canonical reconciliation crossed publication boundary: {reference}")

        healthy = current.get("source_health_state") == "HEALTHY" and current.get("evidence_usable_for_reconciliation") is True
        previous_healthy = False
        if previous_path.exists():
            previous = load(previous_path)
            previous_healthy = healthy_same_identity(previous, current)
            if not previous_healthy:
                raise SystemExit(f"FAIL I3 canonical previous receipt selection invalid: {reference}")
            if rec.get("previous_identity_match") is not True or rec.get("previous_evidence_sha256") is None:
                raise SystemExit(f"FAIL I3 canonical reconciliation lost previous binding: {reference}")

        if healthy:
            if current.get("funding_tenders_authority_verified") is not True or (current.get("eismea_receipt") or {}).get("health_state") != "HEALTHY":
                raise SystemExit(f"FAIL I3 canonical current authority proof incomplete: {reference}")
            if current.get("cross_authority_status_consistent") is not True:
                raise SystemExit(f"FAIL I3 canonical cross-authority status conflict: {reference}")
            if rec.get("semantic_reconciliation_passed") is not True or rec.get("lkg_reference_required") is not False:
                raise SystemExit(f"FAIL I3 canonical healthy reconciliation semantics drift: {reference}")
            if previous_path.exists():
                if rec.get("reconciliation_state") not in {"NO_CHANGE", "I3_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"}:
                    raise SystemExit(f"FAIL I3 canonical reconciled state invalid: {reference}")
            elif rec.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
                raise SystemExit(f"FAIL I3 canonical baseline state invalid: {reference}")
        else:
            if current.get("source_health_state") != "DEGRADED_EXACT_AUTHORITY_CHAIN" or current.get("evidence_usable_for_reconciliation") is not False or current.get("lkg_required") is not True:
                raise SystemExit(f"FAIL I3 canonical degraded source-health state invalid: {reference}")
            if current.get("candidate_state") != "UNKNOWN" or current.get("status_label") is not None:
                raise SystemExit(f"FAIL I3 canonical degraded evidence leaked status: {reference}")
            if current.get("deadline_candidate") is not None or current.get("budget_candidate") is not None:
                raise SystemExit(f"FAIL I3 canonical degraded evidence leaked material candidates: {reference}")
            if rec.get("reconciliation_state") != "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED":
                raise SystemExit(f"FAIL I3 canonical degraded current did not fail closed: {reference}")
            if rec.get("semantic_reconciliation_passed") is not False or rec.get("semantic_change_count") != 0:
                raise SystemExit(f"FAIL I3 canonical degraded reconciliation fabricated semantic change: {reference}")
            if rec.get("lkg_reference_required") is not True or rec.get("lkg_reference_available") is not previous_healthy:
                raise SystemExit(f"FAIL I3 canonical degraded LKG availability drift: {reference}")
            if rec.get("material_admission_ready_for_downstream_review") is not False:
                raise SystemExit(f"FAIL I3 canonical degraded current reached material review gate: {reference}")

        summaries.append({
            "reference": reference,
            "source_health_state": current.get("source_health_state"),
            "candidate_state": current.get("candidate_state"),
            "status_label": current.get("status_label"),
            "semantic_fingerprint": current.get("exact_semantic_fingerprint"),
            "reconciliation_state": rec.get("reconciliation_state"),
            "semantic_change_count": rec.get("semantic_change_count"),
            "previous_same_identity_restored": previous_path.exists(),
            "lkg_reference_required": rec.get("lkg_reference_required"),
            "material_admission_ready_for_downstream_review": rec.get("material_admission_ready_for_downstream_review"),
            "open_call_authorized": False,
            "publication_effect": "NONE",
        })
    return {"i3_exact_calls": summaries, "publication_effect": "NONE"}


def stage_history(root: pathlib.Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for reference, config in CALLS.items():
        folder = root / str(config["folder"])
        current_path = folder / "current" / "ft-i3-exact-evidence.json"
        rec_path = folder / "current" / "i3-exact-reconciliation.json"
        previous_path = folder / "previous" / "ft-i3-exact-evidence.json"
        history = folder / "history"
        history.mkdir(parents=True, exist_ok=True)
        current = load(current_path)
        if current.get("source_health_state") == "HEALTHY" and current.get("evidence_usable_for_reconciliation") is True:
            shutil.copy2(current_path, history / "ft-i3-exact-evidence.json")
            selected = "CURRENT_HEALTHY"
        elif previous_path.exists() and healthy_same_identity(load(previous_path), current):
            shutil.copy2(previous_path, history / "ft-i3-exact-evidence.json")
            selected = "PREVIOUS_HEALTHY_LKG"
        else:
            selected = "NO_HEALTHY_LKG_AVAILABLE"
        shutil.copy2(rec_path, history / "i3-exact-reconciliation.json")
        result[reference] = {
            "selected": selected,
            "lkg_is_current_truth": False,
            "current_source_health_state": current.get("source_health_state"),
        }
    dump(root / "history-selection.json", result)
    return result


def main() -> int:
    root = pathlib.Path("/tmp/partener-eu-eu-direct-programme-intelligence/i3-exact")
    shutil.rmtree(root, ignore_errors=True)
    for config in CALLS.values():
        folder = root / str(config["folder"])
        (folder / "current").mkdir(parents=True, exist_ok=True)
        (folder / "previous").mkdir(parents=True, exist_ok=True)
        (folder / "history").mkdir(parents=True, exist_ok=True)

    acquire_current(root)
    restored = restore_previous(root)
    reconcile(root, restored)
    boundary = enforce_boundary(root)
    history = stage_history(root)
    print(json.dumps({"restore": restored, "boundary": boundary, "history": history}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
