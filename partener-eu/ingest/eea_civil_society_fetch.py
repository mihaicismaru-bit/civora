#!/usr/bin/env python3
"""Live, non-publishing acquisition for EEA Civil Society Fund Romania call pages.

The call index is discovery only. Exact call-detail pages on eeagrants.org are fetched
individually, hashed, parsed, and passed to EEA_CSF_ROMANIA_CALLS_V1. No record is
authorized for publication here; material facts remain reconciliation candidates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import ssl
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

MODULE_PATH = Path(__file__).with_name("eea_civil_society_calls.py")
spec = importlib.util.spec_from_file_location("eea_csf_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(adapter)

PARSER_VERSION = "EEA_CSF_ROMANIA_LIVE_FETCH_V3"
INDEX_URL = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
# Previously verified official exact call pages. This is only a discovery fallback.
# Fresh HTTPS readback, hash, semantic reconciliation and publication gates remain mandatory.
PINNED_OFFICIAL_CALLS = (
    (1, "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives"),
    (2, "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-2-empowering-civic-participation-underserved-communities"),
    (3, "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-3-community-driven-projects-human-rights-and-social-justice"),
    (4, "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-4-promoting-diversity-equality-and-combating-gender-based-violence"),
    (5, "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-5-roma-inclusion-and-empowerment-through-development-interethnic-communities"),
    (6, "https://eeagrants.org/ro/eea-civil-society-fund-romania/calls/call-6-protecting-human-rights-through-climate-and-environmental-actions"),
    (7, "https://eeagrants.org/ro/eea-civil-society-fund-romania/calls/call-7-organisational-development-experienced-csos-and-federations"),
)
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
MAX_BYTES = 4_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"
CALL_PATH_RE = re.compile(
    r"^/(?:en|ro)/eea-civil-society-fund-romania/calls/(?P<slug>[^/?#]+)/?$",
    re.IGNORECASE,
)
INDEX_PATH_RE = re.compile(
    r"^/(?:en|ro)/eea-civil-society-fund-romania/calls/?$",
    re.IGNORECASE,
)
DATE_RE = r"\d{2}/\d{2}/\d{4}"
AMOUNT_RE = r"(?:€|EUR)\s*\d[\d.,]*"


# This parser extracts only directly visible HTML evidence. Hidden, inert and
# non-rendered descendants cannot assert OPEN, a deadline or a source identity.
# External stylesheets are not evaluated: output remains a candidate for review.
_HIDDEN_TAGS = {"head", "template", "script", "style", "noscript", "iframe",
                "object", "svg", "datalist", "select", "textarea", "canvas"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.texts: list[str] = []
        self.h1_parts: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._hidden_depth = 0
        self._h1_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        # Check *every* occurrence: dict(attrs) would allow duplicate attributes
        # to hide contradictory visibility instructions.
        values: dict[str, list[str]] = {}
        for key, value in attrs:
            values.setdefault(key.lower(), []).append((value or "").strip().lower())
        styles = values.get("style", [])
        # CSS utilities can conceal entire call-status/identity sections without
        # hidden/aria-hidden attributes. Treat known responsive Bootstrap states
        # as unverified visibility, never as evidence that a call is OPEN.
        classes = {token for value in values.get("class", []) for token in value.split()}
        css_concealed = (
            bool(classes & {"d-none", "hidden", "invisible", "visually-hidden", "sr-only"})
            or any(re.fullmatch(r"d-(?:sm|md|lg|xl|xxl)-none", token) for token in classes)
            or "collapsing" in classes
            or ("collapse" in classes and "show" not in classes)
            or ("tab-pane" in classes and "active" not in classes)
        )
        concealed = (
            css_concealed
            or tag in _HIDDEN_TAGS
            or (tag in {"dialog", "details"} and "open" not in values)
            # HTML popovers are hidden by default; static acquisition cannot
            # prove script-driven visibility, so they are never source prose.
            or "popover" in values
            or "hidden" in values
            or "inert" in values
            or any(v in {"true", "1"} for v in values.get("aria-hidden", []))
            or any(re.search(r"(?:^|;)\s*display\s*:\s*none\b", v) for v in styles)
            or any(re.search(r"(?:^|;)\s*visibility\s*:\s*(?:hidden|collapse)\b", v) for v in styles)
            or any(re.search(r"(?:^|;)\s*content-visibility\s*:\s*hidden\b", v) for v in styles)
            or any(re.search(r"(?:^|;)\s*opacity\s*:\s*0(?:\.0+)?\s*(?:!\s*important\s*)?(?:;|$)", v) for v in styles)
        )
        hidden = self._hidden_depth > 0 or concealed
        if not hidden and tag == "a":
            hrefs = values.get("href", [])
            if len(hrefs) == 1 and hrefs[0]:
                self.links.append(hrefs[0])
        if tag not in _VOID_TAGS:
            self._stack.append((tag, concealed))
            if concealed:
                self._hidden_depth += 1
            if tag == "h1" and not hidden:
                self._h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        # An unexpected closing tag must not clear an ancestor's hidden status.
        matching = next((i for i in range(len(self._stack) - 1, -1, -1)
                         if self._stack[i][0] == tag), None)
        if matching is None:
            return
        for element, concealed in self._stack[matching:]:
            if concealed:
                self._hidden_depth -= 1
            if element == "h1" and not concealed:
                self._h1_depth = max(0, self._h1_depth - 1)
        del self._stack[matching:]

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.texts.append(value)
        if self._h1_depth:
            self.h1_parts.append(value)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _official_url(url: str, *, call_detail: bool | None = None) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-official EEA URL: {url}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected authority components in URL: {url}")
    # Do not silently strip query, fragment, or semicolon path parameters.
    # In discovery these are unregistered source endpoints, even when their
    # sanitized URL resembles a known exact call. Raw provenance must bind
    # to what the official anchor actually named, not a rewritten URL.
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"unregistered EEA source URL components: {url}")
    path = parsed.path or "/"
    if call_detail is True and not CALL_PATH_RE.match(path):
        raise ValueError(f"not an exact EEA CSF call-detail URL: {url}")
    if call_detail is False and not INDEX_PATH_RE.match(path):
        raise ValueError(f"not the EEA CSF call index URL: {url}")
    return urlunparse(("https", host, path.rstrip("/") or "/", "", "", ""))


def _same_official_endpoint(registered_url: str, candidate_url: str) -> str:
    """A redirect can change www or a trailing slash, never the source identity."""
    original = urlparse(_official_url(registered_url))
    destination_parts = urlparse(candidate_url)
    if destination_parts.query or destination_parts.fragment:
        raise ValueError("EEA source redirect introduced unregistered query/fragment")
    destination = urlparse(_official_url(candidate_url))
    if (
        (original.hostname or "").removeprefix("www.")
        != (destination.hostname or "").removeprefix("www.")
        or original.path.rstrip("/") != destination.path.rstrip("/")
    ):
        raise ValueError("EEA redirect crossed registered official source endpoint")
    return _official_url(candidate_url)


class _RegisteredEEARedirect(HTTPRedirectHandler):
    """Reject untrusted hops *before* urllib follows them, even if it returns later."""

    def __init__(self, registered_url: str) -> None:
        super().__init__()
        self.registered_url = registered_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _same_official_endpoint(self.registered_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_registered_source(request: Request, *, timeout: float):
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        _RegisteredEEARedirect(request.full_url),
    )
    return opener.open(request, timeout=timeout)


def fetch_url(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    requested_url = _official_url(url)
    request = Request(
        requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    with _open_registered_source(request, timeout=timeout) as response:
        status = int(response.getcode() or 0)
        final_url = _same_official_endpoint(requested_url, response.geturl())
        content_type = response.headers.get("Content-Type", "")
        encoding = (response.headers.get("Content-Encoding") or "identity").strip().lower()
        declared_length = response.headers.get("Content-Length")
        if status != 200:
            raise RuntimeError(f"HTTP {status} for {requested_url}")
        if encoding != "identity":
            raise RuntimeError(f"unsupported encoded EEA source body: {encoding}")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise RuntimeError(f"empty or oversized EEA source body for {requested_url}")
    if declared_length is not None:
        declared = str(declared_length).strip()
        if not declared.isdecimal() or int(declared) != len(raw):
            raise RuntimeError("EEA source body differs from declared Content-Length")
    # MIME must match the registered HTML media type, not merely contain the
    # token in an arbitrary parameter or attacker-controlled subtype.
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise RuntimeError(f"unexpected content type {content_type!r} for {requested_url}")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def _validate_handoff_response(
    requested_url: str, response: dict[str, Any]
) -> tuple[str, bytes]:
    """An injected acquisition transport is not a provenance authority.

    Enforce the same source identity, HTTP success, media type and raw-body
    limits as the built-in network fetcher before parsing or admitting bytes.
    A forged handoff must never be accepted merely because its HTML parses.
    """
    if not isinstance(response, dict):
        raise ValueError("EEA handoff is not a response envelope")
    declared_request = response.get("requested_url")
    if not isinstance(declared_request, str):
        raise ValueError("EEA handoff lacks requested source identity")
    _same_official_endpoint(requested_url, declared_request)
    if type(response.get("status")) is not int or response["status"] != 200:
        raise ValueError("EEA handoff lacks verified HTTP 200")
    media_type = str(response.get("content_type") or "").split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("EEA handoff has non-HTML media type")
    raw = response.get("raw")
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError("EEA handoff has absent, invalid or oversized raw HTML")
    final_url = response.get("final_url")
    if not isinstance(final_url, str):
        raise ValueError("EEA handoff lacks final source identity")
    return _same_official_endpoint(requested_url, final_url), raw


def _parse_document(raw: bytes) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def discover_call_urls(raw: bytes, *, base_url: str = INDEX_URL) -> list[str]:
    base_url = _official_url(base_url, call_detail=False)
    parser = _parse_document(raw)
    discovered: dict[tuple[int, str], str] = {}
    for href in parser.links:
        candidate = urljoin(base_url + "/", href)
        try:
            candidate = _official_url(candidate, call_detail=True)
        except ValueError:
            continue
        match = CALL_PATH_RE.match(urlparse(candidate).path)
        if not match:
            continue
        slug = match.group("slug")
        number_match = re.match(r"call-(\d+)-", slug, flags=re.IGNORECASE)
        if not number_match:
            continue
        number = int(number_match.group(1))
        language = urlparse(candidate).path.split("/", 2)[1].lower()
        # Distinct exact URLs for the same call and language may represent
        # conflicting official revisions (including stale OPEN/CLOSED aliases).
        # Never silently select whichever anchor appears last in the index.
        key = (number, language)
        previous = discovered.get(key)
        if previous is not None and previous != candidate:
            raise RuntimeError(
                f"ambiguous official EEA call {number} ({language}): "
                f"{previous} vs {candidate}"
            )
        discovered[key] = candidate

    by_number: dict[int, tuple[int, str]] = {}
    for (number, language), url in discovered.items():
        rank = 0 if language == "en" else 1
        previous = by_number.get(number)
        if previous is None or rank < previous[0]:
            by_number[number] = (rank, url)
    return [by_number[number][1] for number in sorted(by_number)]


def _flat_text(parser: _DocumentParser) -> str:
    return " ".join(parser.texts)


def _extract_label_value(flat: str, labels: tuple[str, ...], pattern: str) -> str | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*:?\s*({pattern})", flat, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split())
    return None


def _call_number_from_url(url: str) -> str | None:
    match = CALL_PATH_RE.match(urlparse(url).path)
    if not match:
        return None
    number_match = re.match(r"call-(\d+)-", match.group("slug"), flags=re.IGNORECASE)
    return number_match.group(1) if number_match else None


def _status_label(flat: str) -> str | None:
    pairs = (
        (r"\bCall for projects\s+Open\b", "Open"),
        (r"\bCall for projects\s+Closed\b", "Closed"),
        (r"\bCall for projects\s+(?:Forthcoming|Upcoming)\b", "Forthcoming"),
        (r"\bApeluri? de proiecte\s+Deschis\b", "Open"),
        (r"\bApeluri? de proiecte\s+Închis\b", "Closed"),
        (r"\bApeluri? de proiecte\s+(?:Viitor|În pregătire)\b", "Forthcoming"),
    )
    # Conflicting visible statuses (e.g. a page template embedding another
    # call's badge) are never sufficient to label this exact call OPEN.
    matched = {value for pattern, value in pairs
               if re.search(pattern, flat, flags=re.IGNORECASE)}
    return next(iter(matched)) if len(matched) == 1 else None


def parse_call_page(raw: bytes, *, authority_url: str) -> dict[str, Any]:
    authority_url = _official_url(authority_url, call_detail=True)
    parser = _parse_document(raw)
    flat = _flat_text(parser)
    call_number = _call_number_from_url(authority_url)
    title = " ".join(parser.h1_parts).strip() or None

    eligible = None
    eligible_match = re.search(
        r"(?:Eligible Applicants|Solicitanții eligibili)\s+(.*?)\s+(?:Call details|Detalii apel|Call number|Numărul Apelului)",
        flat,
        flags=re.IGNORECASE,
    )
    if eligible_match:
        eligible = " ".join(eligible_match.group(1).split())[:1600] or None

    return {
        "callNumber": call_number,
        "title": title,
        "status": _status_label(flat),
        "authorityUrl": authority_url,
        "publicationDate": _extract_label_value(
            flat,
            ("Publication date", "Data publicării"),
            DATE_RE,
        ),
        "submissionDeadline": _extract_label_value(
            flat,
            ("Submission Deadline", "Data limită de depunere a Cererilor de finanțare"),
            DATE_RE,
        ),
        "questionsDeadline": _extract_label_value(
            flat,
            ("Questions deadline date", "Data limită pentru adresarea de întrebări"),
            DATE_RE,
        ),
        "amountAvailable": _extract_label_value(
            flat,
            ("Amount available", "Sumă disponibilă"),
            AMOUNT_RE,
        ),
        "grantAmountFrom": _extract_label_value(
            flat,
            ("Grant amount from", "Valoarea minimă a grantului"),
            AMOUNT_RE,
        ),
        "grantAmountTo": _extract_label_value(
            flat,
            ("Grant amount to", "Valoarea maximă a grantului"),
            AMOUNT_RE,
        ),
        "eligibleApplicants": eligible,
    }


def discover_with_official_fallback(
    raw: bytes, *, base_url: str, minimum_calls: int
) -> tuple[list[str], str, int]:
    """Recover exact official pages after a post-deadline dynamic index transition.

    The official index must affirm the identity and exactly seven launched calls.
    Pinned URLs grant discovery only; every detail page is re-fetched and verified.
    """
    linked = discover_call_urls(raw, base_url=base_url)
    if linked:
        return linked, "INDEX_EXACT_ANCHORS", len(linked)

    flat = _flat_text(_parse_document(raw)).casefold()
    seven_confirmed = (
        "eea civil society fund" in flat
        and (
            "seven calls for proposals" in flat
            or "șapte apeluri de proiecte" in flat
        )
    )
    if not seven_confirmed or minimum_calls != len(PINNED_OFFICIAL_CALLS):
        return [], "INDEX_WITHOUT_VERIFIED_DETAIL_LINKS", 0

    pinned: list[str] = []
    for number, url in PINNED_OFFICIAL_CALLS:
        canonical = _official_url(url, call_detail=True)
        if _call_number_from_url(canonical) != str(number):
            raise RuntimeError("pinned official EEA call identity/path mismatch")
        pinned.append(canonical)
    if len(pinned) != len(set(pinned)):
        raise RuntimeError("duplicate pinned official EEA call URLs")
    return pinned, "PINNED_OFFICIAL_DETAIL_DISCOVERY_REQUIRES_FRESH_READBACK", 0


def collect_live(
    *,
    index_url: str = INDEX_URL,
    run_id: str,
    fetched_at: str | None = None,
    minimum_calls: int = 1,
    fetcher: Callable[[str], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    index = fetcher(index_url)
    # Defence in depth: the injected acquisition transport cannot rebind an
    # official index receipt to a different page on the same authority.
    index_final, index_raw = _validate_handoff_response(index_url, index)
    call_urls, discovery_mode, index_link_count = discover_with_official_fallback(
        index_raw, base_url=index_final, minimum_calls=minimum_calls
    )
    if len(call_urls) < minimum_calls:
        raise RuntimeError(
            f"discovered {len(call_urls)} call-detail URLs, below minimum {minimum_calls}"
        )

    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for requested_url in call_urls:
        try:
            response = fetcher(requested_url)
            # A caller-supplied fetcher is not trusted to enforce redirect identity.
            # Same-domain sibling calls remain distinct immutable source endpoints.
            final_url, raw = _validate_handoff_response(requested_url, response)
            record = parse_call_page(raw, authority_url=final_url)
            normalized = adapter.normalize_record(
                record,
                fetched_at=fetched_at,
                run_id=run_id,
                raw_hash=_sha256(raw),
                verified_authority_urls=[final_url],
            )
            if normalized is None:
                raise RuntimeError("call-detail page did not yield a stable call identifier")
            records.append(normalized)
            pages.append(
                {
                    "requested_url": _official_url(requested_url, call_detail=True),
                    "final_url": final_url,
                    "http_status": int(response["status"]),
                    "content_type": str(response["content_type"]),
                    "raw_hash": _sha256(raw),
                    "bytes": len(raw),
                    "call_identifier": normalized["call_identifier"],
                    "observation_state": normalized["observation_state"],
                }
            )
        except Exception as exc:
            errors.append({"url": requested_url, "error": f"{type(exc).__name__}: {exc}"})

    unique_records: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for record in records:
        key = (
            record["call_identifier"],
            record["programme_family"],
            record["authority_url"],
        )
        previous = unique_records.get(key)
        if previous is None:
            unique_records[key] = record
            continue
        if previous["semantic_fingerprint"] != record["semantic_fingerprint"]:
            previous["requires_reconcile"] = True
            record["requires_reconcile"] = True
            conflicts.append(
                {
                    "call_identifier": record["call_identifier"],
                    "programme_family": record["programme_family"],
                    "authority_url": record["authority_url"],
                    "fingerprints": sorted(
                        {
                            previous["semantic_fingerprint"],
                            record["semantic_fingerprint"],
                        }
                    ),
                }
            )

    normalized_records = list(unique_records.values())
    return {
        "schema": "PARTENER_EU_EEA_CSF_LIVE_EVIDENCE_V1",
        "source_family": adapter.SOURCE_FAMILY,
        "programme_family": adapter.PROGRAMME_FAMILY,
        "authority_class": adapter.AUTHORITY_CLASS,
        "source_index": {
            "url": index_final,
            "http_status": int(index["status"]),
            "content_type": str(index["content_type"]),
            "raw_hash": _sha256(index_raw),
            "bytes": len(index_raw),
            "discovery_mode": discovery_mode,
            "direct_exact_call_links": index_link_count,
        },
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "adapter_version": adapter.PARSER_VERSION,
        "run_id": run_id,
        "pages": pages,
        "records": normalized_records,
        "conflicts": conflicts,
        "errors": errors,
        "stats": {
            "discovered_call_urls": len(call_urls),
            "index_direct_exact_call_links": index_link_count,
            "official_pinned_fallback_used": discovery_mode.startswith("PINNED_"),
            "fetched_call_pages": len(pages),
            "normalized_records": len(normalized_records),
            "open_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "OPEN_CALL"
            ),
            "forthcoming_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "FORTHCOMING_CALL"
            ),
            "closed_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "CLOSED_CALL"
            ),
            "unknown_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "UNKNOWN"
            ),
            "errors": len(errors),
            "conflicts": len(conflicts),
        },
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "requires_reconcile": bool(normalized_records or conflicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-url", default=INDEX_URL)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--minimum-calls", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    run_id = args.run_id or f"EEA-CSF-LIVE-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    evidence = collect_live(
        index_url=args.index_url,
        run_id=run_id,
        fetched_at=args.fetched_at,
        minimum_calls=args.minimum_calls,
    )
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    if evidence["stats"]["errors"] or evidence["stats"]["conflicts"]:
        return 2
    if evidence["stats"]["fetched_call_pages"] < args.minimum_calls:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
