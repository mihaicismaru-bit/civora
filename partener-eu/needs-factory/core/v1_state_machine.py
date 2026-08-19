from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from adapters.dape_release import export_dape_checkpoint
from adapters.partener_call import normalize_call_intelligence
from adapters.semantic_provider import NeedDecisionProvider
from adapters.civora_provider import DiscoveryProvider
from core.engine import sha256_json
from core.need_synthesis import build_need_hypotheses
from core.narrative import compile_analysis
from core.pipeline import PipelineRun
from core.product_mode import build_product_narrative_pack, validate_mode_inputs
from core.research_evidence import attach_matching_research_evidence
from core.research_orchestrator import run_research_cycle
from core.research_requirements import build_research_request
from core.semantic_orchestrator import run_need_synthesis
from exporters.docx_exporter import export_final_package
from exporters.research_pack import export_primary_research_pack


LOCAL_NEED_GAP_TYPES = {
    "career_guidance_need": "career_guidance",
    "practice_quality": "practice_quality",
    "skills_baseline": "skills_baseline",
    "career_intention": "career_intention",
}


class NeedsFactoryV1Error(ValueError):
    """Raised for invalid lifecycle transitions or unsafe v1 inputs."""


def _artifact(run: PipelineRun, checkpoint: str, path: str, value: Any, status: str = "PASS") -> None:
    run.start(checkpoint)
    run.add_artifact(checkpoint, path, value)
    run.close(checkpoint, status)


def _source_snapshot_ids(call_intelligence: Mapping[str, Any], research_cycle: Mapping[str, Any]) -> list[str]:
    result = {str(item) for item in (call_intelligence.get("source_snapshot_ids") or [])}
    for record in (research_cycle.get("evidence") or {}).values():
        semantic = record.get("semantic_sha256")
        source = record.get("source_document_id") or record.get("source") or record.get("id")
        if semantic:
            result.add(f"{source}@{str(semantic)[:16]}")
    return sorted(result)


def _local_claims_from_request(request: Mapping[str, Any]) -> list[Dict[str, Any]]:
    claims = []
    for task in request.get("tasks", []) or []:
        construct = str(task.get("construct") or "")
        gap_type = LOCAL_NEED_GAP_TYPES.get(construct)
        if not gap_type:
            continue
        if task.get("task_type") not in {"PRIMARY_RESEARCH", "DISCOVERY_THEN_PRIMARY_IF_GAP"}:
            continue
        claims.append({
            "id": f"LOCAL-{task['requirement_id']}",
            "scope": "school",
            "construct": construct,
            "requires_direct_local": True,
            "priority": task.get("priority") == "primary",
            "gap_type": gap_type,
            "evidence_ids": [
                str(evidence_id)
                for evidence_id, record in (request.get("_external_evidence") or {}).items()
                if construct in {str(item) for item in (record.get("constructs") or [])}
            ],
        })
    return claims


