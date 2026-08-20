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
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic Needs Factory fixture")
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

    evidence = fixture.get("evidence", {})
    needs = fixture.get("needs", [])
    validation = run.validate_needs(needs, evidence)
    if validation["failures"]:
        print(json.dumps(run.manifest(), ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    trace = run.traceability(
        fixture.get("chains", []),
        [str(need["id"]) for need in needs],
        fixture.get("indicator_ids", []),
    )
    if not trace["valid"]:
        print(json.dumps(run.manifest(), ensure_ascii=False, indent=2, sort_keys=True))
        return 3

    release = run.release_gate({"failures": [], "evidence_gaps": []})
    manifest = run.manifest()
    manifest["release_gate"] = release

    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if release["ready_for_narrative"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
