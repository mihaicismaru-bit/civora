from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import ssl
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_ROWS = 4
MAX_DOCUMENTS = 4
MAX_BYTES = 12_000_000
MAX_EXTRACTED_TEXT_CHARS = 2_000_000
MIN_EXTRACTED_TEXT_CHARS = 40
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _download_url(binding: dict[str, Any]) -> str:
    target_class = str(binding.get("target_class") or "")
    resource_id = str(binding.get("resource_id") or "").strip()
    if not resource_id:
        raise ValueError("resource_id_missing")
    if target_class in {"GOOGLE_DRIVE_FILE", "GOOGLE_DRIVE_CONTENT"}:
        return "https://drive.usercontent.google.com/download?" + urlencode(
            {"id": resource_id, "export": "download", "confirm": "t"}
        )
    if target_class == "GOOGLE_DOCUMENT":
        return f"https://docs.google.com/document/d/{resource_id}/export?format=pdf"
    if target_class == "GOOGLE_PRESENTATION":
        return f"https://docs.google.com/presentation/d/{resource_id}/export/pdf"
    if target_class == "GOOGLE_SPREADSHEETS":
        return f"https://docs.google.com/spreadsheets/d/{resource_id}/export?format=xlsx"
    if target_class == "FIRST_PARTY_DOCUMENT":
        url = str(binding.get("target_url") or "")
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in {"isjvalcea.ro", "www.isjvalcea.ro"}:
            raise ValueError("first_party_document_identity_invalid")
        return url
    raise ValueError("unsupported_target_class")


def _allowed_final_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host in {
        "isjvalcea.ro",
        "www.isjvalcea.ro",
        "drive.google.com",
        "drive.usercontent.google.com",
        "docs.google.com",
    } or host.endswith(".googleusercontent.com")


def _validate_document_bytes(body: bytes, content_type: str) -> str:
    if not body:
        raise RuntimeError("document_body_empty")
    if len(body) > MAX_BYTES:
        raise RuntimeError("document_body_too_large")
    ctype = content_type.lower().split(";", 1)[0].strip()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise RuntimeError(f"document_content_type_not_allowlisted:{ctype or 'missing'}")
    if body.startswith(b"%PDF-"):
        return "PDF"
    if body.startswith(b"PK\x03\x04"):
        return "ZIP_OFFICE_CONTAINER"
    if ctype == "application/msword":
        return "LEGACY_WORD_BINARY"
    if ctype == "application/vnd.ms-excel":
        return "LEGACY_EXCEL_BINARY"
    if ctype == "application/octet-stream":
        raise RuntimeError("octet_stream_magic_unrecognized")
    raise RuntimeError("document_magic_not_recognized")


def _fetch_document(url: str, timeout: float = 25.0) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": "CIVORA-Valcea-Clar-Core-v2-ISJ-ReadOnly/1.0"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = str(response.geturl() or "")
        final = urlsplit(final_url)
        if final.scheme != "https" or not _allowed_final_host(final.hostname or ""):
            raise RuntimeError("document_redirect_host_not_allowlisted")
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"document_http_status:{getattr(response, 'status', 0)}")
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise RuntimeError("document_body_too_large")
        return body, final_url, content_type


