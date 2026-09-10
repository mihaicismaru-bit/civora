from __future__ import annotations

from collections import Counter
from typing import Any

from disclosure_control import MIN_PUBLIC_CELL_N
from research_storage import RESEARCH_ID

ADULT_FORM = "AI4WORK_ADULTS_V1"
EMPLOYER_FORM = "AI4WORK_EMPLOYERS_V1"
FORM_POPULATION = {
    ADULT_FORM: "adults",
    EMPLOYER_FORM: "employers",
}
TARGET_REGIONS = ("Centru", "Sud-Muntenia", "Sud-Vest Oltenia")


class ProfileCoverageControlError(ValueError):
    pass


def _frozen_profile_options(forms_definition: Any) -> dict[str, dict[str, tuple[Any, ...]]]:
    if not isinstance(forms_definition, dict):
        raise ProfileCoverageControlError("forms_definition must be an object")
    if forms_definition.get("research_id") != RESEARCH_ID:
        raise ProfileCoverageControlError("forms_definition research_id mismatch")
    forms = forms_definition.get("forms")
    if not isinstance(forms, list):
        raise ProfileCoverageControlError("forms_definition.forms must be a list")

    result: dict[str, dict[str, tuple[Any, ...]]] = {}
    for form in forms:
        if not isinstance(form, dict):
            raise ProfileCoverageControlError("each frozen form must be an object")
        form_id = form.get("id")
        if form_id not in FORM_POPULATION:
            continue
        if form_id in result:
            raise ProfileCoverageControlError(f"duplicate frozen form definition: {form_id}")
        profile = form.get("profile")
        if not isinstance(profile, list) or not profile:
            raise ProfileCoverageControlError(f"frozen form {form_id} has no profile definition")
        fields: dict[str, tuple[Any, ...]] = {}
        for field in profile:
            if not isinstance(field, dict):
                raise ProfileCoverageControlError(f"invalid profile field in {form_id}")
            field_id = field.get("id")
            options = field.get("options")
            if not isinstance(field_id, str) or not field_id:
                raise ProfileCoverageControlError(f"invalid profile field id in {form_id}")
            if field_id in fields:
                raise ProfileCoverageControlError(f"duplicate profile field {form_id}.{field_id}")
            if not isinstance(options, list) or not options or len(options) != len(set(options)):
                raise ProfileCoverageControlError(
                    f"profile field {form_id}.{field_id} must have a duplicate-free frozen option list"
                )
            fields[field_id] = tuple(options)
        result[form_id] = fields

    if set(result) != set(FORM_POPULATION):
        raise ProfileCoverageControlError("forms_definition must contain both frozen AI4WORK forms exactly once")
    return result


def _coverage_dimensions(method_frame: Any, frozen: dict[str, dict[str, tuple[Any, ...]]]) -> dict[str, tuple[str, ...]]:
    if not isinstance(method_frame, dict):
        raise ProfileCoverageControlError("method_frame must be an object")
    if method_frame.get("research_id") != RESEARCH_ID:
        raise ProfileCoverageControlError("method_frame research_id mismatch")
    sampling = method_frame.get("sampling_design")
    if not isinstance(sampling, dict):
        raise ProfileCoverageControlError("method_frame sampling_design is missing")
    declared = sampling.get("coverage_dimensions")
    if not isinstance(declared, dict) or set(declared) != {"adults", "employers"}:
        raise ProfileCoverageControlError("coverage_dimensions must cover adults and employers exactly")

    result: dict[str, tuple[str, ...]] = {}
    for form_id, population in FORM_POPULATION.items():
        dimensions = declared.get(population)
        if not isinstance(dimensions, list) or not dimensions or len(dimensions) != len(set(dimensions)):
            raise ProfileCoverageControlError(
                f"coverage_dimensions.{population} must be a non-empty duplicate-free list"
            )
        if "region" not in dimensions:
            raise ProfileCoverageControlError(f"coverage_dimensions.{population} must include region")
        unknown = set(dimensions) - set(frozen[form_id])
        if unknown:
            raise ProfileCoverageControlError(
                f"coverage_dimensions.{population} contains field(s) absent from frozen instrument: {sorted(unknown)}"
            )
        result[form_id] = tuple(dimensions)
    return result


