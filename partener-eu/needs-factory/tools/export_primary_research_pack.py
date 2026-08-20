#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exporters.research_pack import export_primary_research_pack


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a Needs Factory primary-research collection pack")
    parser.add_argument("research_gate_result", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    gate = json.loads(args.research_gate_result.read_text(encoding="utf-8"))
    plan = gate.get("primary_research_plan") or gate.get("research_plan")
    if not plan:
        raise SystemExit("research gate result has no primary_research_plan")
    project_id = args.project_id or (gate.get("run_manifest") or {}).get("project_id") or "UNKNOWN"
    result = export_primary_research_pack(plan, args.output_dir, project_id=str(project_id))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
