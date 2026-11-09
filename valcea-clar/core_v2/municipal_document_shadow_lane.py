from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import ssl
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPSHandler, Request, build_opener
from zoneinfo import ZoneInfo

from municipal_reference_shadow_lane import (
    EXPANDED_INDEX_URL,
    _live_state as live_reference_state,
    _validate_expanded_index_url,
    verify_state as verify_reference_state,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"
MAX_LATEST_DOCUMENTS = 5
OFFICIAL_HOST = "dm.primariavl.ro"
OFFICIAL_PATH_PREFIX = "/dm/2026/hotarari.nsf/"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _evidence_id(document_sha: str, kind: str, excerpt: str) -> str:
    payload = f"{document_sha}|{kind}|{_normalize(excerpt)}"
    return "municipal-document:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "").strip()))


def _validate_official_document_url(value: Any) -> str:
    """Accept only bounded first-party 2026 HCL DocManager document URLs."""
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != OFFICIAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not parsed.path.startswith(OFFICIAL_PATH_PREFIX)
        or parsed.fragment
    ):
        raise ValueError("official municipal document URL escaped bounded first-party surface")
    return urlunsplit(("https", OFFICIAL_HOST, parsed.path, parsed.query, ""))


def _valid_decision_identity(number: Any, decision_date: Any) -> bool:
    try:
        parsed = date.fromisoformat(str(decision_date or ""))
        numeric = int(number or 0)
    except (TypeError, ValueError):
        return False
    return numeric > 0 and parsed.year == 2026


def materialize_document_evidence(document: dict[str, Any]) -> dict[str, Any]:
    """Convert a resolved official HCL document into non-authorizing evidence rows.

    The legacy resolver is reusable only as a transport/parser component. Core v2
    independently revalidates document identity boundaries before accepting any
    excerpt as evidence. No evidence row is a FactKernel claim by itself.
    """
    if not document.get("resolved"):
        return {
            "decision_number": document.get("decision_number"),
            "decision_date": document.get("decision_date"),
            "state": "BLOCKED",
            "reason": str(document.get("reason") or "official_document_not_resolved"),
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "evidence": [],
        }

    number = document.get("decision_number")
    decision_date = document.get("decision_date")
    if not _valid_decision_identity(number, decision_date):
        return {
            "decision_number": number,
            "decision_date": decision_date,
            "state": "BLOCKED",
            "reason": "resolved_document_invalid_decision_identity",
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "evidence": [],
        }

    try:
        official_url = _validate_official_document_url(document.get("official_html_url"))
    except (TypeError, ValueError):
        return {
            "decision_number": number,
            "decision_date": decision_date,
            "state": "BLOCKED",
            "reason": "resolved_document_off_surface_url",
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "evidence": [],
        }

    source_sha = str(document.get("source_sha256") or "").strip().lower()
    text_sha = str(document.get("document_text_sha256") or "").strip().lower()
    if not _is_sha256(source_sha) or not _is_sha256(text_sha):
        return {
            "decision_number": number,
            "decision_date": decision_date,
            "state": "BLOCKED",
            "reason": "resolved_document_invalid_identity_hashes",
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "evidence": [],
        }

    evidence: list[dict[str, Any]] = []
    fields = (
        ("OPERATIVE_ARTICLE", "operative_articles"),
        ("VOTE_CONTEXT", "vote_snippets"),
        ("MONEY_CONTEXT", "money_snippets"),
        ("PROCUREMENT_CONTEXT", "procurement_snippets"),
        ("PROJECT_CONTEXT", "project_snippets"),
        ("ENTITY_CONTEXT", "entity_snippets"),
    )
    for kind, field in fields:
        for raw in document.get(field) or []:
            excerpt = _normalize(raw)
            if not excerpt:
                continue
            evidence.append(
                {
                    "evidence_id": _evidence_id(text_sha, kind, excerpt),
                    "kind": kind,
                    "excerpt": excerpt,
                    "source_url": official_url,
                    "source_sha256": source_sha,
                    "document_text_sha256": text_sha,
                    "epistemic_status": "FIRST_PARTY_DOCUMENT_TEXT",
                    "material_fact_status": "UNADJUDICATED",
                }
            )

    operative_count = sum(row["kind"] == "OPERATIVE_ARTICLE" for row in evidence)
    if operative_count == 0:
        return {
            "decision_number": number,
            "decision_date": decision_date,
            "state": "BLOCKED",
            "reason": "resolved_document_without_operative_article_evidence",
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "evidence": evidence,
        }

    return {
        "decision_number": int(number or 0),
        "decision_date": str(decision_date or ""),
        "registered_title": document.get("registered_title"),
        "state": "DOCUMENT_EVIDENCE_READY",
        "reason": "official_document_identity_and_operative_articles_verified",
        "official_html_url": official_url,
        "http_status": document.get("http_status"),
        "source_sha256": source_sha,
        "document_text_sha256": text_sha,
        "document_unid": document.get("document_unid"),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "operative_article_count": operative_count,
        "truth_note": (
            "This row proves bounded first-party document text only. Evidence is not yet a material FactKernel claim, "
            "does not establish current implementation beyond the adopted decision text, and cannot publish an article."
        ),
    }


