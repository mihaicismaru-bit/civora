from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from isj_embedded_content_shadow_lane import (
    _allowed_final_host,
    _download_url,
    _extract_pdf_text,
    _fetch_document,
    _validate_document_bytes,
    _validate_extraction_result,
)
from isj_embedded_notice_shadow_lane import _fold

MAX_CONTEXT_DOCUMENTS = 6
TARGET_ROLES = ("REGISTRATION_NOTICE", "CONTEST_CALENDAR", "CONTEST_PROCEDURE")


def _verified_contest_context(field_report: dict[str, Any], *, expected_year: int) -> dict[str, Any] | None:
    if field_report.get("publication_authority") != "NONE":
        raise ValueError("field_report_publication_boundary_violation")
    if field_report.get("fact_kernel_promotion_allowed") is True or field_report.get("writer_allowed") is True:
        raise ValueError("field_report_promotion_boundary_violation")

    matches: list[dict[str, Any]] = []
    for row in field_report.get("rows") or []:
        if not isinstance(row, dict) or row.get("state") != "FIELD_EVIDENCE_VERIFIED_SHADOW":
            continue
        for field in row.get("fields") or []:
            if not isinstance(field, dict):
                continue
            if field.get("state") != "FIELD_EVIDENCE_VERIFIED_SHADOW":
                continue
            if field.get("field") != "contest_session_year":
                continue
            if field.get("value") != expected_year:
                continue
            field_evidence_id = str(field.get("field_evidence_id") or "")
            text_evidence_id = str(field.get("document_text_evidence_id") or "")
            page_sha = str(field.get("page_text_sha256") or "")
            if not field_evidence_id or not text_evidence_id or not page_sha:
                continue
            matches.append(
                {
                    "contest_session_year": expected_year,
                    "contest_session_field_evidence_id": field_evidence_id,
                    "contest_session_document_text_evidence_id": text_evidence_id,
                    "contest_session_page_number": field.get("page_number"),
                    "contest_session_page_text_sha256": page_sha,
                }
            )
    if len(matches) != 1:
        return None
    return matches[0]


def _role_from_label(label: str) -> str | None:
    folded = _fold(label)
    if not folded:
        return None
    if "inscriere" in folded and ("director" in folded or "concurs" in folded):
        return "REGISTRATION_NOTICE"
    if "calendar" in folded and ("director" in folded or "concurs" in folded):
        return "CONTEST_CALENDAR"
    if ("procedur" in folded or "procedura" in folded) and ("director" in folded or "concurs" in folded):
        return "CONTEST_PROCEDURE"
    return None


def _selected_bindings(target_report: dict[str, Any]) -> list[dict[str, Any]]:
    if target_report.get("publication_authority") != "NONE":
        raise ValueError("target_report_publication_boundary_violation")
    if target_report.get("fact_kernel_promotion_allowed") is True or target_report.get("writer_allowed") is True:
        raise ValueError("target_report_promotion_boundary_violation")

    selected: list[dict[str, Any]] = []
    seen_resources: set[tuple[str, str]] = set()
    for parent in target_report.get("rows") or []:
        if not isinstance(parent, dict) or parent.get("state") != "EMBEDDED_TARGET_IDENTITY_SHADOW":
            continue
        for binding in parent.get("bindings") or []:
            if not isinstance(binding, dict):
                continue
            if binding.get("state") != "TARGET_IDENTITY_BOUND_SHADOW":
                continue
            if binding.get("target_identity_verified") is not True:
                continue
            if binding.get("future_content_fetch_eligible") is not True:
                continue
            role = _role_from_label(str(binding.get("label") or ""))
            if role is None:
                continue
            key = (str(binding.get("target_class") or ""), str(binding.get("resource_id") or ""))
            if not all(key) or key in seen_resources:
                continue
            seen_resources.add(key)
            selected.append({"parent": parent, "binding": binding, "document_role": role})
            if len(selected) >= MAX_CONTEXT_DOCUMENTS:
                return selected
    return selected


