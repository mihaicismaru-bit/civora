from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

import need_ranking_engine as ENGINE
import nf06_preingest as NF06
import response_integrity_control as INTEGRITY
from disclosure_control import MIN_PUBLIC_CELL_N
from research_storage import RESEARCH_ID, canonical_json_bytes

SCHEMA = "eucons.ai4work_adversarial_qa.v0.1"
PROD_EVIDENCE_CLASS = "PROD_REAL_EVIDENCE"
DERIVED_ANALYSIS_CLASS = "PROD_DERIVED_ANALYSIS"
CONTROL_CLASS = "CONTROL_ARTIFACT_NOT_EVIDENCE"
TARGET_REGIONS = tuple(ENGINE.TARGET_REGIONS)
FORMS_PATH = Path(__file__).resolve().with_name("forms_definition.json")


class AdversarialQAError(ValueError):
    pass


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rank_map(rank: list[dict[str, Any]]) -> dict[str, int]:
    if not isinstance(rank, list) or len(rank) != len(ENGINE.CORE_IDS):
        raise AdversarialQAError("rank must contain exactly H1-H5")
    result: dict[str, int] = {}
    for row in rank:
        if not isinstance(row, dict):
            raise AdversarialQAError("rank row must be an object")
        need_id = row.get("need_id")
        value = row.get("rank")
        if need_id not in ENGINE.CORE_IDS or need_id in result:
            raise AdversarialQAError("rank need_id set mismatch")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise AdversarialQAError("competition rank must be a positive integer")
        result[need_id] = value
    if set(result) != set(ENGINE.CORE_IDS):
        raise AdversarialQAError("rank need_id set mismatch")
    return result


def _top_members(rank: list[dict[str, Any]]) -> list[str]:
    mapping = _rank_map(rank)
    return sorted(need_id for need_id, value in mapping.items() if value == 1)


def _comparison(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]] | None,
    *,
    not_computable_reason: str | None = None,
) -> dict[str, Any]:
    baseline_map = _rank_map(baseline)
    if candidate is None:
        return {
            "stability_label": "NOT_COMPUTABLE",
            "material_rank_change": None,
            "top_rank_membership_changed": None,
            "max_absolute_competition_rank_delta": None,
            "rank_deltas": None,
            "baseline_top_rank_members": _top_members(baseline),
            "candidate_top_rank_members": None,
            "candidate_rank": None,
            "not_computable_reason": not_computable_reason or "required view could not be computed",
        }

    candidate_map = _rank_map(candidate)
    deltas = {
        need_id: abs(candidate_map[need_id] - baseline_map[need_id])
        for need_id in ENGINE.CORE_IDS
    }
    baseline_top = sorted(need_id for need_id, value in baseline_map.items() if value == 1)
    candidate_top = sorted(need_id for need_id, value in candidate_map.items() if value == 1)
    top_changed = baseline_top != candidate_top
    max_delta = max(deltas.values(), default=0)
    if top_changed or max_delta >= 2:
        label = "UNSTABLE"
    elif max_delta == 1:
        label = "SENSITIVE"
    else:
        label = "STABLE"
    return {
        "stability_label": label,
        "material_rank_change": label == "UNSTABLE",
        "top_rank_membership_changed": top_changed,
        "max_absolute_competition_rank_delta": max_delta,
        "rank_deltas": deltas,
        "baseline_top_rank_members": baseline_top,
        "candidate_top_rank_members": candidate_top,
        "candidate_rank": candidate,
        "not_computable_reason": None,
    }


def _population_scores(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    form_id: str,
) -> dict[str, Fraction]:
    population = [record for record in records if record.get("form_id") == form_id]
    if not population:
        raise AdversarialQAError(f"required population missing: {form_id}")
    core = plan.get("core_dimensions")
    if not isinstance(core, dict) or tuple(core) != ENGINE.CORE_IDS:
        raise AdversarialQAError("core dimensions must remain exactly H1-H5")
    ref_field = "adult_direct" if form_id == ENGINE.ADULT_FORM else "employer_direct"
    return {
        need_id: ENGINE._population_dimension_score(
            population,
            core[need_id][ref_field],
            field=f"adversarial.{form_id}.{need_id}",
        )
        for need_id in ENGINE.CORE_IDS
    }


