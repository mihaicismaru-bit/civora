from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel

SOURCE_URL = "https://www.isjvalcea.ro/management/concurs-directori-2026"
SOURCE_LABEL = "Inspectoratul Școlar Județean Vâlcea — Concurs directori 2026"


def _field_map(*reports: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for report in reports:
        if report.get("publication_authority") != "NONE":
            raise ValueError("field_report_publication_boundary_violation")
        if report.get("fact_kernel_promotion_allowed") is True or report.get("writer_allowed") is True:
            raise ValueError("field_report_promotion_boundary_violation")
        for row in report.get("rows") or []:
            if not isinstance(row, dict):
                continue
            for field in row.get("fields") or []:
                if not isinstance(field, dict):
                    continue
                evidence_id = str(field.get("field_evidence_id") or "").strip()
                if not evidence_id:
                    continue
                out[evidence_id] = field
    return out


def compose_isj_fact_kernel(
    materiality: dict[str, Any],
    fields: dict[str, Any],
    calendar_fields: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "mode": "ISJ_FACT_KERNEL_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }
    if materiality.get("publication_authority") != "NONE":
        raise ValueError("materiality_publication_boundary_violation")
    if materiality.get("fact_kernel_promotion_allowed") is True or materiality.get("writer_allowed") is True:
        raise ValueError("materiality_promotion_boundary_violation")
    if materiality.get("state") != "MATERIALITY_CANDIDATE_SHADOW":
        terminal = materiality.get("state") if materiality.get("state") in {"NO_STORY", "BLOCKED"} else "BLOCKED"
        return {**base, "state": terminal, "reason": materiality.get("reason") or "materiality_candidate_missing", "fact_kernel_count": 0, "kernels": []}

    candidates = materiality.get("materiality_candidates") or []
    if len(candidates) != 1:
        return {**base, "state": "BLOCKED", "reason": "expected_exactly_one_materiality_candidate", "fact_kernel_count": 0, "kernels": []}
    candidate = candidates[0]
    if candidate.get("category") != "LOCAL_EDUCATION_LEADERSHIP":
        return {**base, "state": "BLOCKED", "reason": "unsupported_materiality_category", "fact_kernel_count": 0, "kernels": []}
    if candidate.get("fact_kernel_status") != "NOT_PROMOTED":
        return {**base, "state": "BLOCKED", "reason": "upstream_fact_kernel_status_not_pristine", "fact_kernel_count": 0, "kernels": []}

    evidence = _field_map(fields, calendar_fields)
    evidence_ids = [str(v) for v in candidate.get("field_evidence_ids") or []]
    if len(evidence_ids) != 4 or len(set(evidence_ids)) != 4 or any(eid not in evidence for eid in evidence_ids):
        return {**base, "state": "BLOCKED", "reason": "candidate_field_evidence_identity_mismatch", "fact_kernel_count": 0, "kernels": []}

    by_name = {str(evidence[eid].get("field") or ""): evidence[eid] for eid in evidence_ids}
    required = {"contest_session_year", "vacant_function_count", "list_document_date", "appointment_effective_date"}
    if set(by_name) != required:
        return {**base, "state": "BLOCKED", "reason": "candidate_field_set_mismatch", "fact_kernel_count": 0, "kernels": []}

    session = by_name["contest_session_year"].get("value")
    vacancy_count = by_name["vacant_function_count"].get("value")
    list_date = str(by_name["list_document_date"].get("value") or "")
    appointment_date = str(by_name["appointment_effective_date"].get("value") or "")
    if session != candidate.get("contest_session_year") or vacancy_count != candidate.get("vacant_function_count") or list_date != candidate.get("vacancy_list_date") or appointment_date != candidate.get("appointment_effective_date"):
        return {**base, "state": "BLOCKED", "reason": "candidate_value_evidence_mismatch", "fact_kernel_count": 0, "kernels": []}
    if session != 2026 or not isinstance(vacancy_count, int) or vacancy_count <= 0 or not list_date or not appointment_date:
        return {**base, "state": "BLOCKED", "reason": "required_fact_value_invalid", "fact_kernel_count": 0, "kernels": []}

    session_id = str(by_name["contest_session_year"]["field_evidence_id"])
    count_id = str(by_name["vacant_function_count"]["field_evidence_id"])
    list_date_id = str(by_name["list_document_date"]["field_evidence_id"])
    appointment_id = str(by_name["appointment_effective_date"]["field_evidence_id"])

    claim_vacancies = f"Pentru sesiunea {session}, lista oficială verificată a ISJ Vâlcea cuprinde {vacancy_count} de funcții vacante de director și director adjunct."
    claim_appointment = f"Calendarul oficial verificat indică data de {appointment_date} pentru intrarea în vigoare a deciziilor de numire rezultate din concurs."
    kernel = FactKernel(
        what=claim_vacancies,
        who="Inspectoratul Școlar Județean Vâlcea; funcțiile vacante de director și director adjunct",
        where="județul Vâlcea",
        when=f"Lista oficială este datată {list_date}; calendarul verificat indică {appointment_date} ca dată de intrare în vigoare a deciziilor de numire.",
        why_it_matters="Concursul privește ocuparea conducerii unităților de învățământ din județ. Termenul de înscriere și intervalele de etapă fără an explicit nu sunt afirmate deoarece nu sunt încă verificate la același nivel.",
        source=SOURCE_LABEL,
        source_url=SOURCE_URL,
        claims=(claim_vacancies, claim_appointment),
        evidence_ids=(session_id, count_id, list_date_id, appointment_id),
    )
    try:
        kernel.validate()
    except ContractViolation as exc:
        return {**base, "state": "BLOCKED", "reason": f"fact_kernel_contract:{exc}", "fact_kernel_count": 0, "kernels": []}

    kernel_doc = {
        "what": kernel.what,
        "who": kernel.who,
        "where": kernel.where,
        "when": kernel.when,
        "why_it_matters": kernel.why_it_matters,
        "source": kernel.source,
        "source_url": kernel.source_url,
        "claims": list(kernel.claims),
        "evidence_ids": list(kernel.evidence_ids),
    }
    claim_evidence = [
        {"claim": claim_vacancies, "field_evidence_ids": [session_id, count_id, list_date_id]},
        {"claim": claim_appointment, "field_evidence_ids": [session_id, appointment_id]},
    ]
    return {
        **base,
        "state": "FACT_KERNEL_VERIFIED_SHADOW",
        "reason": "exact_materiality_fields_promoted_to_evidence_bound_shadow_fact_kernel",
        "fact_kernel_count": 1,
        "kernels": [{
            "category": "LOCAL_EDUCATION_LEADERSHIP",
            "fact_kernel": kernel_doc,
            "claim_evidence": claim_evidence,
            "excluded_unverified_or_non_normalized_fields": list(candidate.get("excluded_unverified_or_non_normalized_fields") or []),
            "integrity_status": "PENDING_SEPARATE_GATE",
        }],
        "truth_rule": "Only values already accepted by the separate ISJ field-materiality gate may enter this shadow FactKernel. Every material claim carries field_evidence_id bindings. Registration deadline and raw schedule ranges remain excluded. This output does not authorize a writer or publication.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose an evidence-bound ISJ FactKernel after field materiality adjudication")
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--fields", required=True)
    parser.add_argument("--calendar-fields", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = compose_isj_fact_kernel(
        json.loads(Path(args.materiality).read_text(encoding="utf-8")),
        json.loads(Path(args.fields).read_text(encoding="utf-8")),
        json.loads(Path(args.calendar_fields).read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "fact_kernel_count": result.get("fact_kernel_count", 0), "fabricated_claim_count": 0, "publication_authority": "NONE", "writer_allowed": False, "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
