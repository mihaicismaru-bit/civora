#!/usr/bin/env python3
"""Maintain fail-closed resolution tasks for every confirmed source hash change."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
LATEST = VALIDATION / "latest.json"
TASKS = VALIDATION / "resolution-tasks"
INGEST_STATE = ROOT / "ingest" / "state"


def atomic_json(path: pathlib.Path, obj: Any) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def nowz() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def candidate_fingerprint(rows: list[dict[str, Any]]) -> str:
    normalized = sorted((str(x.get("url") or ""), str(x.get("sha256") or x.get("semantic_sha256") or "")) for x in rows)
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_task(source_id: str, task: dict[str, Any]) -> pathlib.Path:
    path = TASKS / f"{source_id}.json"
    existing = load_json(path, {}) or {}
    task.setdefault("schema_version", "1.2")
    task.setdefault("task_type", "OFFICIAL_SOURCE_HASH_RESOLUTION")
    task.setdefault("source_id", source_id)
    task.setdefault("status", existing.get("status") or "OPEN_MANUAL_EVIDENCE_RESOLUTION")
    task.setdefault("first_observed_at", existing.get("first_observed_at") or task.get("last_observed_at") or nowz())
    task.setdefault("last_observed_at", nowz())
    task.setdefault(
        "policy",
        "Do not automatically change deadline, eligibility, budget, scoring, beneficiaries, call status, or any other material fact. Resolve only from authoritative evidence and record provenance before publication.",
    )
    task["automatic_material_fact_update_allowed"] = False
    task["material_fact_autoupdate_allowed"] = False
    task.setdefault(
        "blocked_fact_classes",
        ["deadline", "eligibility", "budget", "scoring", "beneficiaries", "material_call_status", "other_material_facts"],
    )
    atomic_json(path, task)
    return path


def task_is_fail_closed(source_id: str) -> bool:
    task = load_json(TASKS / f"{source_id}.json", {}) or {}
    allowed = task.get("automatic_material_fact_update_allowed")
    if allowed is None:
        allowed = task.get("material_fact_autoupdate_allowed")
    return bool(task) and allowed is False


def maintain_validation_tasks(report: dict[str, Any]) -> list[str]:
    updated: list[str] = []
    source_state = load_json(VALIDATION / "source_state.json", {}) or {}
    for src in report.get("sources", []):
        if not src.get("resolution_task_required"):
            continue
        source_id = src.get("id")
        if not source_id:
            continue
        existing = load_json(TASKS / f"{source_id}.json", {}) or {}
        baseline = ((source_state.get("sources") or {}).get(source_id) or {}).get("semantic_sha256")
        write_task(source_id, {
            "source_name": src.get("name"),
            "source_url": src.get("url"),
            "source_tier": src.get("tier"),
            "criticality": src.get("criticality"),
            "baseline_semantic_sha256": existing.get("baseline_semantic_sha256") or baseline,
            "candidate_semantic_sha256": src.get("semantic_sha256"),
            "confirmation_observations": src.get("confirmation_observations", 0),
            "first_observed_at": existing.get("first_observed_at") or src.get("observed_at") or report.get("run_started"),
            "last_observed_at": src.get("observed_at") or report.get("run_started") or nowz(),
            "checkpoint": report.get("checkpoint"),
        })
        updated.append(source_id)
    return updated


def maintain_registry_tasks() -> tuple[list[str], list[str]]:
    health = load_json(INGEST_STATE / "source_registry_health.json", {}) or {}
    updated: list[str] = []
    unsafe: list[str] = []
    for src in health.get("sources", []):
        if not (src.get("semantic_hash_changed") and src.get("material_fact_use")):
            continue
        source_id = src.get("id")
        if not source_id:
            continue
        existing = load_json(TASKS / f"{source_id}.json", {}) or {}
        write_task(source_id, {
            "source_name": src.get("class"),
            "source_url": src.get("url"),
            "source_tier": src.get("tier"),
            "previous_semantic_sha256": existing.get("previous_semantic_sha256") or existing.get("baseline_semantic_sha256") or src.get("previous_semantic_sha256"),
            "candidate_semantic_sha256": src.get("semantic_sha256"),
            "current_semantic_sha256": src.get("semantic_sha256"),
            "first_observed_at": existing.get("first_observed_at") or health.get("observed_at"),
            "last_observed_at": health.get("observed_at") or nowz(),
            "registry_class": src.get("class"),
        })
        updated.append(source_id)
        if src.get("publish_material_fact_update") is not False:
            unsafe.append(source_id)
    return updated, unsafe


def maintain_afir_task() -> list[str]:
    corpus = load_json(INGEST_STATE / "afir_corpus.json", {}) or {}
    changed = [x for x in (corpus.get("items") or []) if x.get("changedFromPrevious")]
    access_dependencies = corpus.get("accessDependencies") or []
    source_id = "SRC-AFIR-CORPUS"
    existing = load_json(TASKS / f"{source_id}.json", {}) or {}
    if not changed and not access_dependencies and not existing:
        return []
    write_task(source_id, {
        "source_name": "AFIR — corpus oficial de pagini și documente",
        "source_url": "https://www.afir.ro/",
        "source_tier": "T1",
        "criticality": "HIGH",
        "candidate_fingerprint": candidate_fingerprint(changed) if changed else existing.get("candidate_fingerprint"),
        "previous_candidate_fingerprint": existing.get("candidate_fingerprint"),
        "candidate_count": len(changed),
        "material_signal_count": sum(bool(x.get("materialChangeCandidate")) for x in changed),
        "candidates": [
            {
                "url": x.get("url"),
                "title": x.get("title"),
                "sha256": x.get("sha256"),
                "material_change_candidate": bool(x.get("materialChangeCandidate")),
                "material_fact_action": "RESOLUTION_TASK_ONLY",
            }
            for x in changed[:100]
        ],
        "auth_dependency_count": len(access_dependencies),
        "auth_dependencies": access_dependencies[:100],
        "technical_classification": "AUTH_REDIRECTS_EXCLUDED_FROM_CHANGE_CANDIDATES" if access_dependencies else None,
        "first_observed_at": existing.get("first_observed_at") or corpus.get("generatedAt"),
        "last_observed_at": corpus.get("generatedAt") or nowz(),
        "corpus_policy": corpus.get("policy") or {},
    })
    return [source_id]


def maintain_peo_calendar_task() -> list[str]:
    state = load_json(INGEST_STATE / "peo_calendar_state.json", {}) or {}
    last = state.get("lastRun") or {}
    changes = state.get("changes") or []
    change_count = int(last.get("changes") or len(changes) or 0)
    if change_count <= 0:
        return []
    source_id = "SRC-PEO-CALENDAR"
    existing = load_json(TASKS / f"{source_id}.json", {}) or {}
    write_task(source_id, {
        "source_name": "PEO — calendar estimativ consolidat (copie instituțională oficială OIR PECU Vest)",
        "source_url": state.get("retrievalSource"),
        "canonical_container": state.get("canonicalContainer"),
        "supporting_official_reference": state.get("supportingOfficialReference"),
        "source_tier": "T1B",
        "criticality": "HIGH",
        "candidate_sha256": last.get("sha256"),
        "previous_candidate_sha256": existing.get("candidate_sha256"),
        "candidate_change_count": change_count,
        "candidate_changes": changes[:200],
        "direct_mipe_verified": bool(state.get("directMipeVerified")),
        "publication_action": "STATE_AND_RESOLUTION_TASK_ONLY",
        "first_observed_at": existing.get("first_observed_at") or last.get("observedAt"),
        "last_observed_at": last.get("observedAt") or nowz(),
    })
    return [source_id]


def main() -> int:
    report = load_json(LATEST, {}) or {}
    TASKS.mkdir(parents=True, exist_ok=True)
    updated: list[str] = []
    updated.extend(maintain_validation_tasks(report))
    registry_updated, unsafe_registry = maintain_registry_tasks()
    updated.extend(registry_updated)
    updated.extend(maintain_afir_task())
    updated.extend(maintain_peo_calendar_task())

    required = set(updated)
    missing = sorted(source_id for source_id in required if not task_is_fail_closed(source_id))
    errors: list[str] = []
    if missing:
        errors.append("missing or unsafe resolution tasks: " + ", ".join(missing))
    if unsafe_registry:
        errors.append("registry attempted material fact publication: " + ", ".join(sorted(unsafe_registry)))

    result = {
        "resolution_tasks": sorted(set(updated)),
        "task_count": len(set(updated)),
        "errors": errors,
        "policy": "hash-change-resolution-task-only-no-material-autoupdate",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
