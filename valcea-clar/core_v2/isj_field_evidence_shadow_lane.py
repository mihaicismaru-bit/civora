from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

VACANCY_LIST_LABEL = "LISTA POSTURI CONCURS DIRECTORI 2026.pdf"
METHODOLOGY_LABEL_PREFIX = "OMEC-4155-Metodologiei privind organizarea CONCURS DIRECTORI 2026"


def _evidence_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-field-{digest[:24]}"


def _page_match(row: dict[str, Any], pattern: str, *, flags: int = 0) -> tuple[re.Match[str], dict[str, Any]]:
    compiled = re.compile(pattern, flags)
    matches: list[tuple[re.Match[str], dict[str, Any]]] = []
    for page in row.get("pages") or []:
        text = str(page.get("text") or "")
        match = compiled.search(text)
        if match:
            matches.append((match, page))
    if len(matches) != 1:
        raise RuntimeError(f"expected_one_page_match:{pattern[:80]}:observed={len(matches)}")
    return matches[0]


def _field(name: str, value: Any, *, row: dict[str, Any], page: dict[str, Any], excerpt: str, derivation: str = "exact_text_capture") -> dict[str, Any]:
    page_number = int(page.get("page_number") or 0)
    page_sha = str(page.get("text_sha256") or "")
    text_evidence_id = str(row.get("document_text_evidence_id") or "")
    if page_number <= 0 or not page_sha or not text_evidence_id or not excerpt.strip():
        raise RuntimeError("field_evidence_provenance_incomplete")
    return {
        "field": name,
        "value": value,
        "state": "FIELD_EVIDENCE_VERIFIED_SHADOW",
        "field_evidence_id": _evidence_id(text_evidence_id, name, str(value), str(page_number), page_sha, excerpt),
        "document_text_evidence_id": text_evidence_id,
        "document_text_sha256": row.get("normalized_text_sha256"),
        "page_number": page_number,
        "page_text_sha256": page_sha,
        "excerpt": excerpt.strip(),
        "derivation": derivation,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
    }


