#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.narrative import compile_analysis
from core.pipeline import PipelineRun
from exporters.docx_exporter import export_final_package


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_manifest(run: PipelineRun, extra: Dict[str, Any] | None = None) -> str:
    manifest = run.manifest()
    if extra:
        manifest.update(extra)
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic Needs Factory fixture")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--export-dir",
        type=Path,
        help="Optionally export the validated deterministic final DOCX package.",
    )
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

    validation = run.validate_needs(needs, evidence)
    if validation["failures"]:
        print(render_manifest(run), end="")
        return 2

    ranked = run.rank_needs(needs, evidence)
    if ranked["blocked"]:
        print(render_manifest(run, {"ranked_needs": ranked}), end="")
        return 3

    causal = run.causal_model(fixture.get("causal_graph", {}))
    if not causal["valid"]:
        print(render_manifest(run, {"causal_validation": causal}), end="")
        return 4

    trace = run.traceability(
        fixture.get("chains", []),
        [str(need["id"]) for need in needs],
        fixture.get("indicator_ids", []),
    )
    if not trace["valid"]:
        print(render_manifest(run, {"traceability_validation": trace}), end="")
        return 5

    release = run.release_gate({"failures": [], "evidence_gaps": []})
    if not release["ready_for_narrative"]:
        print(render_manifest(run, {"release_gate": release}), end="")
        return 6

    pack = run.package(ranked, needs_by_id, evidence, causal, trace, release)
    compiled = compile_analysis(pack)
    export_manifest = None
    if args.export_dir:
        export_manifest = export_final_package(compiled, args.export_dir)

    rendered = render_manifest(run, {
        "release_gate": release,
        "narrative_pack_sha256": pack["pack_sha256"],
        "narrative_claim_count": len(pack["claim_ledger"]),
        "compiled_narrative_valid": compiled["validation"]["valid"],
        "compiled_narrative_sha256": compiled["markdown_sha256"],
        "compiled_source_register_sha256": compiled["source_register_sha256"],
        "compiled_need_count": compiled["validation"]["need_count"],
        "compiled_evidence_count": compiled["validation"]["evidence_count"],
        "export_manifest": export_manifest,
    })
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
