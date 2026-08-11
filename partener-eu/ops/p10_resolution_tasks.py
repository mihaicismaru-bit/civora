#!/usr/bin/env python3
import datetime as dt
import json
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
LATEST = VALIDATION / "latest.json"
TASKS = VALIDATION / "resolution-tasks"


def atomic_json(path, obj):
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


def load_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def nowz():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main():
    report = load_json(LATEST, {})
    TASKS.mkdir(parents=True, exist_ok=True)
    created_or_updated = []
    for src in report.get("sources", []):
        if not src.get("resolution_task_required"):
            continue
        source_id = src.get("id")
        if not source_id:
            continue
        path = TASKS / f"{source_id}.json"
        existing = load_json(path, {}) or {}
        candidate = src.get("semantic_sha256")
        baseline = None
        state = load_json(VALIDATION / "source_state.json", {}) or {}
        baseline = ((state.get("sources") or {}).get(source_id) or {}).get("semantic_sha256")
        task = {
            "task_type": "OFFICIAL_SOURCE_HASH_RESOLUTION",
            "source_id": source_id,
            "source_name": src.get("name"),
            "source_url": src.get("url"),
            "tier": src.get("tier"),
            "criticality": src.get("criticality"),
            "status": "OPEN_MANUAL_EVIDENCE_RESOLUTION",
            "baseline_semantic_sha256": existing.get("baseline_semantic_sha256") or baseline,
            "candidate_semantic_sha256": candidate,
            "confirmation_observations": src.get("confirmation_observations", 0),
            "first_observed_at": existing.get("first_observed_at") or src.get("observed_at") or report.get("run_started"),
            "last_observed_at": src.get("observed_at") or report.get("run_started") or nowz(),
            "policy": "Do not automatically change deadline, eligibility, budget, scoring, or any other material fact. Resolve only from authoritative evidence and record provenance before publication.",
            "automatic_material_fact_update_allowed": False,
            "checkpoint": report.get("checkpoint"),
        }
        atomic_json(path, task)
        created_or_updated.append(source_id)
    print(json.dumps({"resolution_tasks": created_or_updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
