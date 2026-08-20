#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pipeline import PipelineRun


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Needs Factory research-gate fixture")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fixture = load_json(args.fixture)
    run = PipelineRun(
        project_input=fixture["project_input"],
        call_snapshot=fixture["call_snapshot"],
        ruleset_version=fixture["ruleset_version"],
        source_snapshot_ids=fixture.get("source_snapshot_ids", []),
        historical_cutoff=fixture.get("historical_cutoff"),
    )

    gaps = run.gap_detection(
        fixture.get("claims_requiring_local_validation", []),
        fixture.get("evidence", {}),
        fixture.get("population_snapshot", {}),
    )
    plan = run.primary_research_plan(gaps, fixture.get("population_snapshot", {}))

    blocking = [item for item in gaps.get("gaps", []) if item.get("blocking")]
    if blocking or plan.get("sampling_strategy") == "population_snapshot_required":
        state = "BLOCKED_RESEARCH"
    else:
        state = "READY_FOR_PRIMARY_RESEARCH"

    result = {
        "schema_version": "nf.research_gate_run.v0.1",
        "state": state,
        "evidence_gaps": gaps,
        "primary_research_plan": plan,
        "run_manifest": run.manifest(),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    expected = fixture.get("expected_state")
    if expected and state != expected:
        return 2
    expected_gaps = fixture.get("expected_blocking_gap_count")
    if expected_gaps is not None and len(blocking) != int(expected_gaps):
        return 3
    expected_questions = fixture.get("expected_primary_research_question_count")
    if expected_questions is not None and len(plan.get("questions", [])) != int(expected_questions):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
