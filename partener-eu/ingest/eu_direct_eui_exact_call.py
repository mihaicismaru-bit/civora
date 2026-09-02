#!/usr/bin/env python3
"""Exact official evidence for one European Urban Initiative call.

This bounded adapter starts from the official Portico call index, follows the
exact EUI call detail URL, binds the English Terms of Reference document, and
extracts current call-state candidates from the exact official detail page.
It is acquisition-only: no status, deadline, budget, eligibility, publication,
distribution, alert, or corpus mutation is authorized here.

Call 4 intentionally has no fabricated formal call/topic identifier. Its
identity is bound by the exact official detail URL + official page title +
linked Terms of Reference URL. Therefore an OPEN candidate can never satisfy
the PARTENER.EU OPEN gate unless a separate official identifier is supplied by
an authoritative source in a later bounded implementation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SCHEMA = "PARTENER_EU_EUI_EXACT_CALL_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_EUI_EXACT_CALL_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "EUROPEAN_URBAN_INITIATIVE"
AUTHORITY_CLASS = "EUI_EXACT_CALL_DETAIL_AND_TOR"
OBSERVATION_LAYER = "EXACT_CURRENT_CALL_NON_AUTHORIZING"

DEFAULT_DISCOVERY_URL = "https://portico.urban-initiative.eu/urban-panorama/call-for-proposals"
DEFAULT_CALL_URL = "https://www.urban-initiative.eu/calls-proposals/fourth-call-proposals-innovative-actions"
EXPECTED_TITLE = "Fourth Call for Proposals EUI - Innovative Actions"
EXPECTED_SLUG = "fourth-call-proposals-innovative-actions"
TOR_PATH_MARKER = "00_EN_ToR_4th%20EUI-IA%20Call%20for%20Proposals.pdf"

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)


class ExactEUIEvidenceError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _validate_url(url: str, *, host: str, path_prefix: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        raise ExactEUIEvidenceError(f"non-HTTPS EUI authority URL: {url!r}")
    if (parsed.hostname or "").casefold() != host.casefold():
        raise ExactEUIEvidenceError(f"unexpected EUI authority host: {parsed.hostname!r}")
    if not (parsed.path or "/").startswith(path_prefix):
        raise ExactEUIEvidenceError(f"EUI authority path outside bounded allowlist: {parsed.path!r}")
    return url


def _normalise_text(raw: bytes) -> str:
    text = html.unescape(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _http_fetch(url: str, *, timeout: float = 20.0, accept: str = "text/html,*/*;q=0.1") -> tuple[bytes, int, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-EUIExactCall/1.0 (+https://partener.eu)",
            "Accept": accept,
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        status = int(getattr(response, "status", 200))
        final_url = str(response.geturl())
        content_type = str(response.headers.get("Content-Type", ""))
    return raw, status, final_url, content_type


def _receipt(*, requested_url: str, raw: bytes | None, status: int | None, final_url: str | None,
             content_type: str | None, health_state: str, error: str | None = None) -> dict[str, Any]:
    return {
        "health_state": health_state,
        "lkg_required": health_state != "HEALTHY",
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "error": error,
    }


def _safe_fetch(
    url: str,
    *,
    fetcher: Callable[..., tuple[bytes, int, str, str]],
    timeout: float,
    accept: str,
    host: str,
    path_prefix: str,
) -> tuple[bytes | None, dict[str, Any]]:
    _validate_url(url, host=host, path_prefix=path_prefix)
    try:
        raw, status, final_url, content_type = fetcher(url, timeout=timeout, accept=accept)
        _validate_url(final_url, host=host, path_prefix=path_prefix)
        if status != 200:
            return raw, _receipt(
                requested_url=url, raw=raw, status=status, final_url=final_url, content_type=content_type,
                health_state="DEGRADED_HTTP", error=f"unexpected HTTP status {status}",
            )
        return raw, _receipt(
            requested_url=url, raw=raw, status=status, final_url=final_url, content_type=content_type,
            health_state="HEALTHY",
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return None, _receipt(
            requested_url=url, raw=None, status=getattr(exc, "code", None), final_url=None, content_type=None,
            health_state="DEGRADED_TRANSPORT", error=f"{type(exc).__name__}: {exc}",
        )


def _extract_detail_link(discovery_raw: bytes, *, call_url: str) -> bool:
    decoded = html.unescape(discovery_raw.decode("utf-8", errors="ignore"))
    target_path = urlparse(call_url).path
    return EXPECTED_TITLE.casefold() in _normalise_text(discovery_raw).casefold() and target_path in decoded


def _extract_tor_url(detail_raw: bytes, *, call_url: str) -> str | None:
    decoded = html.unescape(detail_raw.decode("utf-8", errors="ignore"))
    candidates = re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", decoded, flags=re.I)
    for href in candidates:
        absolute = urljoin(call_url, href)
        parsed = urlparse(absolute)
        if (parsed.hostname or "").casefold() != "www.urban-initiative.eu":
            continue
        path = parsed.path or ""
        if "00_EN_ToR_4th" in path and "EUI-IA" in path and path.lower().endswith("proposals.pdf"):
            return absolute
    # Some renderers expose URL-escaped href text in JSON/script fragments rather than a normal href.
    marker = "/sites/default/files/2026-02/" + TOR_PATH_MARKER
    if marker in decoded:
        return "https://www.urban-initiative.eu" + marker
    return None


def _status_from_text(text: str) -> tuple[str, str]:
    folded = text.casefold()
    if "the call for proposals is closed" in folded or re.search(r"\bclosed\b", folded):
        return "CLOSED_CALL", "Closed"
    if "the call for proposals is open" in folded or re.search(r"\bopen\b", folded):
        return "OPEN_CALL", "Open"
    if re.search(r"\bupcoming\b|\bforthcoming\b", folded):
        return "FORTHCOMING_CALL", "Forthcoming"
    return "UNKNOWN", "Unknown"


def _detail_semantics(detail_raw: bytes, *, call_url: str, tor_url: str | None) -> dict[str, Any]:
    text = _normalise_text(detail_raw)
    folded = text.casefold()
    if EXPECTED_TITLE.casefold() not in folded:
        raise ExactEUIEvidenceError("exact EUI detail page lost expected Call 4 title")
    if "european urban initiative" not in folded and "eui" not in folded:
        raise ExactEUIEvidenceError("exact EUI detail page lost programme marker")
    candidate_state, status_label = _status_from_text(text)

    deadline = None
    if re.search(r"15\s+june\s+2026", text, flags=re.I) or "15/06/2026" in text:
        deadline = "2026-06-15T14:00:00+02:00" if re.search(r"14[.:]00\s+CEST", text, flags=re.I) else "2026-06-15"
    launch_date = "2026-02-25" if re.search(r"25\s+february\s+2026", text, flags=re.I) or "25/02/2026" in text else None
    budget = "EUR 60 million ERDF provisional" if re.search(r"60\s+million\s+ERDF", text, flags=re.I) else None

    return {
        "identity_scheme": "OFFICIAL_EXACT_URL_TITLE_AND_TOR_CHAIN",
        "identity_slug": EXPECTED_SLUG,
        "official_call_identifier": None,
        "title": EXPECTED_TITLE,
        "authority_url": call_url,
        "tor_url": tor_url,
        "candidate_state": candidate_state,
        "status_label": status_label,
        "launch_date_candidate": launch_date,
        "deadline_candidate": deadline,
        "budget_candidate": budget,
    }


def collect_exact(
    *,
    run_id: str,
    discovery_url: str = DEFAULT_DISCOVERY_URL,
    call_url: str = DEFAULT_CALL_URL,
    fetched_at: str | None = None,
    timeout: float = 20.0,
    output_dir: pathlib.Path | None = None,
    fetcher: Callable[..., tuple[bytes, int, str, str]] = _http_fetch,
) -> dict[str, Any]:
    fetched_at = fetched_at or utc_now()
    _validate_url(discovery_url, host="portico.urban-initiative.eu", path_prefix="/urban-panorama/call-for-proposals")
    _validate_url(call_url, host="www.urban-initiative.eu", path_prefix="/calls-proposals/")
    if urlparse(call_url).path.rstrip("/").split("/")[-1] != EXPECTED_SLUG:
        raise ExactEUIEvidenceError("bounded EUI exact adapter only accepts the official Call 4 detail slug")

    discovery_raw, discovery_receipt = _safe_fetch(
        discovery_url, fetcher=fetcher, timeout=timeout, accept="text/html,application/xhtml+xml,*/*;q=0.1",
        host="portico.urban-initiative.eu", path_prefix="/urban-panorama/call-for-proposals",
    )
    detail_raw, detail_receipt = _safe_fetch(
        call_url, fetcher=fetcher, timeout=timeout, accept="text/html,application/xhtml+xml,*/*;q=0.1",
        host="www.urban-initiative.eu", path_prefix="/calls-proposals/",
    )

    discovery_link_verified = bool(
        discovery_raw is not None and discovery_receipt["health_state"] == "HEALTHY"
        and _extract_detail_link(discovery_raw, call_url=call_url)
    )
    if discovery_receipt["health_state"] == "HEALTHY" and not discovery_link_verified:
        discovery_receipt = {**discovery_receipt, "health_state": "DEGRADED_MARKER_MISMATCH", "lkg_required": True,
                             "error": "Portico index no longer binds Call 4 title to exact detail path"}

    tor_url = _extract_tor_url(detail_raw or b"", call_url=call_url) if detail_raw else None
    semantics: dict[str, Any] | None = None
    if detail_raw is not None and detail_receipt["health_state"] == "HEALTHY":
        try:
            semantics = _detail_semantics(detail_raw, call_url=call_url, tor_url=tor_url)
        except ExactEUIEvidenceError as exc:
            detail_receipt = {**detail_receipt, "health_state": "DEGRADED_MARKER_MISMATCH", "lkg_required": True,
                              "error": str(exc)}

    tor_raw: bytes | None = None
    if tor_url:
        try:
            _validate_url(tor_url, host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-02/")
            tor_raw, tor_receipt = _safe_fetch(
                tor_url, fetcher=fetcher, timeout=timeout, accept="application/pdf,*/*;q=0.1",
                host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-02/",
            )
            if tor_receipt["health_state"] == "HEALTHY":
                content_type = str(tor_receipt.get("content_type") or "").casefold()
                if tor_raw is None or not tor_raw.startswith(b"%PDF") or len(tor_raw) < 1000 or "pdf" not in content_type:
                    tor_receipt = {**tor_receipt, "health_state": "DEGRADED_MARKER_MISMATCH", "lkg_required": True,
                                   "error": "linked Terms of Reference did not validate as a PDF"}
        except ExactEUIEvidenceError as exc:
            tor_receipt = _receipt(
                requested_url=tor_url, raw=None, status=None, final_url=None, content_type=None,
                health_state="DEGRADED_TRANSPORT", error=str(exc),
            )
    else:
        tor_receipt = _receipt(
            requested_url="UNRESOLVED_FROM_EXACT_DETAIL", raw=None, status=None, final_url=None, content_type=None,
            health_state="DEGRADED_MARKER_MISMATCH", error="exact EUI detail page did not expose the English Call 4 Terms of Reference",
        )

    all_receipts = [discovery_receipt, detail_receipt, tor_receipt]
    healthy = all(r.get("health_state") == "HEALTHY" for r in all_receipts)
    source_health_state = "HEALTHY" if healthy and discovery_link_verified and semantics else "DEGRADED"
    lkg_required = source_health_state != "HEALTHY"

    exact_semantics = semantics or {
        "identity_scheme": "OFFICIAL_EXACT_URL_TITLE_AND_TOR_CHAIN",
        "identity_slug": EXPECTED_SLUG,
        "official_call_identifier": None,
        "title": EXPECTED_TITLE,
        "authority_url": call_url,
        "tor_url": tor_url,
        "candidate_state": "UNKNOWN",
        "status_label": "Unknown",
        "launch_date_candidate": None,
        "deadline_candidate": None,
        "budget_candidate": None,
    }
    identity_basis = {
        "identity_scheme": exact_semantics["identity_scheme"],
        "identity_slug": exact_semantics["identity_slug"],
        "title": exact_semantics["title"],
        "authority_url": exact_semantics["authority_url"],
        "tor_url": exact_semantics.get("tor_url"),
    }
    identity_key = sha256_json(identity_basis)

    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "discovery_url": discovery_url,
        "authority_url": call_url,
        "tor_url": tor_url,
        "discovery_link_verified": discovery_link_verified,
        "identity_key": identity_key,
        "identity_scheme": exact_semantics["identity_scheme"],
        "identity_slug": exact_semantics["identity_slug"],
        "official_call_identifier": None,
        "title": exact_semantics["title"],
        "candidate_state": exact_semantics["candidate_state"],
        "status_label": exact_semantics["status_label"],
        "deadline_candidate": exact_semantics["deadline_candidate"],
        "budget_candidate": exact_semantics["budget_candidate"],
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "source_health_state": source_health_state,
        "lkg_required": lkg_required,
        "source_receipts": {
            "portico_call_index": discovery_receipt,
            "exact_call_detail": detail_receipt,
            "terms_of_reference": tor_receipt,
        },
        "tor_raw_sha256": sha256_bytes(tor_raw) if tor_raw is not None else None,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "missing_for_open_confirmation": [
            "official_call_or_topic_identifier",
            "field_scoped_material_admission",
        ],
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        if discovery_raw is not None:
            (output_dir / "eui-portico-call-index.html").write_bytes(discovery_raw)
        if detail_raw is not None:
            (output_dir / "eui-call4-detail.html").write_bytes(detail_raw)
        if tor_raw is not None:
            (output_dir / "eui-call4-terms-of-reference.pdf").write_bytes(tor_raw)
        (output_dir / "eui-call4-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ExactEUIEvidenceError("EUI exact evidence schema/parser drift")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ExactEUIEvidenceError("EUI exact evidence family drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS or evidence.get("observation_state") != OBSERVATION_LAYER:
        raise ExactEUIEvidenceError("EUI exact authority/observation drift")
    _validate_url(str(evidence.get("discovery_url") or ""), host="portico.urban-initiative.eu", path_prefix="/urban-panorama/call-for-proposals")
    _validate_url(str(evidence.get("authority_url") or ""), host="www.urban-initiative.eu", path_prefix="/calls-proposals/")
    if evidence.get("identity_slug") != EXPECTED_SLUG or evidence.get("title") != EXPECTED_TITLE:
        raise ExactEUIEvidenceError("EUI exact Call 4 identity drift")
    if evidence.get("official_call_identifier") is not None:
        raise ExactEUIEvidenceError("EUI exact evidence fabricated an official identifier")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ExactEUIEvidenceError("EUI exact semantic fingerprint mismatch")
    identity_basis = {
        "identity_scheme": semantics.get("identity_scheme"),
        "identity_slug": semantics.get("identity_slug"),
        "title": semantics.get("title"),
        "authority_url": semantics.get("authority_url"),
        "tor_url": semantics.get("tor_url"),
    }
    if sha256_json(identity_basis) != evidence.get("identity_key"):
        raise ExactEUIEvidenceError("EUI exact identity fingerprint mismatch")
    if evidence.get("candidate_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ExactEUIEvidenceError("EUI exact candidate state unsupported")
    if evidence.get("source_health_state") == "HEALTHY":
        if evidence.get("discovery_link_verified") is not True or evidence.get("lkg_required") is not False:
            raise ExactEUIEvidenceError("healthy EUI exact chain lost discovery/detail binding")
        tor_url = str(evidence.get("tor_url") or "")
        _validate_url(tor_url, host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-02/")
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("tor_raw_sha256") or "")):
            raise ExactEUIEvidenceError("healthy EUI exact chain lost Terms-of-Reference hash")
        for receipt in (evidence.get("source_receipts") or {}).values():
            if receipt.get("health_state") != "HEALTHY" or receipt.get("http_status") != 200:
                raise ExactEUIEvidenceError("healthy aggregate contains degraded EUI source receipt")
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("raw_sha256") or "")):
                raise ExactEUIEvidenceError("healthy EUI source receipt lacks raw hash")
    else:
        if evidence.get("lkg_required") is not True:
            raise ExactEUIEvidenceError("degraded EUI exact chain did not require LKG/reference handling")
    if "official_call_or_topic_identifier" not in set(evidence.get("missing_for_open_confirmation") or []):
        raise ExactEUIEvidenceError("EUI exact evidence relaxed OPEN identifier requirement")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ExactEUIEvidenceError(f"EUI exact evidence attempted authorization: {key}")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ExactEUIEvidenceError("EUI exact evidence skipped downstream gates")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ExactEUIEvidenceError("EUI exact evidence crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--discovery-url", default=DEFAULT_DISCOVERY_URL)
    parser.add_argument("--call-url", default=DEFAULT_CALL_URL)
    parser.add_argument("--fetched-at")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    evidence = collect_exact(
        run_id=args.run_id,
        discovery_url=args.discovery_url,
        call_url=args.call_url,
        fetched_at=args.fetched_at,
        timeout=args.timeout,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "identity_slug": evidence["identity_slug"],
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "deadline_candidate": evidence["deadline_candidate"],
        "official_call_identifier": evidence["official_call_identifier"],
        "open_call_authorized": evidence["open_call_authorized"],
        "closed_call_authorized": evidence["closed_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