def _normalize_pdf_text(raw_text: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFC", raw_text.replace("\r\n", "\n").replace("\r", "\n"))
    raw_pages = text.split("\f")
    pages: list[dict[str, Any]] = []
    normalized_pages: list[str] = []
    nonempty_chars = 0
    for page_number, raw_page in enumerate(raw_pages, start=1):
        lines = [line.rstrip() for line in raw_page.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        normalized = "\n".join(lines)
        normalized_pages.append(normalized)
        if not normalized.strip():
            continue
        nonempty_chars += len(normalized)
        pages.append({
            "page_number": page_number,
            "text": normalized,
            "text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "char_count": len(normalized),
        })
    joined = "\f".join(normalized_pages)
    if len(joined) > MAX_EXTRACTED_TEXT_CHARS:
        raise RuntimeError("pdf_text_too_large")
    if nonempty_chars < MIN_EXTRACTED_TEXT_CHARS:
        raise RuntimeError("pdf_text_empty_or_too_short")
    return {
        "normalized_text": joined,
        "normalized_text_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "page_count_observed": len(raw_pages),
        "nonempty_page_count": len(pages),
        "nonempty_char_count": nonempty_chars,
        "pages": pages,
        "normalization": "unicode_nfc+lf+rstrip_lines+trim_outer_blank_lines+formfeed_page_boundaries",
    }


def _extract_pdf_text(body: bytes, timeout: float = 30.0) -> dict[str, Any]:
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("pdftotext_not_available")
    version_run = subprocess.run(
        [executable, "-v"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=5,
        check=False,
    )
    version_lines = [line.strip() for line in (version_run.stdout or "").splitlines() if line.strip()]
    version = version_lines[0][:240] if version_lines else "pdftotext-version-unavailable"
    flags = ["-layout", "-enc", "UTF-8", "-eol", "unix"]
    with tempfile.TemporaryDirectory(prefix="civora-isj-pdf-") as temp_dir:
        input_path = Path(temp_dir) / "input.pdf"
        output_path = Path(temp_dir) / "output.txt"
        input_path.write_bytes(body)
        completed = subprocess.run(
            [executable, *flags, str(input_path), str(output_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"pdftotext_failed:{completed.returncode}:{(completed.stderr or '')[:240]}")
        if not output_path.is_file():
            raise RuntimeError("pdftotext_output_missing")
        raw_text = output_path.read_text(encoding="utf-8", errors="strict")
    normalized = _normalize_pdf_text(raw_text)
    return {
        **normalized,
        "extractor_provenance": {
            "name": "poppler_pdftotext",
            "executable_basename": Path(executable).name,
            "version": version,
            "args": flags,
            "timeout_seconds": timeout,
            "shell": False,
            "ocr_used": False,
        },
    }


def _validate_extraction_result(extraction: dict[str, Any]) -> dict[str, Any]:
    normalized_text = str(extraction.get("normalized_text") or "")
    pages = extraction.get("pages") or []
    provenance = extraction.get("extractor_provenance") or {}
    if len(normalized_text) > MAX_EXTRACTED_TEXT_CHARS:
        raise RuntimeError("pdf_text_too_large")
    if len(normalized_text.strip()) < MIN_EXTRACTED_TEXT_CHARS:
        raise RuntimeError("pdf_text_empty_or_too_short")
    if not isinstance(pages, list) or not pages:
        raise RuntimeError("pdf_text_pages_missing")
    if not isinstance(provenance, dict) or not str(provenance.get("name") or "").strip():
        raise RuntimeError("pdf_text_extractor_provenance_missing")
    expected_sha = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    if extraction.get("normalized_text_sha256") and extraction.get("normalized_text_sha256") != expected_sha:
        raise RuntimeError("pdf_text_sha256_mismatch")
    return {**extraction, "normalized_text_sha256": expected_sha}


def capture_verified_document_contents(
    target_report: dict[str, Any],
    *,
    allow_network: bool,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
    extractor: Callable[[bytes], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if str(target_report.get("publication_authority") or "NONE") != "NONE":
        raise ValueError("target_report_publication_boundary_violation")
    if target_report.get("fact_kernel_promotion_allowed") is True or target_report.get("writer_allowed") is True:
        raise ValueError("target_report_promotion_boundary_violation")

    rows: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for parent in (target_report.get("rows") or [])[:MAX_ROWS]:
        if not isinstance(parent, dict) or parent.get("state") != "EMBEDDED_TARGET_IDENTITY_SHADOW":
            continue
        for binding in parent.get("bindings") or []:
            if not isinstance(binding, dict):
                continue
            if binding.get("state") != "TARGET_IDENTITY_BOUND_SHADOW":
                continue
            if binding.get("target_identity_verified") is not True:
                continue
            if binding.get("current_year_label") is not True:
                continue
            if binding.get("future_content_fetch_eligible") is not True:
                continue
            selected.append({"parent": parent, "binding": binding})
            if len(selected) >= MAX_DOCUMENTS:
                break
        if len(selected) >= MAX_DOCUMENTS:
            break

    for selected_row in selected:
        parent = selected_row["parent"]
        binding = selected_row["binding"]
        base = {
            "signal_id": parent.get("signal_id"),
            "evidence_id": parent.get("evidence_id"),
            "topic_class": parent.get("topic_class"),
            "parent_label": parent.get("label"),
            "document_label": binding.get("label"),
            "target_class": binding.get("target_class"),
            "resource_id": binding.get("resource_id"),
            "target_identity_verified": True,
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "sensitive_result_projection_allowed": False,
            "field_extraction_allowed": False,
        }
        if not allow_network:
            rows.append({**base, "state": "BLOCKED", "reason": "network_read_not_enabled", "content_fetch_attempted": False})
            continue
        try:
            request_url = _download_url(binding)
            body, final_url, content_type = (fetcher or _fetch_document)(request_url)
            final_host = (urlsplit(final_url).hostname or "").lower()
            if not _allowed_final_host(final_host):
                raise RuntimeError("document_redirect_host_not_allowlisted")
            container = _validate_document_bytes(body, content_type)
            sha = hashlib.sha256(body).hexdigest()
            common = {
                **base,
                "content_fetch_attempted": True,
                "content_verified": True,
                "content_type": content_type,
                "content_container": container,
                "content_length": len(body),
                "content_sha256": sha,
                "document_content_evidence_id": f"isj-document-{sha[:24]}",
                "final_host": final_host,
                "request_identity": {
                    "target_class": binding.get("target_class"),
                    "resource_id": binding.get("resource_id"),
                },
                "raw_bytes_persisted": False,
            }
            if container != "PDF":
                rows.append({
                    **common,
                    "state": "DOCUMENT_CONTENT_CAPTURED_SHADOW",
                    "reason": "document_bytes_captured_non_pdf_text_extraction_not_enabled",
                    "text_extracted": False,
                })
                continue
            extraction = _validate_extraction_result((extractor or _extract_pdf_text)(body))
            normalized_text = str(extraction["normalized_text"])
            text_sha = str(extraction["normalized_text_sha256"])
            rows.append({
                **common,
                "state": "DOCUMENT_TEXT_EXTRACTED_SHADOW",
                "reason": "verified_pdf_text_extracted_with_auditable_extractor_provenance_non_authorizing",
                "text_extracted": True,
                "document_text_evidence_id": f"isj-document-text-{text_sha[:24]}",
                "normalized_text_sha256": text_sha,
                "page_count_observed": extraction.get("page_count_observed"),
                "nonempty_page_count": extraction.get("nonempty_page_count"),
                "nonempty_char_count": extraction.get("nonempty_char_count"),
                "text_normalization": extraction.get("normalization"),
                "extractor_provenance": extraction.get("extractor_provenance"),
                "pages": extraction.get("pages"),
                "normalized_text": normalized_text,
                "field_extraction_allowed": False,
            })
        except Exception as exc:
            rows.append({
                **base,
                "state": "BLOCKED",
                "reason": "document_content_fetch_validation_or_text_extraction_failed",
                "content_fetch_attempted": True,
                "content_verified": False,
                "text_extracted": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    return {
        "schema_version": "1.1",
        "mode": "ISJ_EMBEDDED_DOCUMENT_CONTENT_SHADOW",
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
        "selected_document_count": len(selected),
        "document_content_captured_shadow_count": sum(
            row.get("state") in {"DOCUMENT_CONTENT_CAPTURED_SHADOW", "DOCUMENT_TEXT_EXTRACTED_SHADOW"}
            for row in rows
        ),
        "document_text_extracted_shadow_count": sum(row.get("state") == "DOCUMENT_TEXT_EXTRACTED_SHADOW" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": "A trusted document target identity permits bounded read-only byte capture and, for verified PDFs only, deterministic text extraction with recorded extractor provenance. Extracted text remains non-authorizing: no deadline, vacancy count, calendar date, eligibility field, FactKernel, article, site publication or social distribution exists until a later field-level evidence gate binds exact text evidence. Raw document bytes are never persisted by this gate and OCR is not used.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and deterministically extract text from verified ISJ PDF identities without promoting facts")
    parser.add_argument("--targets", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    result = capture_verified_document_contents(targets, allow_network=args.live)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected_document_count": result["selected_document_count"],
        "document_content_captured_shadow_count": result["document_content_captured_shadow_count"],
        "document_text_extracted_shadow_count": result["document_text_extracted_shadow_count"],
        "blocked_count": result["blocked_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