def assert_profile_coverage_control(
    records: list[dict[str, Any]],
    *,
    method_frame: dict[str, Any],
    forms_definition: dict[str, Any],
) -> dict[str, Any]:
    """Validate and describe frozen profile-dimension coverage for a real batch.

    The result is an internal QA control artifact, never need evidence and never a
    public reporting table. Sparse or empty cells do not by themselves make a
    non-probability sample representative or invalid; they are surfaced so the
    later synthesis/adversarial-QA stage can avoid conclusions that depend on
    unsupported strata.
    """
    if not isinstance(records, list) or not records:
        raise ProfileCoverageControlError("profile coverage control requires a non-empty record batch")

    frozen = _frozen_profile_options(forms_definition)
    dimensions = _coverage_dimensions(method_frame, frozen)

    overall: dict[str, dict[str, Counter[Any]]] = {
        form_id: {dimension: Counter() for dimension in dimensions[form_id]}
        for form_id in FORM_POPULATION
    }
    by_region: dict[str, dict[str, dict[str, Counter[Any]]]] = {
        form_id: {
            region: {
                dimension: Counter()
                for dimension in dimensions[form_id]
                if dimension != "region"
            }
            for region in TARGET_REGIONS
        }
        for form_id in FORM_POPULATION
    }

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ProfileCoverageControlError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise ProfileCoverageControlError(f"record[{index}] research_id mismatch")
        if record.get("synthetic") is not False:
            raise ProfileCoverageControlError("profile coverage control accepts only synthetic=false PROD-shaped records")
        form_id = record.get("form_id")
        if form_id not in FORM_POPULATION:
            raise ProfileCoverageControlError(f"record[{index}] unsupported form_id")
        profile = record.get("profile")
        if not isinstance(profile, dict):
            raise ProfileCoverageControlError(f"record[{index}] profile must be an object")

        for dimension in dimensions[form_id]:
            if dimension not in profile:
                raise ProfileCoverageControlError(
                    f"record[{index}] missing frozen coverage dimension {form_id}.{dimension}"
                )
            value = profile[dimension]
            if value not in frozen[form_id][dimension]:
                raise ProfileCoverageControlError(
                    f"record[{index}] value outside frozen options for {form_id}.{dimension}"
                )
            overall[form_id][dimension][value] += 1

        region = profile.get("region")
        if region not in TARGET_REGIONS:
            raise ProfileCoverageControlError(f"record[{index}] region outside target regions")
        for dimension in dimensions[form_id]:
            if dimension != "region":
                by_region[form_id][region][dimension][profile[dimension]] += 1

    counts: dict[str, Any] = {}
    zero_cells: list[str] = []
    sparse_cells: list[str] = []

    for form_id in FORM_POPULATION:
        counts[form_id] = {"overall": {}, "by_region": {}}
        for dimension in dimensions[form_id]:
            option_counts = {
                str(option): overall[form_id][dimension].get(option, 0)
                for option in frozen[form_id][dimension]
            }
            counts[form_id]["overall"][dimension] = option_counts
            for option, n in option_counts.items():
                scope = f"overall:{form_id}:{dimension}:{option}"
                if n == 0:
                    zero_cells.append(scope)
                elif n < MIN_PUBLIC_CELL_N:
                    sparse_cells.append(scope)

        for region in TARGET_REGIONS:
            counts[form_id]["by_region"][region] = {}
            for dimension in dimensions[form_id]:
                if dimension == "region":
                    continue
                option_counts = {
                    str(option): by_region[form_id][region][dimension].get(option, 0)
                    for option in frozen[form_id][dimension]
                }
                counts[form_id]["by_region"][region][dimension] = option_counts
                for option, n in option_counts.items():
                    scope = f"region:{region}:{form_id}:{dimension}:{option}"
                    if n == 0:
                        zero_cells.append(scope)
                    elif n < MIN_PUBLIC_CELL_N:
                        sparse_cells.append(scope)

    return {
        "schema_version": "eucons.ai4work_profile_coverage_control.v0.1",
        "research_id": RESEARCH_ID,
        "stage": "PRE_SYNTHESIS_PROFILE_COVERAGE_QA",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "validated_dimensions": {
            FORM_POPULATION[form_id]: list(dimensions[form_id])
            for form_id in FORM_POPULATION
        },
        "internal_counts_not_for_public_release": counts,
        "zero_cell_scopes": sorted(zero_cells),
        "sparse_cell_scopes_lt_public_release_floor": sorted(sparse_cells),
        "profile_coverage_qa_required": bool(zero_cells or sparse_cells),
        "public_small_cell_floor_reference": MIN_PUBLIC_CELL_N,
        "public_release_authorized": False,
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
        "scope_boundary": "PASS validates only that every real record carries valid frozen profile dimensions and that empty/sparse cells are explicitly surfaced for later adversarial QA. Counts are internal control data, not population prevalence and not public reporting output.",
    }
