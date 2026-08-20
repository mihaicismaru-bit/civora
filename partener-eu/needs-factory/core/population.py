from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .engine import sha256_json


REQUIRED_FIELDS = (
    "snapshot_id",
    "as_of_date",
    "school_year",
    "school_identity",
    "eligible_population_n",
    "grades_in_scope",
    "qualifications_in_scope",
    "count_by_grade_and_qualification",
    "source_document_id",
    "source_date",
    "source_hash_or_receipt",
)


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def validate_population_snapshot(
    snapshot: Mapping[str, Any],
    *,
    historical_cutoff: Optional[str] = None,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for field in REQUIRED_FIELDS:
        value = snapshot.get(field)
        if value in (None, "", [], {}):
            failures.append({"failure": "missing_required_field", "field": field})

    population_n = snapshot.get("eligible_population_n")
    if isinstance(population_n, bool) or not isinstance(population_n, int) or population_n <= 0:
        failures.append({"failure": "invalid_eligible_population_n", "value": population_n})

    grades = {str(item) for item in (snapshot.get("grades_in_scope") or [])}
    qualifications = {str(item) for item in (snapshot.get("qualifications_in_scope") or [])}
    strata = list(snapshot.get("count_by_grade_and_qualification") or [])
    seen: set[Tuple[str, str]] = set()
    strata_total = 0

    for index, row in enumerate(strata):
        grade = str(row.get("grade") or "")
        qualification = str(row.get("qualification") or "")
        count = row.get("count")
        if not grade or not qualification:
            failures.append({"failure": "missing_stratum_identity", "index": index})
            continue
        key = (grade, qualification)
        if key in seen:
            failures.append({"failure": "duplicate_stratum", "grade": grade, "qualification": qualification})
        seen.add(key)
        if grade not in grades:
            failures.append({"failure": "stratum_grade_outside_scope", "grade": grade})
        if qualification not in qualifications:
            failures.append({"failure": "stratum_qualification_outside_scope", "qualification": qualification})
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            failures.append({"failure": "invalid_stratum_count", "index": index, "value": count})
        else:
            strata_total += count

    if isinstance(population_n, int) and population_n > 0 and strata_total != population_n:
        failures.append({
            "failure": "strata_total_mismatch",
            "eligible_population_n": population_n,
            "strata_total": strata_total,
        })

    as_of = _parse_date(snapshot.get("as_of_date"))
    source_date = _parse_date(snapshot.get("source_date"))
    cutoff = _parse_date(historical_cutoff)
    if not as_of:
        failures.append({"failure": "invalid_as_of_date"})
    if not source_date:
        failures.append({"failure": "invalid_source_date"})
    if as_of and source_date and source_date < as_of:
        warnings.append({"warning": "source_date_precedes_snapshot_date"})
    if cutoff:
        if as_of and as_of > cutoff:
            failures.append({"failure": "population_snapshot_post_cutoff", "as_of_date": str(snapshot.get("as_of_date"))})
        if source_date and source_date > cutoff:
            failures.append({"failure": "population_source_post_cutoff", "source_date": str(snapshot.get("source_date"))})

    normalized = {
        "snapshot_id": snapshot.get("snapshot_id"),
        "as_of_date": snapshot.get("as_of_date"),
        "school_year": snapshot.get("school_year"),
        "school_identity": snapshot.get("school_identity"),
        "eligible_population_n": population_n,
        "grades_in_scope": sorted(grades),
        "qualifications_in_scope": sorted(qualifications),
        "count_by_grade_and_qualification": sorted(
            [dict(row) for row in strata],
            key=lambda row: (str(row.get("grade")), str(row.get("qualification"))),
        ),
        "source_document_id": snapshot.get("source_document_id"),
        "source_date": snapshot.get("source_date"),
        "source_hash_or_receipt": snapshot.get("source_hash_or_receipt"),
        "historical_cutoff": historical_cutoff,
    }
    return {
        "schema_version": "nf.population_validation.v0.1",
        "valid": not failures,
        "failures": failures,
        "warnings": warnings,
        "strata_total": strata_total,
        "normalized_snapshot": normalized,
        "snapshot_sha256": sha256_json(normalized) if not failures else None,
    }
