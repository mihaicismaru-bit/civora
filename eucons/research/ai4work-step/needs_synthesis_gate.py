from __future__ import annotations

from typing import Any

import method_frame_lock_control as METHOD_LOCK
import need_analysis_plan_control as ANALYSIS_PLAN
import profile_coverage_control as COVERAGE
import real_batch_synthesis_gate as BASE
import response_integrity_control as INTEGRITY
from research_storage import RESEARCH_ID


class NeedsSynthesisGateError(ValueError):
    pass


def assert_real_batch_ready_for_needs_synthesis(
    records: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    method_frame: dict[str, Any],
    method_frame_lock: dict[str, Any],
    need_analysis_plan: dict[str, Any],
    need_analysis_plan_lock: dict[str, Any],
    channel_register: dict[str, Any],
    forms_definition: dict[str, Any],
    dominant_channel_sensitivity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical entry gate for real PROD data entering needs synthesis.

    This wrapper keeps batch/frame/channel provenance and method coverage in the
    lower-level gate, requires the exact method frame and exact question-to-need
    analysis plan to have been explicitly locked for this collection frame
    before collection started, validates frozen profile-dimension coverage, and
    surfaces exact repeated analytical signatures for adversarial QA without
    using identity/device linkage. The exact source-export digest is carried
    forward so deterministic ranking cannot be executed against a different
    record set. These controls are not evidence of need; they only decide
    whether the exact real batch may proceed to synthesis and what QA
    constraints must remain visible.
    """
    try:
        base = BASE.assert_real_batch_ready_for_synthesis(
            records,
            manifest=manifest,
            collection_frame=collection_frame,
            method_frame=method_frame,
            channel_register=channel_register,
            dominant_channel_sensitivity=dominant_channel_sensitivity,
        )
    except BASE.RealBatchSynthesisGateError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    try:
        method_lock = METHOD_LOCK.assert_method_frame_locked_before_collection(
            method_frame,
            collection_frame=collection_frame,
            method_frame_lock=method_frame_lock,
        )
    except METHOD_LOCK.MethodFrameLockError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    try:
        analysis_plan = ANALYSIS_PLAN.assert_need_analysis_plan_locked_before_collection(
            need_analysis_plan,
            plan_lock=need_analysis_plan_lock,
            collection_frame=collection_frame,
            forms_definition=forms_definition,
        )
    except ANALYSIS_PLAN.NeedAnalysisPlanControlError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    try:
        coverage = COVERAGE.assert_profile_coverage_control(
            records,
            method_frame=method_frame,
            forms_definition=forms_definition,
        )
    except COVERAGE.ProfileCoverageControlError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    try:
        integrity = INTEGRITY.assert_response_integrity_control(
            records,
            source_export_sha256=str(manifest.get("source_export_sha256", "")),
        )
    except INTEGRITY.ResponseIntegrityControlError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    return {
        "schema_version": "eucons.ai4work_needs_synthesis_gate.v0.5",
        "research_id": RESEARCH_ID,
        "stage": "REAL_BATCH_NEEDS_SYNTHESIS_GATE",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "ready_for_needs_synthesis": True,
        "base_gate_schema_version": base["schema_version"],
        "method_frame_lock_control_schema_version": method_lock["schema_version"],
        "need_analysis_plan_control_schema_version": analysis_plan["schema_version"],
        "profile_coverage_control_schema_version": coverage["schema_version"],
        "response_integrity_control_schema_version": integrity["schema_version"],
        "source_export_sha256": str(manifest["source_export_sha256"]),
        "collection_frame_id": collection_frame["collection_frame_id"],
        "method_frame_sha256": method_lock["method_frame_sha256"],
        "method_frame_locked_before_collection": True,
        "need_analysis_plan_sha256": analysis_plan["need_analysis_plan_sha256"],
        "need_analysis_plan_locked_before_collection": True,
        "core_skill_rank_dimensions": analysis_plan["core_skill_rank_dimensions"],
        "design_dimensions": analysis_plan["design_dimensions"],
        "numeric_computation": analysis_plan["numeric_computation"],
        "rank_order_basis": analysis_plan["rank_order_basis"],
        "tie_rule": analysis_plan["tie_rule"],
        "display_precision": analysis_plan["display_precision"],
        "collection_frame_sha256": base["collection_frame_sha256"],
        "channel_register_sha256": base["channel_register_sha256"],
        "profile_coverage_qa_required": coverage["profile_coverage_qa_required"],
        "profile_coverage_control": coverage,
        "response_integrity_qa_required": integrity["response_integrity_qa_required"],
        "response_integrity_control": integrity,
        "automatic_duplicate_exclusion_authorized": False,
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
        "public_release_authorized": False,
        "scope_boundary": "Only PASS of this wrapper permits the exact real PROD batch to enter needs synthesis/adversarial QA. The exact approved method frame and question-to-need analysis plan must be locked for the collection_frame_id before collection_started_at. H1-H5 core-skill ranking uses only the pre-registered direct respondent mappings and deterministic exact-rational arithmetic/tie rules; H6-H7 remain design diagnostics and secondary/project activity cannot add numeric rank points. Exact repeated analytical signatures are QA signals without identity/device linkage and never trigger automatic exclusion. PASS does not establish prevalence, causality, representativeness or any need conclusion; zero/sparse profile cells and repeated-signature clusters remain explicit QA constraints.",
    }
