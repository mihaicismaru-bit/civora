from __future__ import annotations

import argparse
import hashlib
import json
import ssl
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_ROWS = 4
MAX_DOCUMENTS = 4
MAX_BYTES = 12_000_000
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


def capture_verified_document_contents(
    target_report: dict[str, Any],
    *,
    allow_network: bool,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
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
            rows.append({
                **base,
                "state": "DOCUMENT_CONTENT_CAPTURED_SHADOW",
                "reason": "document_bytes_captured_and_identity_preserved_non_authorizing",
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
                "text_extracted": False,
                "field_extraction_allowed": False,
            })
        except Exception as exc:
            rows.append({
                **base,
                "state": "BLOCKED",
                "reason": "document_content_fetch_or_validation_failed",
                "content_fetch_attempted": True,
                "content_verified": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    return {
        "schema_version": "1.0",
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
        "document_content_captured_shadow_count": sum(row.get("state") == "DOCUMENT_CONTENT_CAPTURED_SHADOW" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": "A trusted document target identity permits only bounded read-only byte capture. Captured bytes must pass HTTPS final-host, content-type, size and file-magic checks. Byte capture alone authorizes no field, deadline, vacancy count, FactKernel, article, site publication or social distribution. No document bytes are persisted by this gate; only cryptographic evidence metadata is emitted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture bytes from verified ISJ embedded document identities without promoting facts")
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
        "blocked_count": result["blocked_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
