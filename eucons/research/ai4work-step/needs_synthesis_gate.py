from __future__ import annotations

from typing import Any

import profile_coverage_control as COVERAGE
import real_batch_synthesis_gate as BASE
from research_storage import RESEARCH_ID


class NeedsSynthesisGateError(ValueError):
    pass


def assert_real_batch_ready_for_needs_synthesis(
    records: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    method_frame: dict[str, Any],
    channel_register: dict[str, Any],
    forms_definition: dict[str, Any],
    dominant_channel_sensitivity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical entry gate for real PROD data entering needs synthesis.

    This wrapper deliberately keeps cryptographic/provenance/method coverage in
    real_batch_synthesis_gate and adds the frozen profile-dimension coverage
    control required by the collection-frame QA plan. Neither sub-control is
    evidence of need; both only decide whether the exact real batch may proceed
    to synthesis and adversarial QA.
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
        coverage = COVERAGE.assert_profile_coverage_control(
            records,
            method_frame=method_frame,
            forms_definition=forms_definition,
        )
    except COVERAGE.ProfileCoverageControlError as exc:
        raise NeedsSynthesisGateError(str(exc)) from exc

    return {
        "schema_version": "eucons.ai4work_needs_synthesis_gate.v0.1",
        "research_id": RESEARCH_ID,
        "stage": "REAL_BATCH_NEEDS_SYNTHESIS_GATE",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "ready_for_needs_synthesis": True,
        "base_gate_schema_version": base["schema_version"],
        "profile_coverage_control_schema_version": coverage["schema_version"],
        "collection_frame_sha256": base["collection_frame_sha256"],
        "channel_register_sha256": base["channel_register_sha256"],
        "profile_coverage_qa_required": coverage["profile_coverage_qa_required"],
        "profile_coverage_control": coverage,
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
        "public_release_authorized": False,
        "scope_boundary": "Only PASS of this wrapper permits the exact real PROD batch to enter needs synthesis/adversarial QA. PASS does not establish prevalence, causality, representativeness, ranking or any need conclusion; zero/sparse profile cells remain explicit QA constraints.",
    }