def plan_needs_analysis(
    project_input: Mapping[str, Any],
    call_record: Mapping[str, Any],
    research_profile: Mapping[str, Any],
    discovery_provider: DiscoveryProvider,
    *,
    historical_cutoff: str | None = None,
    population_snapshot: Mapping[str, Any] | None = None,
    research_pack_dir: Path | None = None,
) -> Dict[str, Any]:
    """Plan and execute external research, stopping safely at discovery/research gates."""
    call_intelligence = normalize_call_intelligence(call_record)
    request = build_research_request(
        project_input,
        call_intelligence,
        research_profile,
        historical_cutoff=historical_cutoff,
    )
    research_cycle = run_research_cycle(request, discovery_provider)
    source_ids = _source_snapshot_ids(call_intelligence, research_cycle)
    run = PipelineRun(
        project_input=project_input,
        call_snapshot=call_intelligence,
        ruleset_version="1.0",
        source_snapshot_ids=source_ids,
        historical_cutoff=historical_cutoff,
    )

    _artifact(run, "NF00_INTAKE", "PROJECT_INPUT.json", dict(project_input))
    _artifact(run, "NF01_CALL_INTELLIGENCE", "CALL_INTELLIGENCE.json", call_intelligence)
    _artifact(run, "NF02_RESEARCH_PLAN", "RESEARCH_REQUEST.json", request)
    _artifact(
        run,
        "NF03_EXTERNAL_EVIDENCE",
        "RESEARCH_CYCLE.json",
        research_cycle,
        "PASS" if research_cycle["state"] != "BLOCKED_DISCOVERY" else "BLOCKED_DISCOVERY",
    )

    external_evidence = dict(research_cycle.get("evidence") or {})
    evidence_validation = {
        "schema_version": "nf.external_evidence_validation.v0.1",
        "evidence_record_count": len(external_evidence),
        "accepted_candidate_count": len(research_cycle.get("accepted_candidates") or []),
        "rejected_candidate_count": len(research_cycle.get("rejected_candidates") or []),
        "provider_error_count": len(research_cycle.get("provider_errors") or []),
        "state": research_cycle["state"],
    }
    _artifact(
        run,
        "NF04_EVIDENCE_VALIDATION",
        "EXTERNAL_EVIDENCE_VALIDATION.json",
        evidence_validation,
        "PASS" if research_cycle["state"] != "BLOCKED_DISCOVERY" else "BLOCKED",
    )

    if research_cycle["state"] == "BLOCKED_DISCOVERY":
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "PLAN",
            "state": "BLOCKED_DISCOVERY",
            "project_input": dict(project_input),
            "call_intelligence": call_intelligence,
            "research_request": request,
            "research_cycle": research_cycle,
            "external_evidence": external_evidence,
            "run_manifest": run.manifest(),
            "next_action": "resolve external discovery gaps and rerun plan",
        }

    request_for_claims = dict(request)
    request_for_claims["_external_evidence"] = external_evidence
    local_claims = _local_claims_from_request(request_for_claims)
    snapshot = dict(population_snapshot or {"snapshot_id": "POPULATION-SNAPSHOT-UNRESOLVED"})
    evidence_gaps = run.gap_detection(local_claims, external_evidence, snapshot)
    primary_plan = run.primary_research_plan(evidence_gaps, snapshot)

    blocking_claim_gaps = [
        gap for gap in evidence_gaps.get("gaps", [])
        if gap.get("blocking") and gap.get("gap_type") != "population_snapshot"
    ]
    population_blocked = primary_plan.get("sampling_strategy") == "population_snapshot_required"
    if blocking_claim_gaps or population_blocked or research_cycle.get("primary_research_queue"):
        state = "READY_FOR_PRIMARY_RESEARCH" if not population_blocked else "BLOCKED_RESEARCH"
    else:
        state = "READY_FOR_NEED_SYNTHESIS"

    research_pack_manifest = None
    if state in {"READY_FOR_PRIMARY_RESEARCH", "BLOCKED_RESEARCH"} and research_pack_dir is not None:
        research_pack_manifest = export_primary_research_pack(
            primary_plan,
            research_pack_dir,
            project_id=str(project_input.get("project_id") or project_input.get("project_code") or "UNKNOWN"),
        )

    return {
        "schema_version": "nf.v1_state.v0.1",
        "product_mode": "NEEDS_ANALYSIS",
        "phase": "PLAN",
        "state": state,
        "project_input": dict(project_input),
        "call_intelligence": call_intelligence,
        "research_request": request,
        "research_cycle": research_cycle,
        "external_evidence": external_evidence,
        "local_claims": local_claims,
        "evidence_gaps": evidence_gaps,
        "primary_research_plan": primary_plan,
        "research_pack_manifest": research_pack_manifest,
        "run_manifest": run.manifest(),
        "next_action": (
            "provide authoritative population snapshot and raw primary responses"
            if state in {"READY_FOR_PRIMARY_RESEARCH", "BLOCKED_RESEARCH"}
            else "run semantic need synthesis"
        ),
    }