def _vacancy_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    title_match, title_page = _page_match(
        row,
        r"Lista\s+funcțiilor\s+vacante\s+de\s+director\s+și\s+director\s+adjunct.*?Județul\s+Vâlcea\s+pentru\s+care\s+se\s+organizează\s+concurs,\s+sesiunea\s+(2026)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    number_match, number_page = _page_match(row, r"Nr\.\s*(4596)/(17\.08\.2026)")
    if title_page.get("page_number") != 1 or number_page.get("page_number") != 1:
        raise RuntimeError("vacancy_list_header_not_on_page_one")

    indices: list[int] = []
    index_pages: dict[int, set[int]] = {}
    for page in row.get("pages") or []:
        page_number = int(page.get("page_number") or 0)
        for line in str(page.get("text") or "").splitlines():
            match = re.match(r"^\s*(\d{1,3})\b", line)
            if not match:
                continue
            value = int(match.group(1))
            if 1 <= value <= 999:
                indices.append(value)
                index_pages.setdefault(value, set()).add(page_number)
    unique = sorted(set(indices))
    if not unique or unique[0] != 1 or unique != list(range(1, unique[-1] + 1)):
        raise RuntimeError("vacancy_row_indices_not_contiguous")
    if unique[-1] < 20:
        raise RuntimeError("vacancy_row_sequence_implausibly_short")
    duplicates = sorted(value for value, count in Counter(indices).items() if count > 1)
    if any(value != 1 for value in duplicates):
        raise RuntimeError(f"unexpected_duplicate_vacancy_indices:{duplicates}")
    last_index = unique[-1]
    if last_index not in index_pages:
        raise RuntimeError("vacancy_last_index_provenance_missing")
    last_page_number = max(index_pages[last_index])
    last_page = next((page for page in row.get("pages") or [] if int(page.get("page_number") or 0) == last_page_number), None)
    if not isinstance(last_page, dict):
        raise RuntimeError("vacancy_last_page_missing")
    last_line = next(
        (line for line in str(last_page.get("text") or "").splitlines() if re.match(rf"^\s*{last_index}\b", line)),
        "",
    )
    if not last_line:
        raise RuntimeError("vacancy_last_index_line_missing")

    number = number_match.group(1)
    date_ro = number_match.group(2)
    day, month, year = date_ro.split(".")
    session_year = int(title_match.group(1))
    sequence_material = ",".join(str(v) for v in unique)
    sequence_sha = hashlib.sha256(sequence_material.encode("ascii")).hexdigest()
    count_excerpt = f"{title_match.group(0).strip()} | terminal row: {last_line.strip()}"
    count_field = _field(
        "vacant_function_count",
        last_index,
        row=row,
        page=last_page,
        excerpt=count_excerpt,
        derivation="complete_contiguous_table_row_index_sequence_1_to_N",
    )
    count_field["row_index_sequence_sha256"] = sequence_sha
    count_field["row_index_unique_count"] = len(unique)
    count_field["row_index_occurrence_count"] = len(indices)
    count_field["duplicate_row_indices_ignored_as_page_footer"] = duplicates
    count_field["first_row_index"] = 1
    count_field["last_row_index"] = last_index

    return [
        _field("list_document_number", number, row=row, page=number_page, excerpt=number_match.group(0)),
        _field("list_document_date", f"{year}-{month}-{day}", row=row, page=number_page, excerpt=number_match.group(0)),
        _field("contest_session_year", session_year, row=row, page=title_page, excerpt=title_match.group(0)),
        count_field,
    ]


def _methodology_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    order_match, order_page = _page_match(row, r"nr\.\s*4\.155/2026", flags=re.IGNORECASE)
    gazette_match, gazette_page = _page_match(row, r"MONITORUL OFICIAL AL ROMÂNIE, PARTEA I, Nr\. 552 bis/6\.VII\.2026", flags=re.IGNORECASE)
    seniority_match, seniority_page = _page_match(row, r"are\s+o\s+vechime\s+în\s+învățământul\s+preuniversitar\s+de\s+minimum\s+(5)\s+ani", flags=re.IGNORECASE)
    degree_match, degree_page = _page_match(row, r"este\s+absolvent\s+al\s+învățământului\s+superior\s+cu\s+diplomă\s+de\s+licență\s+sau\s+atestat\s+de\s+echivalare", flags=re.IGNORECASE)
    tenure_match, tenure_page = _page_match(row, r"este\s+titular\s+în\s+învățământul\s+preuniversitar,\s+având\s+încheiat\s+contract\s+de\s+muncă\s+pe\s+perioadă\s+nedeterminată", flags=re.IGNORECASE)
    return [
        _field("methodology_order_number", "4.155/2026", row=row, page=order_page, excerpt=order_match.group(0)),
        _field("methodology_official_gazette_date", "2026-07-06", row=row, page=gazette_page, excerpt=gazette_match.group(0)),
        _field("minimum_preuniversity_seniority_years", int(seniority_match.group(1)), row=row, page=seniority_page, excerpt=seniority_match.group(0)),
        _field("requires_higher_education_degree_or_equivalence", True, row=row, page=degree_page, excerpt=degree_match.group(0)),
        _field("requires_tenured_preuniversity_indefinite_contract", True, row=row, page=tenure_page, excerpt=tenure_match.group(0)),
    ]


def extract_field_evidence(content_report: dict[str, Any]) -> dict[str, Any]:
    if content_report.get("publication_authority") != "NONE":
        raise ValueError("content_report_publication_boundary_violation")
    if content_report.get("fact_kernel_promotion_allowed") is True or content_report.get("writer_allowed") is True:
        raise ValueError("content_report_promotion_boundary_violation")

    rows: list[dict[str, Any]] = []
    for source_row in content_report.get("rows") or []:
        if not isinstance(source_row, dict) or source_row.get("state") != "DOCUMENT_TEXT_EXTRACTED_SHADOW":
            continue
        label = str(source_row.get("document_label") or "")
        base = {
            "document_label": label,
            "document_content_evidence_id": source_row.get("document_content_evidence_id"),
            "document_text_evidence_id": source_row.get("document_text_evidence_id"),
            "document_text_sha256": source_row.get("normalized_text_sha256"),
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        try:
            if label == VACANCY_LIST_LABEL:
                fields = _vacancy_fields(source_row)
                role = "VACANCY_LIST_2026"
            elif label.startswith(METHODOLOGY_LABEL_PREFIX):
                fields = _methodology_fields(source_row)
                role = "METHODOLOGY_2026"
            else:
                continue
            rows.append({
                **base,
                "state": "FIELD_EVIDENCE_VERIFIED_SHADOW",
                "document_role": role,
                "field_evidence_count": len(fields),
                "fields": fields,
                "reason": "exact_field_values_bound_to_verified_pdf_text_non_authorizing",
            })
        except Exception as exc:
            rows.append({
                **base,
                "state": "BLOCKED",
                "document_role": "UNKNOWN_OR_UNVERIFIED",
                "field_evidence_count": 0,
                "fields": [],
                "reason": "field_evidence_extraction_or_provenance_validation_failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    all_fields = [field for row in rows if row.get("state") == "FIELD_EVIDENCE_VERIFIED_SHADOW" for field in row.get("fields") or []]
    vacancy_count = next((field.get("value") for field in all_fields if field.get("field") == "vacant_function_count"), None)
    session_year = next((field.get("value") for field in all_fields if field.get("field") == "contest_session_year"), None)
    material_candidate = isinstance(vacancy_count, int) and vacancy_count > 0 and session_year == 2026
    return {
        "schema_version": "1.0",
        "mode": "ISJ_FIELD_EVIDENCE_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "verified_document_count": sum(row.get("state") == "FIELD_EVIDENCE_VERIFIED_SHADOW" for row in rows),
        "field_evidence_count": len(all_fields),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "material_candidate_shadow_count": 1 if material_candidate else 0,
        "rows": rows,
        "truth_rule": "Field values may be emitted only when exact patterns are bound to verified PDF text plus page-level hashes, or when a table count is derived from a complete contiguous numbered-row sequence with auditable aggregation metadata. These fields remain non-authorizing: they do not create a FactKernel, article, visual readiness, site publication or social delivery.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract exact ISJ field-level evidence from verified PDF text without promoting a story")
    parser.add_argument("--content", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    content = json.loads(Path(args.content).read_text(encoding="utf-8"))
    result = extract_field_evidence(content)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verified_document_count": result["verified_document_count"],
        "field_evidence_count": result["field_evidence_count"],
        "material_candidate_shadow_count": result["material_candidate_shadow_count"],
        "blocked_count": result["blocked_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