def _fetch_register_html() -> tuple[str, str]:
    sys.path.insert(0, str(SCRIPTS))
    adapter = importlib.import_module("ramnicu_valcea_local_council_decision_reference_adapter")
    transport_url = _validate_expanded_index_url(EXPANDED_INDEX_URL)
    opener = build_opener(adapter.NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        transport_url,
        headers={"User-Agent": adapter.USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Cache-Control": "no-cache"},
    )
    with opener.open(request, timeout=adapter.TIMEOUT_SECONDS) as response:
        final_url = _validate_expanded_index_url(response.geturl())
        if final_url != transport_url:
            raise ValueError("municipal register drift after fetch")
        content_type = str(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML municipal register refused: {content_type or 'unknown'}")
        payload = response.read(adapter.MAX_RESPONSE_BYTES + 1)
        if len(payload) > adapter.MAX_RESPONSE_BYTES:
            raise ValueError("municipal register exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return transport_url, payload.decode(charset, errors="replace")


def collect_live(*, as_of: date | None = None, limit: int = MAX_LATEST_DOCUMENTS) -> dict[str, Any]:
    as_of = as_of or _today_bucharest()
    if limit < 1 or limit > MAX_LATEST_DOCUMENTS:
        raise ValueError(f"limit must be between 1 and {MAX_LATEST_DOCUMENTS}")

    raw_refs = live_reference_state(as_of=as_of)
    reference_result = verify_reference_state(raw_refs, as_of=as_of)
    if reference_result.get("status") != "PASS_SHADOW" or not reference_result.get("rows"):
        return {
            "schema_version": "1.1",
            "mode": "MUNICIPAL_DOCUMENT_EVIDENCE_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "status": "BLOCKED_REFERENCE_DISCOVERY",
            "reason": reference_result.get("reason") or reference_result.get("status"),
            "rows": [],
        }

    refs = [row for row in raw_refs.get("references") or [] if isinstance(row, dict) and row.get("decision_date")]
    latest_date = max(str(row["decision_date"]) for row in refs)
    selected = [row for row in refs if str(row.get("decision_date")) == latest_date]
    selected.sort(key=lambda row: int(row.get("decision_number") or 0), reverse=True)
    selected = selected[:limit]

    sys.path.insert(0, str(SCRIPTS))
    resolver = importlib.import_module("council_decision_document_resolver")
    row_resolver = importlib.import_module("council_docmanager_row_resolver")
    transport_url, register_html = _fetch_register_html()
    requested = [
        {
            "decision_number": int(row.get("decision_number") or 0),
            "decision_date": str(row.get("decision_date") or ""),
            "title": str(row.get("title_hint") or ""),
        }
        for row in selected
    ]
    mapping = row_resolver.structural_decision_attachments(transport_url, register_html, requested)

    rows: list[dict[str, Any]] = []
    for requested_row in requested:
        number = int(requested_row["decision_number"])
        candidate = mapping.get(number)
        if not candidate:
            rows.append(
                {
                    "decision_number": number,
                    "decision_date": requested_row["decision_date"],
                    "registered_title": requested_row["title"],
                    "state": "BLOCKED",
                    "reason": "row_document_url_not_resolved",
                    "publication_authority": "NONE",
                    "fact_kernel_promotion_allowed": False,
                    "writer_allowed": False,
                    "evidence": [],
                }
            )
            continue
        try:
            _validate_official_document_url(candidate)
        except ValueError:
            rows.append(
                {
                    "decision_number": number,
                    "decision_date": requested_row["decision_date"],
                    "registered_title": requested_row["title"],
                    "state": "BLOCKED",
                    "reason": "row_document_url_off_surface",
                    "publication_authority": "NONE",
                    "fact_kernel_promotion_allowed": False,
                    "writer_allowed": False,
                    "evidence": [],
                }
            )
            continue
        document = resolver.extract_document(requested_row, candidate)
        rows.append(materialize_document_evidence(document))

    ready = sum(row.get("state") == "DOCUMENT_EVIDENCE_READY" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    return {
        "schema_version": "1.1",
        "mode": "MUNICIPAL_DOCUMENT_EVIDENCE_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "status": "PASS_SHADOW",
        "latest_official_adopted_date": latest_date,
        "reference_count": int(reference_result.get("reference_count") or 0),
        "selected_document_count": len(requested),
        "row_urls_resolved": len(mapping),
        "document_evidence_ready_count": ready,
        "blocked_count": blocked,
        "fabricated_claim_count": 0,
        "rows": rows,
        "truth_rule": (
            "The collector may resolve only bounded same-host official HCL document bodies for the latest deterministic adopted-decision date. "
            "It independently revalidates URL, decision identity and SHA-256 evidence boundaries after the legacy resolver. "
            "It produces evidence rows only; material FactKernel promotion, writer use, persistence and publication remain forbidden."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect latest official municipal HCL body evidence in read-only shadow mode")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=MAX_LATEST_DOCUMENTS)
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("only --live read-only shadow collection is supported")
    try:
        result = collect_live(limit=args.limit)
    except Exception as exc:
        result = {
            "schema_version": "1.1",
            "mode": "MUNICIPAL_DOCUMENT_EVIDENCE_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "latest_official_adopted_date": result.get("latest_official_adopted_date"),
        "reference_count": result.get("reference_count", 0),
        "selected_document_count": result.get("selected_document_count", 0),
        "row_urls_resolved": result.get("row_urls_resolved", 0),
        "document_evidence_ready_count": result.get("document_evidence_ready_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
