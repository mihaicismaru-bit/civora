from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from research_storage import RESEARCH_ID, canonical_json_bytes

PLAN_SCHEMA = "eucons.ai4work_need_analysis_plan.v0.2"
LOCK_SCHEMA = "eucons.ai4work_need_analysis_plan_lock.v0.1"
CONTROL_SCHEMA = "eucons.ai4work_need_analysis_plan_control.v0.2"
CORE_IDS = ("H1", "H2", "H3", "H4", "H5")
DESIGN_IDS = ("H6", "H7")
FORM_BY_AUDIENCE = {"adult": "AI4WORK_ADULTS_V1", "employer": "AI4WORK_EMPLOYERS_V1"}


class NeedAnalysisPlanControlError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NeedAnalysisPlanControlError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NeedAnalysisPlanControlError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise NeedAnalysisPlanControlError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _forms_index(forms_definition: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(forms_definition, dict) or forms_definition.get("research_id") != RESEARCH_ID:
        raise NeedAnalysisPlanControlError("forms definition research_id mismatch")
    forms = forms_definition.get("forms")
    if not isinstance(forms, list):
        raise NeedAnalysisPlanControlError("forms definition must contain forms")
    by_id = {form.get("id"): form for form in forms if isinstance(form, dict)}
    expected = set(FORM_BY_AUDIENCE.values())
    if set(by_id) != expected:
        raise NeedAnalysisPlanControlError("forms definition must contain the two frozen AI4WORK forms exactly")
    return by_id


def _question_index(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    questions = form.get("questions")
    if not isinstance(questions, list):
        raise NeedAnalysisPlanControlError("form questions must be a list")
    return {item.get("id"): item for item in questions if isinstance(item, dict)}


def _validate_reference(ref: Any, *, questions: dict[str, dict[str, Any]], field: str) -> None:
    if not isinstance(ref, dict) or not isinstance(ref.get("question_id"), str):
        raise NeedAnalysisPlanControlError(f"{field} contains an invalid question reference")
    allowed = {"question_id", "row_id", "option"}
    if set(ref) - allowed:
        raise NeedAnalysisPlanControlError(f"{field} contains unreviewed reference fields")
    question = questions.get(ref["question_id"])
    if question is None:
        raise NeedAnalysisPlanControlError(f"{field} references a question absent from the frozen instrument")
    if "row_id" in ref:
        rows = question.get("rows")
        if not isinstance(rows, dict) or ref["row_id"] not in rows:
            raise NeedAnalysisPlanControlError(f"{field} references a row absent from the frozen instrument")
    if "option" in ref:
        options = question.get("options")
        if not isinstance(options, list) or ref["option"] not in options:
            raise NeedAnalysisPlanControlError(f"{field} references an option absent from the frozen instrument")


def _validate_ref_list(value: Any, *, questions: dict[str, dict[str, Any]], field: str, required: bool = True) -> None:
    if not isinstance(value, list) or (required and not value):
        raise NeedAnalysisPlanControlError(f"{field} must be a non-empty list")
    for ref in value:
        _validate_reference(ref, questions=questions, field=field)


def assert_need_analysis_plan_locked_before_collection(
    plan: Any,
    *,
    plan_lock: Any,
    collection_frame: dict[str, Any],
    forms_definition: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise NeedAnalysisPlanControlError("need analysis plan must be an object")
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise NeedAnalysisPlanControlError("unsupported need analysis plan schema")
    if plan.get("research_id") != RESEARCH_ID:
        raise NeedAnalysisPlanControlError("need analysis plan research_id mismatch")
    if plan.get("collection_frame_id") != collection_frame.get("collection_frame_id"):
        raise NeedAnalysisPlanControlError("need analysis plan collection_frame_id mismatch")
    if plan.get("status") != "APPROVED_FOR_PROD":
        raise NeedAnalysisPlanControlError("need analysis plan must be APPROVED_FOR_PROD before synthesis")
    if plan.get("evidence_class") != "METHOD_PLAN_NOT_EVIDENCE":
        raise NeedAnalysisPlanControlError("need analysis plan must remain METHOD_PLAN_NOT_EVIDENCE")
    if plan.get("forms_schema_version") != forms_definition.get("schema_version"):
        raise NeedAnalysisPlanControlError("need analysis plan forms schema does not match frozen instrument")

    approval = plan.get("approval")
    if not isinstance(approval, dict) or approval.get("approved") is not True or approval.get("approved_for_prod") is not True:
        raise NeedAnalysisPlanControlError("need analysis plan approval is incomplete")
    if not isinstance(approval.get("approver_reference"), str) or not approval["approver_reference"].strip():
        raise NeedAnalysisPlanControlError("need analysis plan requires an attributable approver reference")
    plan_approved_at = _parse_ts(approval.get("approved_at"), field="need_analysis_plan.approval.approved_at")

    forms = _forms_index(forms_definition)
    adult_questions = _question_index(forms[FORM_BY_AUDIENCE["adult"]])
    employer_questions = _question_index(forms[FORM_BY_AUDIENCE["employer"]])

    ranking = plan.get("core_skill_ranking")
    if not isinstance(ranking, dict):
        raise NeedAnalysisPlanControlError("core_skill_ranking is required")
    expected_ranking = {
        "scope": "H1-H5 only; scores describe the eligible respondent batch and are not population prevalence estimates",
        "adult_direct_source": "Q10 perceived-need rating matrix",
        "employer_direct_source": "E03 competence-impact rating matrix",
        "normalization": "rating_1_to_5_to_0_100=(value-1)/4*100",
        "respondent_dimension_aggregation": "arithmetic_mean_of_all_mapped_direct_ratings_per_respondent",
        "within_population_aggregation": "arithmetic_mean_of_respondent_dimension_scores",
        "cross_population_combination": "equal_population_components_0.5_adults_0.5_employers",
        "numeric_computation": "exact_rational_no_intermediate_rounding",
        "rank_order_basis": "unrounded_exact_combined_score_descending",
        "tie_rule": "equal_exact_combined_scores_share_competition_rank",
        "display_precision": "2_decimals_round_half_up_display_only",
        "deterministic_display_tie_order": "need_id_ascending_does_not_break_ties",
        "respondent_weighting_allowed": False,
        "secondary_evidence_can_change_numeric_order": False,
        "missing_direct_indicator_imputation_allowed": False,
        "representativeness_claim_allowed": False,
        "causal_claim_allowed": False,
    }
    if ranking != expected_ranking:
        raise NeedAnalysisPlanControlError("core-skill ranking rules differ from the pre-registered reviewed contract")

    core = plan.get("core_dimensions")
    if not isinstance(core, dict) or tuple(core) != CORE_IDS:
        raise NeedAnalysisPlanControlError("core_dimensions must be exactly H1-H5 in canonical order")
    for need_id in CORE_IDS:
        item = core[need_id]
        if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"].strip():
            raise NeedAnalysisPlanControlError(f"{need_id} requires a label")
        _validate_ref_list(item.get("adult_direct"), questions=adult_questions, field=f"{need_id}.adult_direct")
        _validate_ref_list(item.get("employer_direct"), questions=employer_questions, field=f"{need_id}.employer_direct")
        _validate_ref_list(item.get("supporting_adult"), questions=adult_questions, field=f"{need_id}.supporting_adult")
        _validate_ref_list(item.get("supporting_employer"), questions=employer_questions, field=f"{need_id}.supporting_employer")

    design = plan.get("design_dimensions")
    if not isinstance(design, dict) or tuple(design) != DESIGN_IDS:
        raise NeedAnalysisPlanControlError("design_dimensions must be exactly H6-H7 in canonical order")
    _validate_ref_list(design["H6"].get("sources"), questions=employer_questions, field="H6.sources")
    _validate_ref_list(design["H7"].get("adult_sources"), questions=adult_questions, field="H7.adult_sources")
    _validate_ref_list(design["H7"].get("employer_sources"), questions=employer_questions, field="H7.employer_sources")
    if "not mixed into H1-H5" not in str(design["H6"].get("ranking_scope", "")):
        raise NeedAnalysisPlanControlError("H6 must remain outside the H1-H5 core-skill rank")
    if "not mixed into H1-H5" not in str(design["H7"].get("ranking_scope", "")):
        raise NeedAnalysisPlanControlError("H7 must remain outside the H1-H5 core-skill rank")

    if plan.get("synthetic_records_allowed") is not False or plan.get("test_twin_evidence_class") != "TEST_TWIN_NON_EVIDENCE":
        raise NeedAnalysisPlanControlError("TEST TWIN must remain NON-EVIDENCE and excluded from the analysis plan")
    if plan.get("project_activity_as_need_evidence") is not False:
        raise NeedAnalysisPlanControlError("project activity cannot be need evidence")
    if plan.get("merge_authorized") is not False or plan.get("deploy_authorized") is not False or plan.get("prod_activation_authorized") is not False:
        raise NeedAnalysisPlanControlError("analysis-plan approval cannot authorize merge, deploy or PROD activation")

    qa = plan.get("adversarial_qa")
    if not isinstance(qa, dict) or qa.get("full_batch_result_must_be_preserved") is not True or qa.get("automatic_record_exclusion_allowed") is not False:
        raise NeedAnalysisPlanControlError("adversarial QA safeguards are incomplete")
    required_views = qa.get("required_views")
    if not isinstance(required_views, list) or len(required_views) != len(set(required_views)) or len(required_views) < 6:
        raise NeedAnalysisPlanControlError("adversarial QA required_views are incomplete")

    if not isinstance(plan_lock, dict) or plan_lock.get("schema_version") != LOCK_SCHEMA:
        raise NeedAnalysisPlanControlError("need analysis plan lock is missing or unsupported")
    if plan_lock.get("research_id") != RESEARCH_ID or plan_lock.get("collection_frame_id") != collection_frame.get("collection_frame_id"):
        raise NeedAnalysisPlanControlError("need analysis plan lock scope mismatch")
    if plan_lock.get("status") != "APPROVED_BEFORE_COLLECTION" or plan_lock.get("evidence_class") != "METHOD_CONTROL_NOT_EVIDENCE":
        raise NeedAnalysisPlanControlError("need analysis plan lock is not approved method control")
    if not isinstance(plan_lock.get("approver_reference"), str) or not plan_lock["approver_reference"].strip():
        raise NeedAnalysisPlanControlError("need analysis plan lock requires an attributable approver reference")

    expected_sha = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    if plan_lock.get("need_analysis_plan_sha256") != expected_sha:
        raise NeedAnalysisPlanControlError("need analysis plan bytes do not match the pre-collection lock")
    lock_approved_at = _parse_ts(plan_lock.get("approved_at"), field="need_analysis_plan_lock.approved_at")
    collection_started_at = _parse_ts(collection_frame.get("collection_started_at"), field="collection_started_at")
    if lock_approved_at > collection_started_at or plan_approved_at > collection_started_at:
        raise NeedAnalysisPlanControlError("need analysis plan was not approved and locked before collection started")

    return {
        "schema_version": CONTROL_SCHEMA,
        "research_id": RESEARCH_ID,
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "collection_frame_id": collection_frame["collection_frame_id"],
        "need_analysis_plan_sha256": expected_sha,
        "need_analysis_plan_locked_before_collection": True,
        "core_skill_rank_dimensions": list(CORE_IDS),
        "design_dimensions": list(DESIGN_IDS),
        "numeric_computation": ranking["numeric_computation"],
        "rank_order_basis": ranking["rank_order_basis"],
        "tie_rule": ranking["tie_rule"],
        "display_precision": ranking["display_precision"],
        "secondary_evidence_can_change_numeric_order": False,
        "respondent_weighting_allowed": False,
        "representativeness_claim_allowed": False,
        "test_twin_allowed": False,
        "project_activity_as_need_evidence": False,
    }
