from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .causal import validate_causal_graph
from .engine import (
    NeedsFactoryValidationError,
    detect_evidence_gaps,
    sha256_json,
    validate_need,
    validate_release,
    validate_traceability,
)
from .package import build_narrative_ready_pack
from .population import validate_population_snapshot
from .primary_research import generate_primary_research_plan
from .ranking import rank_needs as rank_needs_impl
from .research_evidence import promote_primary_research_evidence
from .resume import build_resume_plan, validate_resume_plan


STAGE_ORDER = [
    "NF00_INTAKE",
    "NF01_CALL_INTELLIGENCE",
    "NF02_RESEARCH_PLAN",
    "NF03_EXTERNAL_EVIDENCE",
    "NF04_EVIDENCE_VALIDATION",
    "NF05_GAP_DETECTION",
    "NF06_PRIMARY_RESEARCH",
    "NF07_NEED_DISCOVERY",
    "NF08_NEED_RANKING",
    "NF09_CAUSAL_MODEL",
    "NF10_INTERVENTION_TRACEABILITY",
    "NF11_ADVERSARIAL_QA",
    "NF12_PACKAGE",
]


def make_run_id(
    project_input: Mapping[str, Any],
    call_snapshot: Mapping[str, Any],
    historical_cutoff: Optional[str],
    ruleset_version: str,
    source_snapshot_ids: Sequence[str],
) -> str:
    payload = {
        "project_input": project_input,
        "call_snapshot": call_snapshot,
        "historical_cutoff": historical_cutoff,
        "ruleset_version": ruleset_version,
        "source_snapshot_ids": sorted(source_snapshot_ids),
    }
    return f"NF-{sha256_json(payload)[:20]}"


@dataclass
class PipelineEvent:
    event: str
    run_id: str
    project_id: str
    checkpoint: str
    status: str
    blocking: bool = False
    artifact_path: Optional[str] = None
    artifact_sha256: Optional[str] = None
    detail: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "checkpoint": self.checkpoint,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "status": self.status,
            "blocking": self.blocking,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


