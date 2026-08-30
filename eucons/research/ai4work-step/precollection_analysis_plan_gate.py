from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_storage import RESEARCH_ID, canonical_json_bytes

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
COLLECTION_FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
PLAN_PATH = HERE / "NEED_ANALYSIS_PLAN_DRAFT.json"
LOCK_PATH = HERE / "PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_DETERMINISTIC_RANKING = {
    "normalization": "rating_1_to_5_to_0_100=(value-1)/4*100",
    "respondent_dimension_aggregation": "arithmetic_mean_of_all_mapped_direct_ratings_per_respondent",
    "within_population_aggregation": "arithmetic_mean_of_respondent_dimension_scores",
    "cross_population_combination": "equal_population_components_0.5_adults_0.5_employers",
    "numeric_computation": "exact_rational_no_intermediate_rounding",
    "rank_order_basis": "unrounded_exact_combined_score_descending",
    "tie_rule": "equal_exact_combined_scores_share_competition_rank",
    "display_precision": "2_decimals_round_half_up_display_only",
    "deterministic_display_tie_order": "need_id_ascending_does_not_break_ties",
}


class PrecollectionAnalysisPlanGateError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PrecollectionAnalysisPlanGateError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PrecollectionAnalysisPlanGateError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PrecollectionAnalysisPlanGateError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _activation_requested(contract: dict[str, Any], manifest: dict[str, Any], frame: dict[str, Any]) -> bool:
    return any(
        (
            contract.get("production_enabled") is True,
            manifest.get("state") == "APPROVED_FOR_PROD",
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
            frame.get("frame_status") == "APPROVED_FOR_PROD",
            frame.get("collection_enabled") is True,
        )
    )