def _rank_for_records(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    mode: str,
) -> list[dict[str, Any]]:
    if mode == "adult":
        return ENGINE._competition_rank(
            _population_scores(records, plan, form_id=ENGINE.ADULT_FORM)
        )
    if mode == "employer":
        return ENGINE._competition_rank(
            _population_scores(records, plan, form_id=ENGINE.EMPLOYER_FORM)
        )
    if mode != "pooled":
        raise AdversarialQAError(f"unsupported ranking mode: {mode}")
    adults = _population_scores(records, plan, form_id=ENGINE.ADULT_FORM)
    employers = _population_scores(records, plan, form_id=ENGINE.EMPLOYER_FORM)
    combined = {
        need_id: (adults[need_id] + employers[need_id]) / 2
        for need_id in ENGINE.CORE_IDS
    }
    return ENGINE._competition_rank(combined)


def _safe_rank(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    mode: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        return _rank_for_records(records, plan, mode=mode), None
    except (AdversarialQAError, ENGINE.NeedRankingEngineError) as exc:
        return None, str(exc)


def _validate_prod_bindings(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    need_analysis_plan: dict[str, Any],
    collection_frame: dict[str, Any],
    response_integrity_result: dict[str, Any],
) -> str:
    if not isinstance(records, list) or not records:
        raise AdversarialQAError("adversarial QA requires a non-empty real response batch")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AdversarialQAError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise AdversarialQAError(f"record[{index}] research_id mismatch")
        if record.get("synthetic") is not False:
            raise AdversarialQAError("synthetic/TEST TWIN records are permanently NON-EVIDENCE")
        if record.get("form_id") not in {ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM}:
            raise AdversarialQAError(f"record[{index}] unsupported form_id")

    source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    if not isinstance(ranking_result, dict):
        raise AdversarialQAError("ranking result required")
    if ranking_result.get("schema_version") != ENGINE.ENGINE_SCHEMA:
        raise AdversarialQAError("unsupported ranking-result schema")
    if ranking_result.get("research_id") != RESEARCH_ID:
        raise AdversarialQAError("ranking-result research mismatch")
    if ranking_result.get("evidence_class") != DERIVED_ANALYSIS_CLASS:
        raise AdversarialQAError("ranking result must be PROD_DERIVED_ANALYSIS")
    if ranking_result.get("source_evidence_class") != PROD_EVIDENCE_CLASS:
        raise AdversarialQAError("ranking result must derive only from PROD_REAL_EVIDENCE")
    if ranking_result.get("source_export_sha256") != source_sha:
        raise AdversarialQAError("ranking result is not bound to the supplied source export")
    if ranking_result.get("adversarial_qa_required") is not True:
        raise AdversarialQAError("ranking result does not require adversarial QA")
    if ranking_result.get("public_release_authorized") is not False:
        raise AdversarialQAError("pre-QA ranking must not authorize public release")
    if ranking_result.get("representativeness_claim_allowed") is not False:
        raise AdversarialQAError("representativeness boundary missing from ranking result")

    try:
        ENGINE._assert_plan_contract(need_analysis_plan)
    except ENGINE.NeedRankingEngineError as exc:
        raise AdversarialQAError(str(exc)) from exc
    if need_analysis_plan.get("status") != "APPROVED_FOR_PROD":
        raise AdversarialQAError("need-analysis plan must be APPROVED_FOR_PROD")
    approval = need_analysis_plan.get("approval") or {}
    if approval.get("approved") is not True or approval.get("approved_for_prod") is not True:
        raise AdversarialQAError("need-analysis plan approval is incomplete")
    plan_sha = _sha256(need_analysis_plan)
    if ranking_result.get("need_analysis_plan_sha256") != plan_sha:
        raise AdversarialQAError("ranking result is not bound to the supplied need-analysis plan")

    if not isinstance(collection_frame, dict):
        raise AdversarialQAError("collection frame required")
    if collection_frame.get("research_id") != RESEARCH_ID:
        raise AdversarialQAError("collection-frame research mismatch")
    if collection_frame.get("frame_status") != "APPROVED_FOR_PROD":
        raise AdversarialQAError("collection frame must be APPROVED_FOR_PROD")
    frame_approval = collection_frame.get("approval") or {}
    if frame_approval.get("approved_for_prod") is not True:
        raise AdversarialQAError("collection-frame approval is incomplete")
    frame_sha = _sha256(collection_frame)
    if ranking_result.get("collection_frame_sha256") != frame_sha:
        raise AdversarialQAError("ranking result is not bound to the supplied collection frame")

    if not isinstance(response_integrity_result, dict):
        raise AdversarialQAError("response-integrity result required")
    try:
        recomputed_integrity = INTEGRITY.assert_response_integrity_control(
            records,
            source_export_sha256=source_sha,
        )
    except INTEGRITY.ResponseIntegrityControlError as exc:
        raise AdversarialQAError(str(exc)) from exc
    if response_integrity_result != recomputed_integrity:
        raise AdversarialQAError("response-integrity result does not reconcile with the exact source batch")
    return source_sha


def _validate_baseline_ranks(
    records: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    ranking_result: dict[str, Any],
) -> dict[str, Any]:
    pooled = _rank_for_records(records, plan, mode="pooled")
    adult = _rank_for_records(records, plan, mode="adult")
    employer = _rank_for_records(records, plan, mode="employer")
    if ranking_result.get("pooled_equal_population_rank") != pooled:
        raise AdversarialQAError("pooled baseline rank drifted from deterministic ranking engine")
    if ranking_result.get("adult_component_rank") != adult:
        raise AdversarialQAError("adult baseline rank drifted from deterministic ranking engine")
    if ranking_result.get("employer_component_rank") != employer:
        raise AdversarialQAError("employer baseline rank drifted from deterministic ranking engine")

    regions: dict[str, Any] = {}
    published_regions = ranking_result.get("regional_equal_population_views")
    if not isinstance(published_regions, dict) or set(published_regions) != set(TARGET_REGIONS):
        raise AdversarialQAError("ranking result must contain all target-region views")
    for region in TARGET_REGIONS:
        region_records = [
            record for record in records
            if isinstance(record.get("profile"), dict)
            and record["profile"].get("region") == region
        ]
        region_pooled = _rank_for_records(region_records, plan, mode="pooled")
        region_adult = _rank_for_records(region_records, plan, mode="adult")
        region_employer = _rank_for_records(region_records, plan, mode="employer")
        if (published_regions.get(region) or {}).get("rank") != region_pooled:
            raise AdversarialQAError(f"regional baseline rank drifted for {region}")
        regions[region] = {
            "pooled": region_pooled,
            "adult": region_adult,
            "employer": region_employer,
        }
    return {
        "pooled": pooled,
        "adult": adult,
        "employer": employer,
        "regions": regions,
    }


def _structural_views(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    pooled = baseline["pooled"]
    views = [
        {
            "view_id": "POPULATION_ADULTS",
            "view_family": "population",
            "comparison": _comparison(pooled, baseline["adult"]),
        },
        {
            "view_id": "POPULATION_EMPLOYERS",
            "view_family": "population",
            "comparison": _comparison(pooled, baseline["employer"]),
        },
    ]
    for region in TARGET_REGIONS:
        views.append(
            {
                "view_id": f"REGION::{region}",
                "view_family": "region",
                "comparison": _comparison(pooled, baseline["regions"][region]["pooled"]),
            }
        )
    return views


def _channel_threshold(collection_frame: dict[str, Any]) -> float:
    thresholds = (
        (collection_frame.get("sampling_design") or {})
        .get("provisional_readiness_thresholds")
    )
    if not isinstance(thresholds, dict):
        raise AdversarialQAError("collection-frame readiness thresholds missing")
    value = thresholds.get("single_channel_share_max")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < 1:
        raise AdversarialQAError("single_channel_share_max must be between 0 and 1")
    return float(value)


def _dominant_channel_views(
    records: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    collection_frame: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    threshold = _channel_threshold(collection_frame)
    scopes: list[tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]] = [
        ("OVERALL", "pooled", records, baseline["pooled"]),
        (
            "POPULATION::ADULTS",
            "adult",
            [record for record in records if record.get("form_id") == ENGINE.ADULT_FORM],
            baseline["adult"],
        ),
        (
            "POPULATION::EMPLOYERS",
            "employer",
            [record for record in records if record.get("form_id") == ENGINE.EMPLOYER_FORM],
            baseline["employer"],
        ),
    ]
    for region in TARGET_REGIONS:
        region_records = [
            record for record in records
            if isinstance(record.get("profile"), dict)
            and record["profile"].get("region") == region
        ]
        scopes.extend(
            [
                (
                    f"REGION_POPULATION::{region}::ADULTS",
                    "adult",
                    [record for record in region_records if record.get("form_id") == ENGINE.ADULT_FORM],
                    baseline["regions"][region]["adult"],
                ),
                (
                    f"REGION_POPULATION::{region}::EMPLOYERS",
                    "employer",
                    [record for record in region_records if record.get("form_id") == ENGINE.EMPLOYER_FORM],
                    baseline["regions"][region]["employer"],
                ),
            ]
        )

    output: list[dict[str, Any]] = []
    for scope_id, mode, scope_records, scope_baseline in scopes:
        if not scope_records:
            raise AdversarialQAError(f"required channel-QA scope is empty: {scope_id}")
        counts = Counter(str(record.get("recruitment_channel_id")) for record in scope_records)
        n = len(scope_records)
        for channel_id, count in sorted(counts.items()):
            share = count / n
            if share <= threshold:
                continue
            retained = [
                record for record in scope_records
                if str(record.get("recruitment_channel_id")) != channel_id
            ]
            candidate, reason = _safe_rank(retained, plan, mode=mode)
            output.append(
                {
                    "view_id": f"DOMINANT_CHANNEL::{scope_id}::{channel_id}",
                    "view_family": "dominant_channel_sensitivity",
                    "scope": scope_id,
                    "ranking_mode": mode,
                    "opaque_recruitment_channel_id": channel_id,
                    "trigger_threshold": threshold,
                    "observed_share": share,
                    "n_before": n,
                    "n_after": len(retained),
                    "automatic_exclusion_applied": False,
                    "comparison": _comparison(
                        scope_baseline,
                        candidate,
                        not_computable_reason=reason,
                    ),
                }
            )
    return output


def _signature_sha(record: dict[str, Any]) -> str:
    payload = {
        "form_id": record.get("form_id"),
        "profile": record.get("profile"),
        "answers": record.get("answers", {}),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _repeated_signature_views(
    records: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        clusters[_signature_sha(record)].append(record)
    output: list[dict[str, Any]] = []
    for signature_sha, members in sorted(clusters.items()):
        if len(members) < 2:
            continue
        keeper_id = min(str(member.get("response_id")) for member in members)
        retained = [
            record for record in records
            if _signature_sha(record) != signature_sha
            or str(record.get("response_id")) == keeper_id
        ]
        candidate, reason = _safe_rank(retained, plan, mode="pooled")
        output.append(
            {
                "view_id": f"REPEATED_SIGNATURE::{signature_sha}",
                "view_family": "repeated_signature_sensitivity",
                "analytical_signature_sha256": signature_sha,
                "cluster_record_count": len(members),
                "records_removed_for_sensitivity_only": len(members) - 1,
                "deterministic_keeper_rule": "lowest opaque response_id",
                "automatic_exclusion_applied": False,
                "identity_or_device_linkage_used": False,
                "comparison": _comparison(
                    baseline["pooled"],
                    candidate,
                    not_computable_reason=reason,
                ),
            }
        )
    return output


def _profile_options() -> dict[str, dict[str, list[str]]]:
    payload = json.loads(FORMS_PATH.read_text(encoding="utf-8"))
    if payload.get("research_id") != RESEARCH_ID:
        raise AdversarialQAError("forms-definition research mismatch")
    result: dict[str, dict[str, list[str]]] = {}
    for form in payload.get("forms", []):
        form_id = form.get("id")
        if form_id not in {ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM}:
            continue
        fields: dict[str, list[str]] = {}
        for field in form.get("profile", []):
            field_id = field.get("id")
            options = field.get("options")
            if not isinstance(field_id, str) or not isinstance(options, list) or not options:
                raise AdversarialQAError("profile definition must contain bounded categorical options")
            fields[field_id] = [str(value) for value in options]
        result[form_id] = fields
    if set(result) != {ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM}:
        raise AdversarialQAError("profile definition must cover both instruments")
    return result


def _coverage_dimensions(collection_frame: dict[str, Any]) -> dict[str, list[str]]:
    coverage = ((collection_frame.get("sampling_design") or {}).get("coverage_dimensions"))
    if not isinstance(coverage, dict):
        raise AdversarialQAError("coverage dimensions missing from collection frame")
    mapped = {
        ENGINE.ADULT_FORM: coverage.get("adults"),
        ENGINE.EMPLOYER_FORM: coverage.get("employers"),
    }
    if not all(isinstance(value, list) and value for value in mapped.values()):
        raise AdversarialQAError("coverage dimensions must be declared for both instruments")
    return {form_id: [str(item) for item in values] for form_id, values in mapped.items()}


def _sparse_profile_views(
    records: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    collection_frame: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    options = _profile_options()
    coverage = _coverage_dimensions(collection_frame)
    sparse: list[dict[str, Any]] = []
    zero: list[dict[str, Any]] = []

    for form_id in (ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM):
        for dimension in coverage[form_id]:
            if dimension not in options[form_id]:
                raise AdversarialQAError(
                    f"collection-frame coverage dimension is not a frozen profile field: {form_id}.{dimension}"
                )
            values = options[form_id][dimension]
            if dimension == "region":
                cells = [(None, value) for value in values]
            else:
                cells = [(region, value) for region in TARGET_REGIONS for value in values]
            for region, value in cells:
                cell_records = []
                for record in records:
                    if record.get("form_id") != form_id:
                        continue
                    profile = record.get("profile")
                    if not isinstance(profile, dict):
                        continue
                    if region is not None and profile.get("region") != region:
                        continue
                    if profile.get(dimension) == value:
                        cell_records.append(record)
                n = len(cell_records)
                descriptor = {
                    "form_id": form_id,
                    "region": region,
                    "profile_dimension": dimension,
                    "profile_value": value,
                    "disclosure_floor": MIN_PUBLIC_CELL_N,
                }
                if n == 0:
                    zero.append(
                        {
                            **descriptor,
                            "status": "ZERO_CELL_CAVEAT",
                            "leave_one_cell_out_computable": False,
                        }
                    )
                    continue
                if n >= MIN_PUBLIC_CELL_N:
                    continue
                cell_response_ids = {str(record.get("response_id")) for record in cell_records}
                retained = [
                    record for record in records
                    if str(record.get("response_id")) not in cell_response_ids
                ]
                candidate, reason = _safe_rank(retained, plan, mode="pooled")
                sparse.append(
                    {
                        "view_id": (
                            f"SPARSE_PROFILE::{form_id}::{region or 'ALL_REGIONS'}::"
                            f"{dimension}::{value}"
                        ),
                        "view_family": "sparse_profile_sensitivity",
                        **descriptor,
                        "internal_cell_n": n,
                        "records_removed_for_sensitivity_only": n,
                        "automatic_exclusion_applied": False,
                        "comparison": _comparison(
                            baseline["pooled"],
                            candidate,
                            not_computable_reason=reason,
                        ),
                    }
                )
    return sparse, zero


def _overall_label(comparisons: list[dict[str, Any]]) -> str:
    labels = [item.get("comparison", {}).get("stability_label") for item in comparisons]
    if "NOT_COMPUTABLE" in labels:
        return "NOT_COMPUTABLE"
    if "UNSTABLE" in labels:
        return "UNSTABLE"
    if "SENSITIVE" in labels:
        return "SENSITIVE"
    return "STABLE"


def run_adversarial_qa(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    need_analysis_plan: dict[str, Any],
    collection_frame: dict[str, Any],
    response_integrity_result: dict[str, Any],
) -> dict[str, Any]:
    """Run the pre-registered adversarial QA without deleting or reweighting source records.

    PROD accepts only exact synthetic=false records already ranked by the deterministic
    H1-H5 engine. TEST TWIN and unit fixtures are NON-EVIDENCE and may exercise this
    code only inside tests. All leave-out operations are sensitivity views; the full
    source batch is preserved and no identity/device inference is attempted.
    """
    source_sha = _validate_prod_bindings(
        records,
        ranking_result=ranking_result,
        need_analysis_plan=need_analysis_plan,
        collection_frame=collection_frame,
        response_integrity_result=response_integrity_result,
    )
    baseline = _validate_baseline_ranks(
        records,
        plan=need_analysis_plan,
        ranking_result=ranking_result,
    )
    structural = _structural_views(baseline)
    dominant = _dominant_channel_views(
        records,
        plan=need_analysis_plan,
        collection_frame=collection_frame,
        baseline=baseline,
    )
    repeated = _repeated_signature_views(
        records,
        plan=need_analysis_plan,
        baseline=baseline,
    )
    sparse, zero = _sparse_profile_views(
        records,
        plan=need_analysis_plan,
        collection_frame=collection_frame,
        baseline=baseline,
    )

    all_comparisons = structural + dominant + repeated + sparse
    overall = _overall_label(all_comparisons)
    sensitivity_views = dominant + repeated + sparse
    sensitivity_not_computable = any(
        item["comparison"]["stability_label"] == "NOT_COMPUTABLE"
        for item in sensitivity_views
    )
    sensitivity_unstable = any(
        item["comparison"]["stability_label"] == "UNSTABLE"
        for item in sensitivity_views
    )
    collection_must_continue = sensitivity_not_computable or sensitivity_unstable
    competing_orders_required = any(
        item["comparison"]["stability_label"] == "UNSTABLE"
        for item in all_comparisons
    )

    return {
        "schema_version": SCHEMA,
        "research_id": RESEARCH_ID,
        "stage": "PROD_REAL_EVIDENCE_ADVERSARIAL_QA",
        "evidence_class": CONTROL_CLASS,
        "source_evidence_class": PROD_EVIDENCE_CLASS,
        "source_export_sha256": source_sha,
        "collection_frame_sha256": _sha256(collection_frame),
        "need_analysis_plan_sha256": _sha256(need_analysis_plan),
        "ranking_result_sha256": _sha256(ranking_result),
        "response_integrity_result_sha256": _sha256(response_integrity_result),
        "full_batch_record_count": len(records),
        "full_batch_rank_preserved": baseline["pooled"],
        "structural_required_views": structural,
        "dominant_channel_sensitivity_views": dominant,
        "repeated_signature_sensitivity_views": repeated,
        "sparse_profile_sensitivity_views": sparse,
        "zero_profile_cell_caveats": zero,
        "dominant_channel_triggered": bool(dominant),
        "repeated_signature_triggered": bool(repeated),
        "sparse_profile_triggered": bool(sparse),
        "overall_stability_label": overall,
        "qa_completed": True,
        "collection_must_continue": collection_must_continue,
        "needs_analysis_may_proceed": not collection_must_continue,
        "competing_orders_required": competing_orders_required,
        "single_definitive_rank_allowed": (
            not competing_orders_required and overall != "NOT_COMPUTABLE"
        ),
        "automatic_record_exclusion_applied": False,
        "respondent_weighting_applied": False,
        "identity_or_device_linkage_used": False,
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "representativeness_claim_allowed": False,
        "causal_claim_allowed": False,
        "public_release_authorized": False,
        "test_twin_evidence_eligible": False,
        "scope_boundary": "Adversarial QA is a control artifact over the exact PROD_REAL_EVIDENCE batch. Structural, dominant-channel, repeated-signature and sparse-profile views may challenge the pooled order but never delete source records, infer identity, add respondent weights, convert project activity into evidence, or make a population-representativeness claim. NOT_COMPUTABLE or unstable sensitivity views keep collection fail-closed; structural heterogeneity is reported as competing orders rather than forced into one definitive rank. Public NEEDS_ANALYSIS/DOCX release still requires the downstream disclosure/source-register/final-package gate.",
    }