class PipelineRun:
    """Deterministic Needs Factory domain pipeline state.

    Persistence and artifact registration are intentionally external (DAPE contract).
    This object emits events and canonical artifacts for the host orchestrator.
    """

    def __init__(
        self,
        project_input: Mapping[str, Any],
        call_snapshot: Mapping[str, Any],
        ruleset_version: str,
        source_snapshot_ids: Sequence[str],
        historical_cutoff: Optional[str] = None,
    ) -> None:
        self.project_input = dict(project_input)
        self.call_snapshot = dict(call_snapshot)
        self.ruleset_version = ruleset_version
        self.source_snapshot_ids = sorted(source_snapshot_ids)
        self.historical_cutoff = historical_cutoff
        self.project_id = str(project_input.get("project_id") or project_input.get("project_code") or "UNKNOWN")
        self.run_id = make_run_id(
            self.project_input,
            self.call_snapshot,
            historical_cutoff,
            ruleset_version,
            self.source_snapshot_ids,
        )
        self.artifacts: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.closed_checkpoints: List[str] = []
        self.predecessor_run_id: Optional[str] = None
        self.resume_plan: Optional[Dict[str, Any]] = None

    def _emit(self, event: str, checkpoint: str, status: str, **kwargs: Any) -> None:
        self.events.append(PipelineEvent(
            event=event,
            run_id=self.run_id,
            project_id=self.project_id,
            checkpoint=checkpoint,
            status=status,
            **kwargs,
        ).as_dict())

    def start(self, checkpoint: str) -> None:
        self._emit("NF_CHECKPOINT_STARTED", checkpoint, "STARTED")

    def add_artifact(self, checkpoint: str, path: str, value: Any) -> str:
        digest = sha256_json(value)
        self.artifacts[path] = value
        self._emit(
            "NF_ARTIFACT_READY",
            checkpoint,
            "READY",
            artifact_path=path,
            artifact_sha256=digest,
        )
        return digest

    def close(self, checkpoint: str, status: str = "PASS") -> None:
        if checkpoint not in self.closed_checkpoints:
            self.closed_checkpoints.append(checkpoint)
        self._emit("NF_CHECKPOINT_CLOSED", checkpoint, status)

    def apply_resume(
        self,
        previous_manifest: Mapping[str, Any],
        *,
        changed_inputs: Sequence[str],
    ) -> Dict[str, Any]:
        plan = build_resume_plan(
            previous_manifest,
            changed_inputs=changed_inputs,
            successor_run_id=self.run_id,
        )
        validation = validate_resume_plan(plan)
        if not validation["valid"]:
            raise NeedsFactoryValidationError(f"invalid resume plan: {validation['failures']}")
        self.predecessor_run_id = str(previous_manifest.get("run_id"))
        self.resume_plan = plan
        self.closed_checkpoints = list(plan["reusable_closed_checkpoints"])
        return plan

    def gap_detection(
        self,
        claims: Sequence[Mapping[str, Any]],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        population_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        checkpoint = "NF05_GAP_DETECTION"
        self.start(checkpoint)
        gaps = detect_evidence_gaps(claims, evidence_by_id)
        snapshot = dict(population_snapshot or {})
        if any(g.get("scope") in {"school", "beneficiary", "uat", "locality"} for g in gaps):
            population_n = snapshot.get("eligible_population_n")
            if not isinstance(population_n, int) or population_n <= 0:
                gaps.append({
                    "gap_id": "GAP-POPULATION-SNAPSHOT",
                    "gap_type": "population_snapshot",
                    "scope": "school",
                    "blocking": True,
                    "reason": "primary research requires authoritative eligible population and strata counts",
                })
        artifact = {"schema_version": "nf.evidence_gaps.v0.1", "gaps": gaps}
        self.add_artifact(checkpoint, "EVIDENCE_GAPS.json", artifact)
        for gap in gaps:
            self._emit(
                "NF_EVIDENCE_GAP",
                checkpoint,
                "OPEN",
                blocking=bool(gap.get("blocking")),
                detail=str(gap.get("gap_id")),
            )
        self.close(checkpoint, "PASS" if not gaps else "PASS_WITH_GAPS")
        return artifact

    def primary_research_plan(
        self,
        evidence_gaps: Mapping[str, Any],
        population_snapshot: Mapping[str, Any],
    ) -> Dict[str, Any]:
        checkpoint = "NF06_PRIMARY_RESEARCH"
        self.start(checkpoint)
        gaps = [g for g in evidence_gaps.get("gaps", []) if g.get("gap_type") != "population_snapshot"]
        plan = generate_primary_research_plan(gaps, population_snapshot)
        self.add_artifact(checkpoint, "PRIMARY_RESEARCH_PLAN.json", plan)
        status = "BLOCKED_POPULATION" if plan.get("sampling_strategy") == "population_snapshot_required" else "PLAN_READY"
        self.close(checkpoint, status)
        return plan

    def resolve_primary_research(
        self,
        evidence_gaps: Mapping[str, Any],
        population_snapshot: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        *,
        territory: str,
        school_identity: str,
        period: str,
        source_document_id: str,
    ) -> Dict[str, Any]:
        checkpoint = "NF06_PRIMARY_RESEARCH"
        self.start(checkpoint)
        if self.resume_plan:
            self.add_artifact(checkpoint, "RESUME_PLAN.json", self.resume_plan)

        population_validation = validate_population_snapshot(
            population_snapshot,
            historical_cutoff=self.historical_cutoff,
        )
        self.add_artifact(checkpoint, "POPULATION_VALIDATION.json", population_validation)
        if not population_validation["valid"]:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail="population_snapshot")
            self.close(checkpoint, "FAIL_POPULATION")
            return {
                "valid": False,
                "population_validation": population_validation,
                "research_plan": None,
                "primary_research_evidence": None,
            }

        normalized_snapshot = population_validation["normalized_snapshot"]
        gaps = [g for g in evidence_gaps.get("gaps", []) if g.get("gap_type") != "population_snapshot"]
        research_plan = generate_primary_research_plan(gaps, normalized_snapshot)
        self.add_artifact(checkpoint, "PRIMARY_RESEARCH_PLAN.json", research_plan)

        try:
            promoted = promote_primary_research_evidence(
                rows,
                research_plan,
                population_validation,
                territory=territory,
                school_identity=school_identity,
                period=period,
                source_document_id=source_document_id,
            )
        except ValueError as exc:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail=str(exc))
            self.close(checkpoint, "FAIL_PRIMARY_RESEARCH")
            return {
                "valid": False,
                "population_validation": population_validation,
                "research_plan": research_plan,
                "primary_research_evidence": None,
                "error": str(exc),
            }

        self.add_artifact(checkpoint, "PRIMARY_RESEARCH_AGGREGATES.json", promoted["aggregates"])
        self.add_artifact(checkpoint, "PRIMARY_RESEARCH_EVIDENCE.json", promoted)
        self.close(checkpoint, "PASS")
        return {
            "valid": True,
            "population_validation": population_validation,
            "research_plan": research_plan,
            "primary_research_evidence": promoted,
        }

    def validate_needs(
        self,
        needs: Sequence[Mapping[str, Any]],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        checkpoint = "NF07_NEED_DISCOVERY"
        self.start(checkpoint)
        results = [validate_need(need, evidence_by_id) for need in needs]
        failures = [result for result in results if not result["valid"]]
        artifact = {"schema_version": "nf.need_validation.v0.1", "results": results, "failures": failures}
        self.add_artifact(checkpoint, "NEED_VALIDATION.json", artifact)
        if failures:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail="need_validation")
            self.close(checkpoint, "FAIL")
        else:
            self.close(checkpoint, "PASS")
        return artifact

    def rank_needs(
        self,
        needs: Sequence[Mapping[str, Any]],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        checkpoint = "NF08_NEED_RANKING"
        self.start(checkpoint)
        result = rank_needs_impl(needs, evidence_by_id)
        self.add_artifact(checkpoint, "NEEDS_RANKED.json", result)
        if result.get("blocked"):
            self._emit("NF_QA_FAILED", checkpoint, "BLOCKED", blocking=True, detail="unrankable_needs")
            self.close(checkpoint, "PASS_WITH_BLOCKED_NEEDS")
        else:
            self.close(checkpoint, "PASS")
        return result

    def causal_model(self, graph: Mapping[str, Any]) -> Dict[str, Any]:
        checkpoint = "NF09_CAUSAL_MODEL"
        self.start(checkpoint)
        graph_artifact = dict(graph)
        self.add_artifact(checkpoint, "CAUSAL_GRAPH.json", graph_artifact)
        result = validate_causal_graph(graph_artifact)
        self.add_artifact(checkpoint, "CAUSAL_VALIDATION.json", result)
        if result["valid"]:
            self.close(checkpoint, "PASS" if not result.get("warnings") else "PASS_WITH_WARNINGS")
        else:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail="causal_graph")
            self.close(checkpoint, "FAIL")
        return result

    def traceability(
        self,
        chains: Sequence[Mapping[str, Any]],
        need_ids: Sequence[str],
        indicator_ids: Sequence[str],
    ) -> Dict[str, Any]:
        checkpoint = "NF10_INTERVENTION_TRACEABILITY"
        self.start(checkpoint)
        result = validate_traceability(chains, need_ids, indicator_ids)
        self.add_artifact(checkpoint, "TRACEABILITY_VALIDATION.json", result)
        if result["valid"]:
            self.close(checkpoint, "PASS")
        else:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail="traceability")
            self.close(checkpoint, "FAIL")
        return result

    def release_gate(self, qa_report: Mapping[str, Any]) -> Dict[str, Any]:
        checkpoint = "NF11_ADVERSARIAL_QA"
        self.start(checkpoint)
        result = validate_release(qa_report)
        self.add_artifact(checkpoint, "RELEASE_GATE.json", result)
        if result["ready_for_narrative"]:
            self._emit("NF_QA_PASSED", checkpoint, "PASS")
            self.close(checkpoint, "PASS")
        else:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail="release_gate")
            self.close(checkpoint, "FAIL")
        return result

    def package(
        self,
        ranked_needs: Mapping[str, Any],
        needs_by_id: Mapping[str, Mapping[str, Any]],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        causal_validation: Mapping[str, Any],
        traceability_validation: Mapping[str, Any],
        release_gate: Mapping[str, Any],
    ) -> Dict[str, Any]:
        checkpoint = "NF12_PACKAGE"
        self.start(checkpoint)
        try:
            result = build_narrative_ready_pack(
                self.project_input,
                ranked_needs,
                needs_by_id,
                evidence_by_id,
                causal_validation,
                traceability_validation,
                release_gate,
            )
        except NeedsFactoryValidationError as exc:
            self._emit("NF_QA_FAILED", checkpoint, "FAIL", blocking=True, detail=str(exc))
            self.close(checkpoint, "FAIL")
            raise
        self.add_artifact(checkpoint, "NARRATIVE_READY_PACK.json", result)
        self.close(checkpoint, "PASS")
        return result

    def manifest(self) -> Dict[str, Any]:
        return {
            "schema_version": "nf.run_manifest.v0.1",
            "run_id": self.run_id,
            "predecessor_run_id": self.predecessor_run_id,
            "project_id": self.project_id,
            "historical_cutoff": self.historical_cutoff,
            "ruleset_version": self.ruleset_version,
            "source_snapshot_ids": self.source_snapshot_ids,
            "closed_checkpoints": self.closed_checkpoints,
            "resume_plan": self.resume_plan,
            "artifact_hashes": {path: sha256_json(value) for path, value in sorted(self.artifacts.items())},
            "events": self.events,
        }
