#!/usr/bin/env python3
"""Bounded common exact-current adapter for EEA CSF Romania Calls #1-#3.

This module centralises transport/provenance/fail-closed mechanics only. Exact
call identity, titles and numeric candidate fields remain explicit in SPECS.
All observed call fields are non-authorizing candidate evidence until semantic
reconciliation and field-scoped material admission are completed downstream.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA_CIVIL_SOCIETY_FUND_ROMANIA"
PROGRAMME_ID = "EEA_CSF_RO_2021_2028"
AUTHORITY_CLASS = "T1_FMO_OFFICIAL_EXACT_CALL"
OBSERVATION_STATE = "EXACT_CURRENT_CALL_NON_AUTHORIZING"
CALL_IDENTIFIER_KIND = "OFFICIAL_CALL_NUMBER"
INDEX_URL = "https://eeagrants.org/ro/eea-civil-society-fund-romania/calls"
MAX_BYTES = 4 * 1024 * 1024
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


@dataclass(frozen=True)
class CallSpec:
    call_id: str
    slug: str
    title_ro: str
    title_en: str
    budget: str
    grant_min: str
    grant_max: str

    @property
    def exact_url(self) -> str:
        return f"{INDEX_URL}/{self.slug}"

    @property
    def schema(self) -> str:
        return f"PARTENER_EU_EEA_CSF_RO_CALL{self.call_id}_EXACT_EVIDENCE_V1"

    @property
    def parser_version(self) -> str:
        return f"EEA_CSF_RO_CALL{self.call_id}_EXACT_V1"


SPECS: dict[str, CallSpec] = {
    "1": CallSpec(
        call_id="1",
        slug="call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives",
        title_ro="Apel #1 Consolidarea democrației și a statului de drept prin inițiative ale societății civile",
        title_en="Call #1 Strengthening Democracy and Rule of Law through Civil Society Initiatives",
        budget="EUR 3,718,664",
        grant_min="EUR 200,001",
        grant_max="EUR 350,000",
    ),
    "2": CallSpec(
        call_id="2",
        slug="call-2-empowering-civic-participation-underserved-communities",
        title_ro="Apel #2 Consolidarea participării civice în comunitățile insuficient deservite",
        title_en="Call #2 Empowering Civic Participation in Underserved Communities",
        budget="EUR 4,500,000",
        grant_min="EUR 15,000",
        grant_max="EUR 350,000",
    ),
    "3": CallSpec(
        call_id="3",
        slug="community-driven-projects-human-rights-and-social-justice",
        title_ro="Apel #3 Proiecte comunitare pentru drepturile omului și justiție socială",
        title_en="Call #3 Community-Driven Projects for Human Rights and Social Justice",
        budget="EUR 6,300,000",
        grant_min="EUR 200,001",
        grant_max="EUR 350,000",
    ),
}


class ExactCSFCommonError(ValueError):
    pass


class TextProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def get_spec(call_id: str) -> CallSpec:
    try:
        return SPECS[str(call_id)]
    except KeyError as exc:
        raise ExactCSFCommonError(f"unsupported bounded EEA CSF call id: {call_id!r}") from exc


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _fold(value: str) -> str:
    text = html.unescape(value or "").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def _validate_url(spec: CallSpec, url: str, *, exact: bool = False) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "eeagrants.org":
        raise ExactCSFCommonError(f"unexpected EEA CSF authority URL: {url!r}")
    path = parsed.path.rstrip("/")
    prefix = "/ro/eea-civil-society-fund-romania/calls"
    if not path.startswith(prefix):
        raise ExactCSFCommonError(f"EEA CSF authority path outside bounded allowlist: {parsed.path!r}")
    if exact and path.split("/")[-1] != spec.slug:
        raise ExactCSFCommonError(f"bounded exact adapter accepts only official Call #{spec.call_id} detail")
    return url


def _http_fetch(url: str, *, timeout: float = 25.0) -> tuple[bytes, int, str, str]:
    req = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-EEA-CSF-Exact/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ro,en;q=0.8",
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ExactCSFCommonError("EEA CSF exact source exceeded bounded acquisition limit")
        return raw, int(getattr(response, "status", 200)), str(response.geturl()), str(response.headers.get("Content-Type", ""))


def _receipt(
    url: str,
    *,
    raw: bytes | None = None,
    status: int | None = None,
    final_url: str | None = None,
    content_type: str | None = None,
    health: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "health_state": health,
        "lkg_required": health != "HEALTHY",
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "error": error,
    }


def _safe_fetch(
    spec: CallSpec,
    url: str,
    *,
    exact: bool,
    timeout: float,
    fetcher: Callable[..., tuple[bytes, int, str, str]],
) -> tuple[bytes | None, dict[str, Any]]:
    _validate_url(spec, url, exact=exact)
    try:
        raw, status, final_url, content_type = fetcher(url, timeout=timeout)
        _validate_url(spec, final_url, exact=exact)
        if status != 200:
            return raw, _receipt(url, raw=raw, status=status, final_url=final_url, content_type=content_type, health="DEGRADED_HTTP", error=f"unexpected HTTP status {status}")
        if "html" not in content_type.casefold():
            return raw, _receipt(url, raw=raw, status=status, final_url=final_url, content_type=content_type, health="DEGRADED_CONTENT_TYPE", error=f"unexpected content type {content_type!r}")
        return raw, _receipt(url, raw=raw, status=status, final_url=final_url, content_type=content_type, health="HEALTHY")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return None, _receipt(url, status=getattr(exc, "code", None), health="DEGRADED_TRANSPORT", error=f"{type(exc).__name__}: {exc}")


def _index_binds_exact(spec: CallSpec, index_raw: bytes) -> bool:
    decoded = html.unescape(index_raw.decode("utf-8", errors="ignore"))
    folded = _fold(_text(index_raw))
    title_present = any(_fold(marker) in folded for marker in (spec.title_ro, spec.title_en))
    return title_present and urlparse(spec.exact_url).path in decoded


def _status(text: str) -> tuple[str, str]:
    folded = _fold(text)
    open_patterns = (
        r"apeluri de proiecte\s+deschis\b",
        r"call for projects\s+open\b",
        r"call status\s*:?\s*open\b",
    )
    closed_patterns = (
        r"apeluri de proiecte\s+inchis\b",
        r"call for projects\s+closed\b",
        r"call status\s*:?\s*closed\b",
    )
    if any(re.search(pattern, folded) for pattern in open_patterns):
        return "OPEN_CALL", "Open"
    if any(re.search(pattern, folded) for pattern in closed_patterns):
        return "CLOSED_CALL", "Closed"
    return "UNKNOWN", "Unknown"


def _number_present(folded: str, label_ro: str, label_en: str, value: str) -> bool:
    escaped = re.escape(value)
    return bool(re.search(rf"{label_ro}\s+€?\s*{escaped}", folded) or re.search(rf"{label_en}\s+€?\s*{escaped}", folded))


def _unknown_semantics(spec: CallSpec) -> dict[str, Any]:
    return {
        "programme_id": PROGRAMME_ID,
        "official_call_identifier": spec.call_id,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "title": spec.title_ro,
        "authority_url": spec.exact_url,
        "candidate_state": "UNKNOWN",
        "status_label": "Unknown",
        "publication_date_candidate": None,
        "questions_deadline_candidate": None,
        "deadline_candidate": None,
        "budget_candidate": None,
        "grant_min_candidate": None,
        "grant_max_candidate": None,
    }


def _detail_semantics(spec: CallSpec, raw: bytes) -> dict[str, Any]:
    text = _text(raw)
    folded = _fold(text)
    if not any(_fold(marker) in folded for marker in (spec.title_ro, spec.title_en)):
        raise ExactCSFCommonError(f"exact EEA CSF detail lost Call #{spec.call_id} title")
    if "civil society fund" not in folded:
        raise ExactCSFCommonError("exact EEA CSF detail lost programme marker")
    if not re.search(rf"numarul apelului de proiecte\s+{spec.call_id}\b", folded) and not re.search(rf"call number\s+{spec.call_id}\b", folded):
        raise ExactCSFCommonError(f"exact EEA CSF detail lost official Call number {spec.call_id}")

    candidate_state, status_label = _status(text)
    deadline = "2026-10-08" if (re.search(r"data limita de depunere a cererilor de finantare\s+08/10/2026", folded) or re.search(r"submission deadline\s*:?\s*08/10/2026", folded)) else None
    publication_date = "2026-07-08" if (re.search(r"data publicarii\s+08/07/2026", folded) or re.search(r"publication date\s+08/07/2026", folded)) else None
    questions_deadline = "2026-09-29" if (re.search(r"data limita pentru adresarea de intrebari\s+29/09/2026", folded) or re.search(r"questions deadline date\s+29/09/2026", folded)) else None
    budget_value = spec.budget.removeprefix("EUR ")
    min_value = spec.grant_min.removeprefix("EUR ")
    max_value = spec.grant_max.removeprefix("EUR ")
    amount = spec.budget if _number_present(folded, "suma disponibila", "amount available", budget_value) else None
    minimum = spec.grant_min if _number_present(folded, "valoarea minima a grantului", "grant amount from", min_value) else None
    maximum = spec.grant_max if _number_present(folded, "valoarea maxima a grantului", "grant amount to", max_value) else None

    return {
        "programme_id": PROGRAMME_ID,
        "official_call_identifier": spec.call_id,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "title": spec.title_ro,
        "authority_url": spec.exact_url,
        "candidate_state": candidate_state,
        "status_label": status_label,
        "publication_date_candidate": publication_date,
        "questions_deadline_candidate": questions_deadline,
        "deadline_candidate": deadline,
        "budget_candidate": amount,
        "grant_min_candidate": minimum,
        "grant_max_candidate": maximum,
    }


def collect_exact(
    call_id: str,
    *,
    run_id: str,
    fetched_at: str | None = None,
    timeout: float = 25.0,
    output_dir: pathlib.Path | None = None,
    fetcher: Callable[..., tuple[bytes, int, str, str]] = _http_fetch,
) -> dict[str, Any]:
    spec = get_spec(call_id)
    observed = fetched_at or utc_now()
    index_raw, index_receipt = _safe_fetch(spec, INDEX_URL, exact=False, timeout=timeout, fetcher=fetcher)
    detail_raw, detail_receipt = _safe_fetch(spec, spec.exact_url, exact=True, timeout=timeout, fetcher=fetcher)

    discovery_link_verified = bool(index_raw is not None and index_receipt["health_state"] == "HEALTHY" and _index_binds_exact(spec, index_raw))
    if index_receipt["health_state"] == "HEALTHY" and not discovery_link_verified:
        index_receipt = {**index_receipt, "health_state": "DEGRADED_MARKER_MISMATCH", "lkg_required": True, "error": f"official EEA CSF call index lost exact Call #{spec.call_id} binding"}

    semantics: dict[str, Any] | None = None
    if detail_raw is not None and detail_receipt["health_state"] == "HEALTHY":
        try:
            semantics = _detail_semantics(spec, detail_raw)
        except ExactCSFCommonError as exc:
            detail_receipt = {**detail_receipt, "health_state": "DEGRADED_MARKER_MISMATCH", "lkg_required": True, "error": str(exc)}

    healthy = discovery_link_verified and semantics is not None and index_receipt.get("health_state") == "HEALTHY" and detail_receipt.get("health_state") == "HEALTHY"
    source_health_state = "HEALTHY" if healthy else "DEGRADED"
    exact_semantics = semantics if healthy and semantics is not None else _unknown_semantics(spec)
    identity_basis = {
        "programme_id": PROGRAMME_ID,
        "official_call_identifier": spec.call_id,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "authority_url": spec.exact_url,
    }
    missing = ["semantic_reconciliation", "field_scoped_material_admission"]
    if source_health_state != "HEALTHY" or exact_semantics["candidate_state"] == "UNKNOWN":
        missing.insert(0, "fresh_exact_current_status")

    evidence: dict[str, Any] = {
        "schema": spec.schema,
        "parser_version": spec.parser_version,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "run_id": run_id,
        "fetched_at": observed,
        "index_url": INDEX_URL,
        "authority_url": spec.exact_url,
        "discovery_link_verified": discovery_link_verified,
        "official_call_identifier": spec.call_id,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "identity_key": sha256_json(identity_basis),
        "candidate_state": exact_semantics["candidate_state"],
        "status_label": exact_semantics["status_label"],
        "deadline_candidate": exact_semantics["deadline_candidate"],
        "budget_candidate": exact_semantics["budget_candidate"],
        "grant_min_candidate": exact_semantics["grant_min_candidate"],
        "grant_max_candidate": exact_semantics["grant_max_candidate"],
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "source_health_state": source_health_state,
        "lkg_required": source_health_state != "HEALTHY",
        "source_receipts": {"official_calls_index_discovery": index_receipt, "official_exact_call_detail": detail_receipt},
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "missing_for_material_admission": missing,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(call_id, evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        if index_raw is not None:
            (output_dir / "eea-csf-ro-calls-index.html").write_bytes(index_raw)
        if detail_raw is not None:
            (output_dir / f"eea-csf-ro-call{spec.call_id}-detail.html").write_bytes(detail_raw)
        (output_dir / f"eea-csf-ro-call{spec.call_id}-exact-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return evidence


def validate_evidence(call_id: str, evidence: Mapping[str, Any]) -> None:
    spec = get_spec(call_id)
    if evidence.get("schema") != spec.schema or evidence.get("parser_version") != spec.parser_version:
        raise ExactCSFCommonError(f"EEA CSF Call #{spec.call_id} exact schema/parser drift")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ExactCSFCommonError("EEA CSF exact family drift")
    if evidence.get("programme_id") != PROGRAMME_ID:
        raise ExactCSFCommonError("EEA CSF programme identity drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS or evidence.get("observation_state") != OBSERVATION_STATE:
        raise ExactCSFCommonError("EEA CSF authority/observation drift")
    _validate_url(spec, str(evidence.get("index_url") or ""), exact=False)
    _validate_url(spec, str(evidence.get("authority_url") or ""), exact=True)
    if evidence.get("official_call_identifier") != spec.call_id or evidence.get("call_identifier_kind") != CALL_IDENTIFIER_KIND:
        raise ExactCSFCommonError(f"EEA CSF official Call #{spec.call_id} identifier drift")
    identity_basis = {"programme_id": PROGRAMME_ID, "official_call_identifier": spec.call_id, "call_identifier_kind": CALL_IDENTIFIER_KIND, "authority_url": spec.exact_url}
    if evidence.get("identity_key") != sha256_json(identity_basis):
        raise ExactCSFCommonError("EEA CSF exact identity fingerprint mismatch")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, Mapping) or sha256_json(dict(semantics)) != evidence.get("exact_semantic_fingerprint"):
        raise ExactCSFCommonError("EEA CSF exact semantic fingerprint mismatch")
    if semantics.get("official_call_identifier") != spec.call_id:
        raise ExactCSFCommonError("EEA CSF exact semantics lost official call identifier")
    if evidence.get("candidate_state") not in {"OPEN_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ExactCSFCommonError("EEA CSF exact candidate state unsupported")
    if evidence.get("source_health_state") == "HEALTHY":
        if evidence.get("lkg_required") is not False or evidence.get("discovery_link_verified") is not True:
            raise ExactCSFCommonError("healthy EEA CSF exact chain lost discovery/detail binding")
        receipts = evidence.get("source_receipts") or {}
        if set(receipts) != {"official_calls_index_discovery", "official_exact_call_detail"}:
            raise ExactCSFCommonError("EEA CSF source receipt set drift")
        for receipt in receipts.values():
            if receipt.get("health_state") != "HEALTHY" or receipt.get("http_status") != 200:
                raise ExactCSFCommonError("healthy EEA CSF aggregate contains degraded receipt")
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("raw_sha256") or "")):
                raise ExactCSFCommonError("healthy EEA CSF receipt lost raw SHA-256")
    else:
        if evidence.get("lkg_required") is not True:
            raise ExactCSFCommonError("degraded EEA CSF exact chain did not require LKG/reference handling")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("status_label") != "Unknown":
            raise ExactCSFCommonError("degraded EEA CSF exact chain retained material candidate state")
        for key in ("deadline_candidate", "budget_candidate", "grant_min_candidate", "grant_max_candidate"):
            if evidence.get(key) is not None:
                raise ExactCSFCommonError(f"degraded EEA CSF exact chain retained candidate field: {key}")
    missing = set(evidence.get("missing_for_material_admission") or [])
    if "semantic_reconciliation" not in missing or "field_scoped_material_admission" not in missing:
        raise ExactCSFCommonError("EEA CSF exact evidence weakened downstream gates")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ExactCSFCommonError(f"EEA CSF exact evidence attempted authorization: {key}")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ExactCSFCommonError("EEA CSF exact evidence skipped mandatory gates")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ExactCSFCommonError("EEA CSF exact evidence crossed publication boundary")


def main_for(call_id: str) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fetched-at")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    evidence = collect_exact(call_id, run_id=args.run_id, fetched_at=args.fetched_at, timeout=args.timeout, output_dir=args.output_dir)
    print(json.dumps({"official_call_identifier": evidence["official_call_identifier"], "candidate_state": evidence["candidate_state"], "status_label": evidence["status_label"], "deadline_candidate": evidence["deadline_candidate"], "source_health_state": evidence["source_health_state"], "open_call_authorized": False, "publication_effect": "NONE"}, ensure_ascii=False, sort_keys=True))
    return 0
