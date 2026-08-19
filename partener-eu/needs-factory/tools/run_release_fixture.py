#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.dape_release import export_dape_checkpoint
from core.narrative import compile_analysis
from core.pipeline import PipelineRun
from exporters.docx_exporter import export_final_package


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full Needs Factory release fixture through DAPE handoff")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--result", type=Path)
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
    needs_by_id = {str(need["id"]): need for need in needs}

    need_validation = run.validate_needs(needs, evidence)
    if need_validation["failures"]:
        return 2
    ranked = run.rank_needs(needs, evidence)
    if ranked["blocked"]:
        return 3
    causal = run.causal_model(fixture.get("causal_graph", {}))
    if not causal["valid"]:
        return 4
    trace = run.traceability(
        fixture.get("chains", []),
        [str(need["id"]) for need in needs],
        fixture.get("indicator_ids", []),
    )
    if not trace["valid"]:
        return 5
    release = run.release_gate({"failures": [], "evidence_gaps": []})
    if not release["ready_for_narrative"]:
        return 6
    pack = run.package(ranked, needs_by_id, evidence, causal, trace, release)
    compiled = compile_analysis(pack)

    final_dir = args.output_root / "final"
    dape_dir = args.output_root / "dape_checkpoint"
    export_manifest = export_final_package(compiled, final_dir, basename="ANALIZA_NEVOI")
    handoff = export_dape_checkpoint(
        run.manifest(),
        pack,
        compiled,
        export_manifest,
        dape_dir,
        checkpoint_id="NF-CP12-RELEASE-HANDOFF",
        project_id="NEEDS-FACTORY",
        canonical_base_checkpoint="NF-CP11",
    )

    result = {
        "schema_version": "nf.release_fixture_result.v0.1",
        "run_id": run.run_id,
        "narrative_pack_sha256": pack["pack_sha256"],
        "compiled_narrative_sha256": compiled["markdown_sha256"],
        "compiled_source_register_sha256": compiled["source_register_sha256"],
        "final_export_manifest": export_manifest,
        "dape_handoff": handoff,
        "release_state": "HANDOFF_READY_NOT_CANONICAL",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