def _successor_source_ids(
    plan_state: Mapping[str, Any],
    population_snapshot: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    result = {str(item) for item in ((plan_state.get("run_manifest") or {}).get("source_snapshot_ids") or [])}
    population_receipt = population_snapshot.get("source_hash_or_receipt")
    if population_receipt:
        result.add(f"{population_snapshot.get('snapshot_id')}@{str(population_receipt)}")
    canonical_rows = sorted(
        [dict(row) for row in raw_rows],
        key=lambda row: (
            str(row.get("respondent_id")), str(row.get("question_id")),
            str(row.get("grade")), str(row.get("qualification")), str(row.get("value")),
        ),
    )
    result.add(f"PRIMARY-RAW@{sha256_json(canonical_rows)[:16]}")
    return sorted(result)


def resume_needs_analysis(
    plan_state: Mapping[str, Any],
    population_snapshot: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    synthesis_policy: Mapping[str, Any],
    semantic_provider: NeedDecisionProvider,
    *,
    output_root: Path,
) -> Dict[str, Any]:
    """Resume a blocked research run and produce the standalone final package if all gates pass."""
    if plan_state.get("state") not in {"READY_FOR_PRIMARY_RESEARCH", "BLOCKED_RESEARCH"}:
        raise NeedsFactoryV1Error(f"resume requires a research-blocked plan state, got {plan_state.get('state')}")
    previous_manifest = plan_state.get("run_manifest") or {}
    if not previous_manifest.get("run_id"):
        raise NeedsFactoryV1Error("plan state has no predecessor run manifest")

    source_ids = _successor_source_ids(plan_state, population_snapshot, raw_rows)
    successor = PipelineRun(
        project_input=plan_state["project_input"],
        call_snapshot=plan_state["call_intelligence"],
        ruleset_version="1.0",
        source_snapshot_ids=source_ids,
        historical_cutoff=plan_state.get("research_request", {}).get("historical_cutoff"),
    )
    resume_plan = successor.apply_resume(
        previous_manifest,
        changed_inputs=["population_snapshot", "primary_research_raw"],
    )
    resolved = successor.resolve_primary_research(
        plan_state["evidence_gaps"],
        population_snapshot,
        raw_rows,
        territory=str(plan_state["project_input"].get("territory")),
        school_identity=str(population_snapshot.get("school_identity")),
        period=str(population_snapshot.get("school_year")),
        source_document_id=str(population_snapshot.get("source_document_id") or "PRIMARY_RESEARCH_RAW"),
    )
    if not resolved.get("valid"):
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "RESUME",
            "state": "BLOCKED_RESEARCH_VALIDATION",
            "predecessor_run_id": previous_manifest.get("run_id"),
            "run_manifest": successor.manifest(),
            "resume_plan": resume_plan,
            "research_resolution": resolved,
            "next_action": "correct population snapshot or raw primary responses",
        }

    promoted = resolved["primary_research_evidence"]
    claim_resolution = attach_matching_research_evidence(
        plan_state.get("local_claims") or [],
        plan_state.get("external_evidence") or {},
        promoted["evidence"],
    )
    if claim_resolution["unresolved_gaps"]:
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "RESUME",
            "state": "BLOCKED_RESEARCH_GAPS",
            "unresolved_gaps": claim_resolution["unresolved_gaps"],
            "run_manifest": successor.manifest(),
            "next_action": "collect additional direct evidence for unresolved constructs",
        }

    combined_evidence = claim_resolution["evidence"]
    hypotheses = build_need_hypotheses(
        plan_state["research_request"],
        combined_evidence,
        synthesis_policy,
    )
    semantic = run_need_synthesis(hypotheses, combined_evidence, semantic_provider)
    if semantic["state"] != "READY_FOR_RANKING":
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "RESUME",
            "state": "BLOCKED_NEED_SYNTHESIS",
            "hypotheses": hypotheses,
            "semantic_decisions": semantic,
            "run_manifest": successor.manifest(),
            "next_action": "resolve semantic decision failures without adding unapproved evidence",
        }

    needs = semantic["needs"]
    need_validation = successor.validate_needs(needs, combined_evidence)
    if need_validation["failures"]:
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "RESUME",
            "state": "BLOCKED_NEED_VALIDATION",
            "need_validation": need_validation,
            "run_manifest": successor.manifest(),
        }
    ranked = successor.rank_needs(needs, combined_evidence)
    if ranked.get("blocked"):
        return {
            "schema_version": "nf.v1_state.v0.1",
            "product_mode": "NEEDS_ANALYSIS",
            "phase": "RESUME",
            "state": "BLOCKED_RANKING",
            "ranked_needs": ranked,
            "run_manifest": successor.manifest(),
        }

    mode_validation = validate_mode_inputs(
        "NEEDS_ANALYSIS",
        has_activity_plan=False,
        has_indicator_plan=False,
        need_count=len(needs),
    )
    if not mode_validation["valid"]:
        raise NeedsFactoryV1Error(f"standalone product mode invalid: {mode_validation['failures']}")

    causal = {
        "valid": True,
        "mode": "NOT_REQUIRED_FOR_NEEDS_ANALYSIS",
        "failures": [],
        "warnings": [{"warning": "causal_model_not_required_for_standalone_needs_analysis", "node_id": None}],
    }
    trace = {
        "valid": True,
        "mode": "NOT_REQUIRED_FOR_NEEDS_ANALYSIS",
        "failures": [],
        "coverage": {},
    }
    _artifact(successor, "NF09_CAUSAL_MODEL", "CAUSAL_MODE.json", causal, "NOT_REQUIRED")
    _artifact(successor, "NF10_INTERVENTION_TRACEABILITY", "TRACEABILITY_MODE.json", trace, "NOT_REQUIRED")
    release = successor.release_gate({"failures": [], "evidence_gaps": []})
    if not release["ready_for_narrative"]:
        raise NeedsFactoryV1Error("standalone release gate unexpectedly blocked")

    needs_by_id = {str(item["id"]): item for item in needs}
    successor.start("NF12_PACKAGE")
    pack = build_product_narrative_pack(
        "NEEDS_ANALYSIS",
        plan_state["project_input"],
        ranked,
        needs_by_id,
        combined_evidence,
        causal,
        trace,
        release,
    )
    successor.add_artifact("NF12_PACKAGE", "NARRATIVE_READY_PACK.json", pack)
    successor.close("NF12_PACKAGE", "PASS")

    compiled = compile_analysis(pack, title="Analiza de nevoi")
    final_dir = output_root / "final"
    dape_dir = output_root / "dape_checkpoint"
    export_manifest = export_final_package(compiled, final_dir, basename="ANALIZA_NEVOI")
    handoff = export_dape_checkpoint(
        successor.manifest(),
        pack,
        compiled,
        export_manifest,
        dape_dir,
        checkpoint_id=f"NF-V1-{successor.run_id}-HANDOFF",
        project_id="NEEDS-FACTORY",
        canonical_base_checkpoint=str(previous_manifest.get("run_id")),
    )

    return {
        "schema_version": "nf.v1_state.v0.1",
        "product_mode": "NEEDS_ANALYSIS",
        "phase": "RESUME",
        "state": "HANDOFF_READY_NOT_CANONICAL",
        "predecessor_run_id": previous_manifest.get("run_id"),
        "successor_run_id": successor.run_id,
        "resume_plan": resume_plan,
        "population_validation": resolved["population_validation"],
        "primary_research_evidence": {
            "population_snapshot_sha256": promoted["population_snapshot_sha256"],
            "raw_response_sha256": promoted["raw_response_sha256"],
            "aggregate_sha256": promoted["aggregate_sha256"],
            "evidence_ids": sorted(promoted["evidence"]),
        },
        "hypotheses": hypotheses,
        "semantic_decisions": semantic,
        "ranked_needs": ranked,
        "mode_validation": mode_validation,
        "release_gate": release,
        "narrative_pack_sha256": pack["pack_sha256"],
        "compiled_analysis_sha256": compiled["markdown_sha256"],
        "final_export_manifest": export_manifest,
        "dape_handoff": handoff,
        "run_manifest": successor.manifest(),
        "next_action": "DAPE host acceptance and explicit merge approval if integration is desired",
    }
