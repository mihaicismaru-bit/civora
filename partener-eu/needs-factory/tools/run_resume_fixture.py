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
from core.research_evidence import attach_matching_research_evidence
from core.resume import validate_resume_plan


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic Needs Factory blocked->resume acceptance fixture")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = load_json(args.fixture)

    predecessor = PipelineRun(
        project_input=fixture["project_input"],
        call_snapshot=fixture["call_snapshot"],
        ruleset_version=fixture["ruleset_version"],
        source_snapshot_ids=fixture["predecessor_source_snapshot_ids"],
        historical_cutoff=fixture.get("historical_cutoff"),
    )
    predecessor_gaps = predecessor.gap_detection(
        fixture["claims"],
        fixture["external_evidence"],
        fixture["unresolved_population_snapshot"],
    )
    predecessor_plan = predecessor.primary_research_plan(
        predecessor_gaps,
        fixture["unresolved_population_snapshot"],
    )
    if predecessor_plan.get("sampling_strategy") != "population_snapshot_required":
        return 2
    predecessor_manifest = predecessor.manifest()

    successor = PipelineRun(
        project_input=fixture["project_input"],
        call_snapshot=fixture["call_snapshot"],
        ruleset_version=fixture["ruleset_version"],
        source_snapshot_ids=fixture["successor_source_snapshot_ids"],
        historical_cutoff=fixture.get("historical_cutoff"),
    )
    resume_plan = successor.apply_resume(
        predecessor_manifest,
        changed_inputs=["population_snapshot", "primary_research_raw"],
    )
    if not validate_resume_plan(resume_plan)["valid"]:
        return 3
    if resume_plan["restart_stage"] != "NF06_PRIMARY_RESEARCH":
        return 4
    if "NF05_GAP_DETECTION" not in resume_plan["reusable_closed_checkpoints"]:
        return 5

    resolved = successor.resolve_primary_research(
        predecessor_gaps,
        fixture["resolved_population_snapshot"],
        fixture["raw_responses"],
        territory=fixture["project_input"]["territory"],
        school_identity=fixture["resolved_population_snapshot"]["school_identity"],
        period=fixture["resolved_population_snapshot"]["school_year"],
        source_document_id="SYNTHETIC-SURVEY-RAW",
    )
    if not resolved["valid"]:
        return 6

    promoted = resolved["primary_research_evidence"]
    claim_resolution = attach_matching_research_evidence(
        fixture["claims"],
        fixture["external_evidence"],
        promoted["evidence"],
    )
    if claim_resolution["unresolved_gaps"]:
        return 7
    combined_evidence = claim_resolution["evidence"]

    need_validation = successor.validate_needs(fixture["needs"], combined_evidence)
    if need_validation["failures"]:
        return 8
    ranked = successor.rank_needs(fixture["needs"], combined_evidence)
    if ranked["blocked"]:
        return 9
    causal = successor.causal_model(fixture["causal_graph"])
    if not causal["valid"]:
        return 10
    trace = successor.traceability(
        fixture["chains"],
        [str(need["id"]) for need in fixture["needs"]],
        fixture["indicator_ids"],
    )
    if not trace["valid"]:
        return 11
    release = successor.release_gate({"failures": [], "evidence_gaps": claim_resolution["unresolved_gaps"]})
    if not release["ready_for_narrative"]:
        return 12
    needs_by_id = {str(need["id"]): need for need in fixture["needs"]}
    pack = successor.package(ranked, needs_by_id, combined_evidence, causal, trace, release)

    result = {
        "schema_version": "nf.resume_acceptance.v0.1",
        "fixture_type": fixture["fixture_type"],
        "predecessor_run_id": predecessor.run_id,
        "predecessor_state": "BLOCKED_RESEARCH",
        "successor_run_id": successor.run_id,
        "successor_state": "READY_FOR_NARRATIVE",
        "resume_plan": resume_plan,
        "population_snapshot_sha256": resolved["population_validation"]["snapshot_sha256"],
        "raw_response_sha256": promoted["raw_response_sha256"],
        "aggregate_sha256": promoted["aggregate_sha256"],
        "primary_evidence_count": len(promoted["evidence"]),
        "unresolved_local_gaps": claim_resolution["unresolved_gaps"],
        "narrative_pack_sha256": pack["pack_sha256"],
        "successor_manifest": successor.manifest(),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