def capture_context_documents(
    target_report: dict[str, Any],
    field_report: dict[str, Any],
    *,
    allow_network: bool,
    expected_year: int,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
    extractor: Callable[[bytes], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = _verified_contest_context(field_report, expected_year=expected_year)
    selected = _selected_bindings(target_report)
    rows: list[dict[str, Any]] = []

    if context is None:
        return {
            "schema_version": "1.0",
            "mode": "ISJ_CONTEXT_DOCUMENTS_SHADOW",
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "network_read_enabled": allow_network,
            "contest_context_verified": False,
            "expected_contest_session_year": expected_year,
            "selected_context_document_count": 0,
            "document_content_captured_shadow_count": 0,
            "document_text_extracted_shadow_count": 0,
            "blocked_count": 1,
            "rows": [
                {
                    "state": "BLOCKED",
                    "reason": "verified_contest_session_context_missing_or_ambiguous",
                    "publication_authority": "NONE",
                    "material_fact_use": False,
                    "fact_kernel_promotion_allowed": False,
                    "writer_allowed": False,
                    "site_publish_allowed": False,
                    "social_publish_allowed": False,
                }
            ],
            "truth_rule": (
                "A registration, calendar or procedure filename may route a document role but may not establish its year or any fact. "
                "This gate requires exactly one previously verified contest_session_year field-evidence record for the expected year before "
                "it can read sibling document targets from the same first-party contest page."
            ),
        }

    for item in selected:
        parent = item["parent"]
        binding = item["binding"]
        role = item["document_role"]
        base = {
            "signal_id": parent.get("signal_id"),
            "parent_evidence_id": parent.get("evidence_id"),
            "parent_label": parent.get("label"),
            "document_label": binding.get("label"),
            "document_role": role,
            "target_class": binding.get("target_class"),
            "resource_id": binding.get("resource_id"),
            "target_identity_verified": True,
            **context,
            "context_binding_method": "verified_contest_session_field_evidence_plus_same_parent_document_target",
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "deadline_verified": False,
            "calendar_verified": False,
            "event_time_verified": False,
        }
        if not allow_network:
            rows.append(
                {
                    **base,
                    "state": "BLOCKED",
                    "reason": "network_read_not_enabled",
                    "content_fetch_attempted": False,
                }
            )
            continue
        try:
            request_url = _download_url(binding)
            body, final_url, content_type = (fetcher or _fetch_document)(request_url)
            from urllib.parse import urlsplit

            final_host = (urlsplit(final_url).hostname or "").lower()
            if not _allowed_final_host(final_host):
                raise RuntimeError("document_redirect_host_not_allowlisted")
            container = _validate_document_bytes(body, content_type)
            import hashlib

            sha = hashlib.sha256(body).hexdigest()
            common = {
                **base,
                "content_fetch_attempted": True,
                "content_verified": True,
                "content_type": content_type,
                "content_container": container,
                "content_length": len(body),
                "content_sha256": sha,
                "document_content_evidence_id": f"isj-context-document-{sha[:24]}",
                "final_host": final_host,
                "raw_bytes_persisted": False,
            }
            if container != "PDF":
                rows.append(
                    {
                        **common,
                        "state": "DOCUMENT_CONTENT_CAPTURED_SHADOW",
                        "reason": "context_document_bytes_verified_non_pdf_text_extraction_not_enabled",
                        "text_extracted": False,
                    }
                )
                continue
            extraction = _validate_extraction_result((extractor or _extract_pdf_text)(body))
            text_sha = str(extraction["normalized_text_sha256"])
            rows.append(
                {
                    **common,
                    "state": "DOCUMENT_TEXT_EXTRACTED_SHADOW",
                    "reason": "context_document_pdf_text_extracted_with_verified_contest_context_non_authorizing",
                    "text_extracted": True,
                    "document_text_evidence_id": f"isj-context-document-text-{text_sha[:24]}",
                    "normalized_text_sha256": text_sha,
                    "page_count_observed": extraction.get("page_count_observed"),
                    "nonempty_page_count": extraction.get("nonempty_page_count"),
                    "nonempty_char_count": extraction.get("nonempty_char_count"),
                    "text_normalization": extraction.get("normalization"),
                    "extractor_provenance": extraction.get("extractor_provenance"),
                    "pages": extraction.get("pages"),
                    "normalized_text": extraction.get("normalized_text"),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    **base,
                    "state": "BLOCKED",
                    "reason": "context_document_fetch_validation_or_text_extraction_failed",
                    "content_fetch_attempted": True,
                    "content_verified": False,
                    "text_extracted": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:400],
                }
            )

    return {
        "schema_version": "1.0",
        "mode": "ISJ_CONTEXT_DOCUMENTS_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "network_read_enabled": allow_network,
        "contest_context_verified": True,
        "expected_contest_session_year": expected_year,
        **context,
        "selected_context_document_count": len(selected),
        "document_content_captured_shadow_count": sum(
            row.get("state") in {"DOCUMENT_CONTENT_CAPTURED_SHADOW", "DOCUMENT_TEXT_EXTRACTED_SHADOW"}
            for row in rows
        ),
        "document_text_extracted_shadow_count": sum(
            row.get("state") == "DOCUMENT_TEXT_EXTRACTED_SHADOW" for row in rows
        ),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "selected_roles": sorted({str(row.get("document_role")) for row in rows if row.get("document_role")}),
        "rows": rows,
        "truth_rule": (
            "Filename semantics may only route registration/calendar/procedure document roles. The contest year comes exclusively from a "
            "previously verified contest_session_year field_evidence_id. Exact deadlines, calendar dates and event times remain unverified "
            "until a later field-level gate binds values to verified document text and page hashes. No FactKernel or writer promotion occurs here."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind ISJ registration/calendar/procedure documents to verified contest context and capture their content read-only"
    )
    parser.add_argument("--targets", required=True)
    parser.add_argument("--fields", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    target_report = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    field_report = json.loads(Path(args.fields).read_text(encoding="utf-8"))
    result = capture_context_documents(
        target_report,
        field_report,
        allow_network=args.live,
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "contest_context_verified": result["contest_context_verified"],
                "selected_context_document_count": result["selected_context_document_count"],
                "document_text_extracted_shadow_count": result["document_text_extracted_shadow_count"],
                "blocked_count": result["blocked_count"],
                "publication_authority": "NONE",
                "acceptance_ready": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
