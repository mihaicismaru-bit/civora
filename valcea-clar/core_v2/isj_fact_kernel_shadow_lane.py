from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from contracts import ContractViolation, FactKernel

SOURCE_URL = "https://www.isjvalcea.ro/management/concurs-directori-2026"
SOURCE_LABEL = "Inspectoratul Școlar Județean Vâlcea — Concurs directori 2026"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


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


def _romanian_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = (
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    )
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"


def _validated_deadline_fact_promotion(
    materiality_candidate: dict[str, Any],
    fact_promotion: dict[str, Any] | None,
    fact_promotion_validation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if fact_promotion is None and fact_promotion_validation is None:
        return None
    if not isinstance(fact_promotion, dict) or not isinstance(fact_promotion_validation, dict):
        raise ValueError("deadline_fact_promotion_requires_gate_and_independent_validation")

    for label, report in (("fact_promotion", fact_promotion), ("fact_promotion_validation", fact_promotion_validation)):
        if report.get("publication_authority") != "NONE":
            raise ValueError(f"{label}_publication_boundary_violation")
        if report.get("acceptance_ready") is not False:
            raise ValueError(f"{label}_acceptance_boundary_violation")
        if report.get("writer_allowed") is not False:
            raise ValueError(f"{label}_writer_boundary_violation")
        if report.get("site_publish_allowed") is not False or report.get("social_publish_allowed") is not False:
            raise ValueError(f"{label}_publication_path_boundary_violation")

    if fact_promotion.get("state") != "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW":
        raise ValueError("deadline_fact_promotion_state_not_verified")
    if fact_promotion.get("fact_kernel_promotion_allowed") is not True:
        raise ValueError("deadline_fact_promotion_not_allowed")
    if fact_promotion_validation.get("status") != "PASS_SHADOW":
        raise ValueError("deadline_fact_promotion_independent_validation_not_passed")
    if fact_promotion_validation.get("fact_kernel_promotion_allowed") is not True:
        raise ValueError("deadline_fact_promotion_validation_not_allowed")

    candidates = fact_promotion.get("promotion_candidates") or []
    if len(candidates) != 1 or int(fact_promotion.get("promotion_candidate_count") or 0) != 1:
        raise ValueError("deadline_fact_promotion_candidate_cardinality")
    promotion = candidates[0]
    if not isinstance(promotion, dict) or promotion.get("field") != "registration_deadline":
        raise ValueError("deadline_fact_promotion_candidate_invalid")
    if promotion.get("state") != "FACT_KERNEL_FIELD_PROMOTION_VERIFIED_SHADOW":
        raise ValueError("deadline_fact_promotion_candidate_state_not_verified")
    if promotion.get("fact_kernel_promotion_allowed") is not True or promotion.get("writer_allowed") is not False:
        raise ValueError("deadline_fact_promotion_candidate_boundary_violation")

    materiality_promoted = (materiality_candidate.get("materiality_only_promoted_fields") or {}).get("registration_deadline")
    if not isinstance(materiality_promoted, dict):
        raise ValueError("materiality_promoted_deadline_missing")

    deadline = str(promotion.get("value") or "")
    date.fromisoformat(deadline)
    if deadline != str(fact_promotion.get("registration_deadline") or ""):
        raise ValueError("deadline_fact_promotion_top_level_value_mismatch")
    if deadline != str(fact_promotion_validation.get("registration_deadline") or ""):
        raise ValueError("deadline_fact_promotion_validation_value_mismatch")
    if deadline != str(materiality_promoted.get("value") or ""):
        raise ValueError("deadline_fact_promotion_materiality_value_mismatch")

    fact_promotion_id = str(promotion.get("fact_kernel_promotion_evidence_id") or "")
    if not fact_promotion_id:
        raise ValueError("deadline_fact_promotion_evidence_id_missing")
    if fact_promotion_id != str(fact_promotion.get("fact_kernel_promotion_evidence_id") or ""):
        raise ValueError("deadline_fact_promotion_top_level_evidence_id_mismatch")
    if fact_promotion_id != str(fact_promotion_validation.get("fact_kernel_promotion_evidence_id") or ""):
        raise ValueError("deadline_fact_promotion_validation_evidence_id_mismatch")

    upstream_materiality_id = str(promotion.get("upstream_materiality_promotion_evidence_id") or "")
    if not upstream_materiality_id:
        raise ValueError("deadline_upstream_materiality_promotion_evidence_id_missing")
    if upstream_materiality_id != str(fact_promotion.get("upstream_materiality_promotion_evidence_id") or ""):
        raise ValueError("deadline_upstream_materiality_promotion_top_level_mismatch")
    if upstream_materiality_id != str(fact_promotion_validation.get("upstream_materiality_promotion_evidence_id") or ""):
        raise ValueError("deadline_upstream_materiality_promotion_validation_mismatch")
    if upstream_materiality_id != str(materiality_promoted.get("promotion_evidence_id") or ""):
        raise ValueError("deadline_upstream_materiality_promotion_materiality_mismatch")

    identity_keys = (
        "field_evidence_id",
        "scope_field_evidence_id",
        "source_registration_window_field_evidence_id",
        "document_text_evidence_id",
        "page_text_sha256",
    )
    for key in identity_keys:
        value = str(promotion.get(key) or "")
        if not value:
            raise ValueError(f"deadline_fact_promotion_identity_missing:{key}")
        validation_key = "registration_deadline_field_evidence_id" if key == "field_evidence_id" else key
        if value != str(fact_promotion_validation.get(validation_key) or ""):
            raise ValueError(f"deadline_fact_promotion_validation_identity_mismatch:{key}")
        if value != str(materiality_promoted.get(key) or ""):
            raise ValueError(f"deadline_fact_promotion_materiality_identity_mismatch:{key}")

    supporting = [str(v) for v in promotion.get("supporting_field_evidence_ids") or []]
    if supporting != [str(v) for v in fact_promotion_validation.get("supporting_field_evidence_ids") or []]:
        raise ValueError("deadline_fact_promotion_supporting_validation_mismatch")
    if supporting != [str(v) for v in materiality_promoted.get("supporting_field_evidence_ids") or []]:
        raise ValueError("deadline_fact_promotion_supporting_materiality_mismatch")
    if len(supporting) != 2 or len(set(supporting)) != 2:
        raise ValueError("deadline_fact_promotion_supporting_identity_invalid")

    excerpt = _norm(promotion.get("excerpt"))
    if not excerpt or excerpt != _norm(fact_promotion_validation.get("excerpt")) or excerpt != _norm(materiality_promoted.get("excerpt")):
        raise ValueError("deadline_fact_promotion_excerpt_mismatch")
    page_number = int(promotion.get("page_number") or 0)
    if page_number <= 0 or page_number != int(fact_promotion_validation.get("page_number") or 0) or page_number != int(materiality_promoted.get("page_number") or 0):
        raise ValueError("deadline_fact_promotion_page_number_mismatch")

    existing_ids = [str(v) for v in materiality_candidate.get("field_evidence_ids") or []]
    if [str(v) for v in promotion.get("existing_fact_kernel_field_evidence_ids") or []] != existing_ids:
        raise ValueError("deadline_fact_promotion_existing_evidence_universe_mismatch")
    field_evidence_id = str(promotion.get("field_evidence_id") or "")
    if field_evidence_id in existing_ids:
        raise ValueError("deadline_fact_promotion_already_in_base_evidence_universe")

    return {
        "field": "registration_deadline",
        "value": deadline,
        "field_evidence_id": field_evidence_id,
        "scope_field_evidence_id": str(promotion["scope_field_evidence_id"]),
        "source_registration_window_field_evidence_id": str(promotion["source_registration_window_field_evidence_id"]),
        "supporting_field_evidence_ids": supporting,
        "document_text_evidence_id": str(promotion["document_text_evidence_id"]),
        "page_number": page_number,
        "page_text_sha256": str(promotion["page_text_sha256"]),
        "excerpt": excerpt,
        "upstream_materiality_promotion_evidence_id": upstream_materiality_id,
        "fact_kernel_promotion_evidence_id": fact_promotion_id,
    }


def compose_isj_fact_kernel(
    materiality: dict[str, Any],
    fields: dict[str, Any],
    calendar_fields: dict[str, Any],
    *,
    fact_deadline_promotion: dict[str, Any] | None = None,
    fact_deadline_promotion_validation: dict[str, Any] | None = None,
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

    try:
        promoted_deadline = _validated_deadline_fact_promotion(candidate, fact_deadline_promotion, fact_deadline_promotion_validation)
    except (ValueError, TypeError) as exc:
        return {**base, "state": "BLOCKED", "reason": f"deadline_fact_kernel_composition_gate:{exc}", "fact_kernel_count": 0, "kernels": []}

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

    promoted_fact_claims: list[dict[str, Any]] = []
    if promoted_deadline is not None:
        deadline = str(promoted_deadline["value"])
        deadline_claim = f"Calendarul oficial verificat pentru sesiunea {session} indică data de {_romanian_date(deadline)} ca termen-limită al perioadei de înscriere."
        promoted_fact_claims.append({
            **promoted_deadline,
            "claim": deadline_claim,
            "state": "FACT_KERNEL_COMPOSED_SHADOW_PENDING_WRITER_PROJECTION_GATE",
            "claim_evidence_ids": [
                str(promoted_deadline["field_evidence_id"]),
                str(promoted_deadline["scope_field_evidence_id"]),
                str(promoted_deadline["source_registration_window_field_evidence_id"]),
                str(promoted_deadline["document_text_evidence_id"]),
                str(promoted_deadline["fact_kernel_promotion_evidence_id"]),
            ],
            "writer_projection_allowed": False,
            "article_projection_allowed": False,
        })

    return {
        **base,
        "state": "FACT_KERNEL_VERIFIED_SHADOW",
        "reason": "exact_materiality_fields_promoted_to_evidence_bound_shadow_fact_kernel" + ("_plus_independently_validated_deadline_composition_pending_writer_projection" if promoted_fact_claims else ""),
        "fact_kernel_count": 1,
        "fact_kernel_deadline_composition_consumed": bool(promoted_fact_claims),
        "promoted_fact_claim_count": len(promoted_fact_claims),
        "kernels": [{
            "category": "LOCAL_EDUCATION_LEADERSHIP",
            "fact_kernel": kernel_doc,
            "claim_evidence": claim_evidence,
            "promoted_fact_claims": promoted_fact_claims,
            "writer_projection_excluded_fields": ["registration_deadline"] if promoted_fact_claims else [],
            "excluded_unverified_or_non_normalized_fields": list(candidate.get("excluded_unverified_or_non_normalized_fields") or []),
            "integrity_status": "PENDING_SEPARATE_GATE",
        }],
        "truth_rule": "The base writer-visible FactKernel still contains only the four historically verified field identities. When the separate materiality-to-FactKernel deadline gate and its independent validator both PASS_SHADOW, this composition may add one evidence-bound registration-deadline fact in promoted_fact_claims. That promoted fact is inside FactKernel composition truth but remains explicitly excluded from writer/article projection until a later independent writer gate. It grants no publication, social, merge, deploy or acceptance authority.",
    }


def _load_optional_runtime_pair(materiality_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    workdir = materiality_path.parent
    promotion_path = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion.json"
    validation_path = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion-validation.json"
    if not promotion_path.exists() and not validation_path.exists():
        return None, None
    if not promotion_path.exists() or not validation_path.exists():
        raise FileNotFoundError("deadline_fact_promotion_runtime_pair_incomplete")
    return json.loads(promotion_path.read_text(encoding="utf-8")), json.loads(validation_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose an evidence-bound ISJ FactKernel after field materiality adjudication")
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--fields", required=True)
    parser.add_argument("--calendar-fields", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    materiality_path = Path(args.materiality)
    promotion, promotion_validation = _load_optional_runtime_pair(materiality_path)
    result = compose_isj_fact_kernel(
        json.loads(materiality_path.read_text(encoding="utf-8")),
        json.loads(Path(args.fields).read_text(encoding="utf-8")),
        json.loads(Path(args.calendar_fields).read_text(encoding="utf-8")),
        fact_deadline_promotion=promotion,
        fact_deadline_promotion_validation=promotion_validation,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "fact_kernel_count": result.get("fact_kernel_count", 0), "promoted_fact_claim_count": result.get("promoted_fact_claim_count", 0), "fact_kernel_deadline_composition_consumed": result.get("fact_kernel_deadline_composition_consumed", False), "fabricated_claim_count": 0, "publication_authority": "NONE", "writer_allowed": False, "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
