from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from typing import Any

import nf06_preingest as NF06
from research_storage import RESEARCH_ID, canonical_json_bytes

PLAN_SCHEMA = "eucons.ai4work_need_analysis_plan.v0.2"
GATE_SCHEMA = "eucons.ai4work_needs_synthesis_gate.v0.5"
ENGINE_SCHEMA = "eucons.ai4work_need_ranking_engine.v0.1"
ADULT_FORM = "AI4WORK_ADULTS_V1"
EMPLOYER_FORM = "AI4WORK_EMPLOYERS_V1"
CORE_IDS = ("H1", "H2", "H3", "H4", "H5")
TARGET_REGIONS = ("Sud-Vest Oltenia", "Sud-Muntenia", "Centru")


class NeedRankingEngineError(ValueError):
    pass


def _display_score(value: Fraction) -> str:
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    return format(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _normalized_rating(value: Any, *, field: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise NeedRankingEngineError(f"{field} must be a required integer rating 1..5")
    return Fraction((value - 1) * 100, 4)


def _extract_direct_rating(record: dict[str, Any], ref: dict[str, Any], *, field: str) -> Fraction:
    answers = record.get("answers")
    if not isinstance(answers, dict):
        raise NeedRankingEngineError(f"{field} record answers missing")
    question_id = ref.get("question_id")
    if question_id not in answers:
        raise NeedRankingEngineError(f"{field} required direct question missing")
    value = answers[question_id]
    row_id = ref.get("row_id")
    if row_id is not None:
        if not isinstance(value, dict) or row_id not in value:
            raise NeedRankingEngineError(f"{field} required direct matrix row missing")
        value = value[row_id]
    return _normalized_rating(value, field=field)


def _population_dimension_score(records: list[dict[str, Any]], refs: list[dict[str, Any]], *, field: str) -> Fraction:
    if not records:
        raise NeedRankingEngineError(f"{field} population has no eligible records")
    if not isinstance(refs, list) or not refs:
        raise NeedRankingEngineError(f"{field} direct mapping missing")
    respondent_scores: list[Fraction] = []
    for index, record in enumerate(records):
        direct = [
            _extract_direct_rating(record, ref, field=f"{field}[{index}]")
            for ref in refs
        ]
        respondent_scores.append(sum(direct, Fraction(0, 1)) / len(direct))
    return sum(respondent_scores, Fraction(0, 1)) / len(respondent_scores)


def _competition_rank(scores: dict[str, Fraction]) -> list[dict[str, Any]]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    output: list[dict[str, Any]] = []
    for need_id, score in ordered:
        rank = 1 + sum(1 for other in scores.values() if other > score)
        output.append(
            {
                "need_id": need_id,
                "rank": rank,
                "score_exact_fraction": _fraction_text(score),
                "score_display_0_100": _display_score(score),
            }
        )
    return output


def _assert_plan_contract(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA or plan.get("research_id") != RESEARCH_ID:
        raise NeedRankingEngineError("need-analysis plan schema/research mismatch")
    ranking = plan.get("core_skill_ranking")
    if not isinstance(ranking, dict):
        raise NeedRankingEngineError("core_skill_ranking missing")
    required = {
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
    for key, expected in required.items():
        if ranking.get(key) != expected:
            raise NeedRankingEngineError(f"ranking contract mismatch: {key}")
    if ranking.get("respondent_weighting_allowed") is not False:
        raise NeedRankingEngineError("respondent weighting must remain forbidden")
    if ranking.get("secondary_evidence_can_change_numeric_order") is not False:
        raise NeedRankingEngineError("secondary evidence cannot alter numeric order")
    if ranking.get("missing_direct_indicator_imputation_allowed") is not False:
        raise NeedRankingEngineError("missing direct indicator imputation must remain forbidden")


def compute_core_need_ranking(
    records: list[dict[str, Any]],
    *,
    synthesis_gate_result: dict[str, Any],
    need_analysis_plan: dict[str, Any],
) -> dict[str, Any]:
    """Compute the pre-registered H1-H5 rank from an exact gate-approved PROD batch.

    No TEST TWIN or synthetic record can enter. The computation uses exact
    rational arithmetic and performs no intermediate rounding. Display rounding
    is applied only after rank order and ties have been determined from exact
    scores. Secondary evidence and project activity are not inputs.
    """
    if not isinstance(records, list) or not records:
        raise NeedRankingEngineError("real response batch required")
    if not isinstance(synthesis_gate_result, dict):
        raise NeedRankingEngineError("needs-synthesis gate result required")
    if synthesis_gate_result.get("schema_version") != GATE_SCHEMA:
        raise NeedRankingEngineError("unsupported needs-synthesis gate schema")
    if synthesis_gate_result.get("research_id") != RESEARCH_ID:
        raise NeedRankingEngineError("needs-synthesis gate research mismatch")
    if synthesis_gate_result.get("ready_for_needs_synthesis") is not True:
        raise NeedRankingEngineError("batch has not passed the needs-synthesis gate")
    if synthesis_gate_result.get("source_evidence_class") != "PROD_REAL_EVIDENCE":
        raise NeedRankingEngineError("only PROD_REAL_EVIDENCE may be ranked")
    if synthesis_gate_result.get("representativeness_claim_allowed") is not False:
        raise NeedRankingEngineError("representativeness boundary missing")
    if synthesis_gate_result.get("weighting_allowed") is not False:
        raise NeedRankingEngineError("weighting boundary missing")

    _assert_plan_contract(need_analysis_plan)
    expected_plan_sha = hashlib.sha256(canonical_json_bytes(need_analysis_plan)).hexdigest()
    if synthesis_gate_result.get("need_analysis_plan_sha256") != expected_plan_sha:
        raise NeedRankingEngineError("analysis plan bytes do not match synthesis gate")

    expected_source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    if synthesis_gate_result.get("source_export_sha256") != expected_source_sha:
        raise NeedRankingEngineError("record batch does not match synthesis-gate source export")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise NeedRankingEngineError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise NeedRankingEngineError(f"record[{index}] research mismatch")
        if record.get("synthetic") is not False:
            raise NeedRankingEngineError("synthetic/TEST TWIN records are permanently NON-EVIDENCE")
        if record.get("form_id") not in {ADULT_FORM, EMPLOYER_FORM}:
            raise NeedRankingEngineError(f"record[{index}] unsupported form")

    adults = [record for record in records if record["form_id"] == ADULT_FORM]
    employers = [record for record in records if record["form_id"] == EMPLOYER_FORM]
    core = need_analysis_plan.get("core_dimensions")
    if not isinstance(core, dict) or tuple(core) != CORE_IDS:
        raise NeedRankingEngineError("core dimensions must remain exactly H1-H5")

    adult_scores: dict[str, Fraction] = {}
    employer_scores: dict[str, Fraction] = {}
    combined_scores: dict[str, Fraction] = {}
    dimensions: dict[str, Any] = {}

    for need_id in CORE_IDS:
        item = core[need_id]
        adult_score = _population_dimension_score(adults, item["adult_direct"], field=f"{need_id}.adults")
        employer_score = _population_dimension_score(employers, item["employer_direct"], field=f"{need_id}.employers")
        combined_score = (adult_score + employer_score) / 2
        adult_scores[need_id] = adult_score
        employer_scores[need_id] = employer_score
        combined_scores[need_id] = combined_score
        dimensions[need_id] = {
            "label": item["label"],
            "adult_score_exact_fraction": _fraction_text(adult_score),
            "adult_score_display_0_100": _display_score(adult_score),
            "employer_score_exact_fraction": _fraction_text(employer_score),
            "employer_score_display_0_100": _display_score(employer_score),
            "combined_score_exact_fraction": _fraction_text(combined_score),
            "combined_score_display_0_100": _display_score(combined_score),
        }

    regional_views: dict[str, Any] = {}
    for region in TARGET_REGIONS:
        region_adults = [record for record in adults if record.get("profile", {}).get("region") == region]
        region_employers = [record for record in employers if record.get("profile", {}).get("region") == region]
        region_scores: dict[str, Fraction] = {}
        for need_id in CORE_IDS:
            item = core[need_id]
            a_score = _population_dimension_score(region_adults, item["adult_direct"], field=f"{region}.{need_id}.adults")
            e_score = _population_dimension_score(region_employers, item["employer_direct"], field=f"{region}.{need_id}.employers")
            region_scores[need_id] = (a_score + e_score) / 2
        regional_views[region] = {
            "adult_n": len(region_adults),
            "employer_n": len(region_employers),
            "rank": _competition_rank(region_scores),
        }

    return {
        "schema_version": ENGINE_SCHEMA,
        "research_id": RESEARCH_ID,
        "stage": "PROD_REAL_EVIDENCE_CORE_NEED_RANKING",
        "evidence_class": "PROD_DERIVED_ANALYSIS",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "source_export_sha256": expected_source_sha,
        "collection_frame_sha256": synthesis_gate_result.get("collection_frame_sha256"),
        "method_frame_sha256": synthesis_gate_result.get("method_frame_sha256"),
        "need_analysis_plan_sha256": expected_plan_sha,
        "adult_n": len(adults),
        "employer_n": len(employers),
        "dimensions": dimensions,
        "pooled_equal_population_rank": _competition_rank(combined_scores),
        "adult_component_rank": _competition_rank(adult_scores),
        "employer_component_rank": _competition_rank(employer_scores),
        "regional_equal_population_views": regional_views,
        "rank_basis": "unrounded exact rational scores",
        "display_rounding": "2 decimals ROUND_HALF_UP, display only",
        "tie_rule": "equal exact combined scores share competition rank; need_id orders display only",
        "respondent_weighting_applied": False,
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "representativeness_claim_allowed": False,
        "causal_claim_allowed": False,
        "public_release_authorized": False,
        "adversarial_qa_required": True,
        "scope_boundary": "This deterministic result is derived only from the exact gate-approved PROD_REAL_EVIDENCE batch. It describes that eligible batch, not population prevalence. Supporting/secondary evidence may contextualize or challenge interpretation but cannot change H1-H5 numeric rank. Final NEEDS_ANALYSIS remains blocked until all pre-registered adversarial sensitivity views and disclosure controls pass.",
    }
