#!/usr/bin/env python3
"""Select at most one stale PARTENER.EU source producer for recovery dispatch.

This is orchestration only. It never changes source facts or timestamps. Existing
source workflows remain the only owners of acquisition and persistence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "ingest" / "data_plane_contract.json"
DEFAULT_STATE_DIR = ROOT / "ingest" / "state"

PRODUCERS = {
    "AFIR_CORPUS": "partener-eu-afir-ingest.yml",
    "MIPE_CORPUS": "partener-eu-mipe-ingest.yml",
    "PEO_CALENDAR": "partener-eu-peo-calendar.yml",
    "VERIFIED_SOURCE_REGISTRY": "partener-eu-source-registry.yml",
}

OBSERVED_PATHS = {
    "AFIR_CORPUS": ("generatedAt",),
    "MIPE_CORPUS": ("lastRun", "observedAt"),
    "PEO_CALENDAR": ("lastRun", "observedAt"),
    "VERIFIED_SOURCE_REGISTRY": ("observed_at",),
}


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def nested_get(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def evaluate(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    state_dir: Path = DEFAULT_STATE_DIR,
    reference: dt.datetime | None = None,
) -> dict[str, Any]:
    reference = (reference or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    contract = load_json(contract_path)
    corpora = contract.get("corpora") or {}
    rows: list[dict[str, Any]] = []

    for source_id, workflow in PRODUCERS.items():
        config = corpora.get(source_id) or {}
        state_file = str(config.get("stateFile") or "")
        max_age_hours = float(config.get("freshnessSlaHours") or 0)
        state = load_json(state_dir / state_file) if state_file else {}
        observed_raw = nested_get(state, OBSERVED_PATHS[source_id])
        observed = parse_time(observed_raw)

        age_hours: float | None = None
        if observed is not None:
            age_hours = max(0.0, (reference - observed).total_seconds() / 3600.0)

        due = (
            not state_file
            or max_age_hours <= 0
            or observed is None
            or (age_hours is not None and age_hours > max_age_hours)
        )
        ratio = None if age_hours is None or max_age_hours <= 0 else age_hours / max_age_hours
        rows.append(
            {
                "sourceId": source_id,
                "workflow": workflow,
                "stateFile": state_file,
                "observedAt": observed_raw,
                "ageHours": None if age_hours is None else round(age_hours, 3),
                "maxAgeHours": max_age_hours,
                "ageToSlaRatio": None if ratio is None else round(ratio, 3),
                "due": due,
            }
        )

    due_rows = [row for row in rows if row["due"]]
    due_rows.sort(
        key=lambda row: (
            row["ageToSlaRatio"] is None,
            row["ageToSlaRatio"] if row["ageToSlaRatio"] is not None else float("inf"),
            row["sourceId"],
        ),
        reverse=True,
    )
    selected = due_rows[0] if due_rows else None
    return {
        "status": "REFRESH_DUE" if selected else "CURRENT",
        "referenceTime": reference.isoformat().replace("+00:00", "Z"),
        "selected": selected,
        "sources": rows,
        "policy": {
            "dispatchAtMostOneProducer": True,
            "factsMutatedByWatchdog": False,
            "timestampsMutatedByWatchdog": False,
            "producerWorkflowsRemainCanonical": True,
        },
    }


def write_github_output(path: Path, result: dict[str, Any]) -> None:
    selected = result.get("selected") or {}
    values = {
        "due": "true" if selected else "false",
        "source_id": str(selected.get("sourceId") or ""),
        "workflow": str(selected.get("workflow") or ""),
        "age_hours": str(selected.get("ageHours") if selected else ""),
        "max_age_hours": str(selected.get("maxAgeHours") if selected else ""),
    }
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--as-of", help="ISO-8601 reference time for deterministic checks")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    reference = parse_time(args.as_of) if args.as_of else None
    if args.as_of and reference is None:
        parser.error("--as-of must be an ISO-8601 timestamp")

    result = evaluate(contract_path=args.contract, state_dir=args.state_dir, reference=reference)
    if args.github_output:
        write_github_output(args.github_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