def precollection_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    need_analysis_plan: dict[str, Any],
    plan_lock: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        collection_frame.get("research_id"),
        need_analysis_plan.get("research_id"),
        plan_lock.get("research_id"),
    }
    if research_ids != {RESEARCH_ID}:
        errors.append("research_id_mismatch")

    frame_id = collection_frame.get("collection_frame_id")
    if not isinstance(frame_id, str) or not frame_id.strip():
        errors.append("collection_frame_id_missing")
    if need_analysis_plan.get("collection_frame_id") != frame_id:
        errors.append("need_analysis_plan_collection_frame_mismatch")
    if plan_lock.get("collection_frame_id") != frame_id:
        errors.append("plan_lock_collection_frame_mismatch")

    if not _activation_requested(contract, manifest, collection_frame):
        return errors

    if need_analysis_plan.get("schema_version") != "eucons.ai4work_need_analysis_plan.v0.2":
        errors.append("need_analysis_plan_schema_invalid")
    if need_analysis_plan.get("status") != "APPROVED_FOR_PROD":
        errors.append("need_analysis_plan_not_approved")
    if need_analysis_plan.get("evidence_class") != "METHOD_PLAN_NOT_EVIDENCE":
        errors.append("need_analysis_plan_evidence_class_invalid")
    approval = need_analysis_plan.get("approval")
    if not isinstance(approval, dict) or approval.get("approved") is not True or approval.get("approved_for_prod") is not True:
        errors.append("need_analysis_plan_approval_incomplete")
        plan_approved_at = None
    else:
        if not isinstance(approval.get("approver_reference"), str) or not approval["approver_reference"].strip():
            errors.append("need_analysis_plan_approver_missing")
        try:
            plan_approved_at = _parse_ts(approval.get("approved_at"), field="need_analysis_plan.approval.approved_at")
        except PrecollectionAnalysisPlanGateError:
            plan_approved_at = None
            errors.append("need_analysis_plan_approved_at_invalid")

    ranking = need_analysis_plan.get("core_skill_ranking")
    if not isinstance(ranking, dict):
        errors.append("core_skill_ranking_missing")
    else:
        for key, expected in EXPECTED_DETERMINISTIC_RANKING.items():
            if ranking.get(key) != expected:
                errors.append(f"deterministic_ranking_contract_invalid:{key}")
        if ranking.get("respondent_weighting_allowed") is not False:
            errors.append("respondent_weighting_not_frozen_false")
        if ranking.get("secondary_evidence_can_change_numeric_order") is not False:
            errors.append("secondary_evidence_rank_influence_not_frozen_false")
        if ranking.get("missing_direct_indicator_imputation_allowed") is not False:
            errors.append("missing_indicator_imputation_not_frozen_false")
        if ranking.get("representativeness_claim_allowed") is not False:
            errors.append("representativeness_claim_not_frozen_false")
        if ranking.get("causal_claim_allowed") is not False:
            errors.append("causal_claim_not_frozen_false")
    if need_analysis_plan.get("synthetic_records_allowed") is not False:
        errors.append("synthetic_records_not_forbidden")
    if need_analysis_plan.get("test_twin_evidence_class") != "TEST_TWIN_NON_EVIDENCE":
        errors.append("test_twin_not_non_evidence")
    if need_analysis_plan.get("project_activity_as_need_evidence") is not False:
        errors.append("project_activity_need_evidence_not_forbidden")

    if plan_lock.get("schema_version") != "eucons.ai4work_precollection_analysis_plan_lock.v0.1":
        errors.append("plan_lock_schema_invalid")
    if plan_lock.get("state") != "LOCKED_BEFORE_PROD_ACTIVATION":
        errors.append("plan_lock_not_approved")
    if plan_lock.get("evidence_class") != "METHOD_CONTROL_NOT_EVIDENCE":
        errors.append("plan_lock_evidence_class_invalid")
    if plan_lock.get("need_analysis_plan_reference") != "NEED_ANALYSIS_PLAN_DRAFT.json":
        errors.append("plan_lock_reference_invalid")
    expected_sha = hashlib.sha256(canonical_json_bytes(need_analysis_plan)).hexdigest()
    declared_sha = plan_lock.get("need_analysis_plan_sha256")
    if not isinstance(declared_sha, str) or not SHA256_RE.fullmatch(declared_sha):
        errors.append("plan_lock_sha256_missing_or_invalid")
    elif declared_sha != expected_sha:
        errors.append("plan_lock_sha256_mismatch")
    if plan_lock.get("synthetic_or_test_twin_can_satisfy_lock") is not False:
        errors.append("plan_lock_test_twin_shortcut_not_forbidden")
    if plan_lock.get("project_activity_as_need_evidence") is not False:
        errors.append("plan_lock_project_activity_shortcut_not_forbidden")
    if plan_lock.get("secondary_evidence_can_change_numeric_order") is not False:
        errors.append("plan_lock_secondary_rank_shortcut_not_forbidden")
    if not isinstance(plan_lock.get("approver_reference"), str) or not plan_lock["approver_reference"].strip():
        errors.append("plan_lock_approver_missing")
    try:
        lock_approved_at = _parse_ts(plan_lock.get("approved_at"), field="plan_lock.approved_at")
    except PrecollectionAnalysisPlanGateError:
        lock_approved_at = None
        errors.append("plan_lock_approved_at_invalid")

    try:
        activation_approved_at = _parse_ts(manifest.get("approval_timestamp"), field="activation_manifest.approval_timestamp")
    except PrecollectionAnalysisPlanGateError:
        activation_approved_at = None
        errors.append("activation_approval_timestamp_invalid")

    if plan_approved_at is not None and lock_approved_at is not None and plan_approved_at > lock_approved_at:
        errors.append("plan_approved_after_lock")
    if lock_approved_at is not None and activation_approved_at is not None and lock_approved_at > activation_approved_at:
        errors.append("plan_locked_after_prod_activation_approval")

    if need_analysis_plan.get("merge_authorized") is not False or need_analysis_plan.get("deploy_authorized") is not False or need_analysis_plan.get("prod_activation_authorized") is not False:
        errors.append("analysis_plan_cannot_authorize_activation_or_deploy")
    if plan_lock.get("merge_authorized") is not False or plan_lock.get("deploy_authorized") is not False or plan_lock.get("prod_activation_authorized") is not False:
        errors.append("plan_lock_cannot_authorize_activation_or_deploy")

    return errors


def evaluate_repository_precollection_gate() -> tuple[bool, list[str]]:
    errors = precollection_errors(
        contract=_load(CONTRACT_PATH),
        manifest=_load(MANIFEST_PATH),
        collection_frame=_load(COLLECTION_FRAME_PATH),
        need_analysis_plan=_load(PLAN_PATH),
        plan_lock=_load(LOCK_PATH),
    )
    return not errors, errors


def assert_repository_fail_closed_or_prelocked() -> None:
    contract = _load(CONTRACT_PATH)
    manifest = _load(MANIFEST_PATH)
    frame = _load(COLLECTION_FRAME_PATH)
    ready, errors = evaluate_repository_precollection_gate()
    if _activation_requested(contract, manifest, frame) and not ready:
        raise PrecollectionAnalysisPlanGateError(
            "AI4WORK PROD activation surface opened before the exact analysis plan was approved and locked: "
            + "; ".join(errors)
        )


def main() -> int:
    try:
        assert_repository_fail_closed_or_prelocked()
    except (OSError, json.JSONDecodeError, PrecollectionAnalysisPlanGateError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    ready, errors = evaluate_repository_precollection_gate()
    if ready:
        contract = _load(CONTRACT_PATH)
        manifest = _load(MANIFEST_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        if _activation_requested(contract, manifest, frame):
            print("PASS: exact NEED_ANALYSIS_PLAN is approved and locked before PROD activation")
        else:
            print("PASS: AI4WORK remains fail-closed; precollection analysis-plan lock is not yet required")
    else:
        print("PASS: AI4WORK remains fail-closed with non-activation consistency diagnostics: " + ", ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
