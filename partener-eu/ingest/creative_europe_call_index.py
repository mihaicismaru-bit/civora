#!/usr/bin/env python3
"""Fail-closed Creative Europe call-index discovery adapter.

The European Commission Culture & Creativity funding index mixes Creative
Europe calls with other culture-sector opportunities. This adapter therefore
admits only rows carrying an explicit `CREA-*` reference and keeps every
index-level lifecycle/deadline value non-authorizing. Material call facts must
be resolved through exact current Funding & Tenders topic evidence and semantic
reconciliation.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

ADAPTER_ID = "CREATIVE_EUROPE_CALLS_V1"
PARSER_VERSION = "CREATIVE_EUROPE_CALL_INDEX_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CREATIVE_EUROPE"
AUTHORITY_CLASS = "EUROPEAN_COMMISSION_CULTURE_CALL_INDEX"
OBSERVATION_STATE = "CALL_INDEX_DISCOVERY"
REF_RE = re.compile(r"^CREA-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
STATUS_VALUES = {"open", "closed", "upcoming"}
LABELS = {"ref:", "reference:", "status:", "deadline:", "opportunity details", "call details"}
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)


class _VisibleEventParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, str | None]] = []
        self._suppressed_depth = 0
        self._link_href: str | None = None
        self._link_parts: list[str] | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {k.lower(): (v or "") for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._suppressed_depth += 1
            return
        if self._suppressed_depth:
            return
        if tag == "a" and self._link_parts is None:
            self._link_href = self._attrs(attrs).get("href") or None
            self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if self._suppressed_depth:
            return
        if tag == "a" and self._link_parts is not None:
            value = " ".join(" ".join(self._link_parts).split())
            if value:
                self.events.append({"kind": "link", "value": value, "href": self._link_href})
            self._link_href = None
            self._link_parts = None

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._link_parts is not None:
            self._link_parts.append(value)
        else:
            self.events.append({"kind": "text", "value": value, "href": None})


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _value(event: dict[str, str | None]) -> str:
    return str(event.get("value") or "").strip()


def _parse(raw: bytes) -> list[dict[str, str | None]]:
    parser = _VisibleEventParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser.events


def _next_value(events: list[dict[str, str | None]], start: int, stop: int) -> str | None:
    for idx in range(start, stop):
        value = _value(events[idx])
        if value:
            return value
    return None


def _label_value(events: list[dict[str, str | None]], start: int, stop: int, label: str) -> str | None:
    wanted = label.casefold()
    for idx in range(start, stop):
        value = _value(events[idx])
        folded = value.casefold()
        if folded == wanted:
            return _next_value(events, idx + 1, stop)
        if folded.startswith(wanted):
            suffix = value[len(label):].strip()
            if suffix:
                return suffix
    return None


def _detail_url(events: list[dict[str, str | None]], start: int, stop: int, authority_url: str) -> str | None:
    authority_host = (urlparse(authority_url).hostname or "").lower()
    for idx in range(start, stop):
        event = events[idx]
        if event.get("kind") != "link":
            continue
        value = _value(event).casefold()
        href = str(event.get("href") or "").strip()
        if not href:
            continue
        resolved = urljoin(authority_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != authority_host:
            continue
        if "opportunity details" in value or "call details" in value:
            return resolved
    return None


def _title(events: list[dict[str, str | None]], start: int, stop: int) -> str | None:
    deadline_idx = None
    for idx in range(start, stop):
        if _value(events[idx]).casefold().startswith("deadline:"):
            deadline_idx = idx
            break
    search_start = (deadline_idx + 1) if deadline_idx is not None else start + 1
    skipped_date = False
    for idx in range(search_start, stop):
        value = _value(events[idx])
        folded = value.casefold()
        if not value or folded in LABELS or REF_RE.fullmatch(value):
            continue
        if folded in STATUS_VALUES:
            continue
        if folded.startswith(("status:", "deadline:", "ref:", "reference:")):
            continue
        if not skipped_date and (re.search(r"\b20\d{2}\b", value) or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]20\d{2}", value)):
            skipped_date = True
            continue
        if len(value) < 4:
            continue
        return value
    return None


def _strand(reference: str) -> str | None:
    upper = reference.upper()
    for marker in ("-CULT-", "-MEDIA-", "-CROSS-"):
        if marker in upper:
            return marker.strip("-")
    return None


def extract_creative_europe_candidates(raw: bytes, *, authority_url: str) -> list[dict[str, Any]]:
    """Extract only explicit CREA-* rows from the mixed Commission culture index."""
    events = _parse(raw)
    ref_indexes: list[int] = []
    for idx, event in enumerate(events):
        value = _value(event)
        if REF_RE.fullmatch(value):
            ref_indexes.append(idx)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pos, ref_idx in enumerate(ref_indexes):
        stop = ref_indexes[pos + 1] if pos + 1 < len(ref_indexes) else min(len(events), ref_idx + 60)
        reference = _value(events[ref_idx]).upper()
        if reference in seen:
            continue
        seen.add(reference)
        status = (_label_value(events, ref_idx + 1, stop, "Status:") or "").casefold() or None
        deadline = _label_value(events, ref_idx + 1, stop, "Deadline:")
        title = _title(events, ref_idx + 1, stop)
        detail_url = _detail_url(events, ref_idx + 1, stop, authority_url)
        rows.append({
            "call_reference_candidate": reference,
            "programme_strand_candidate": _strand(reference),
            "title_candidate": title,
            "status_candidate": status if status in STATUS_VALUES else None,
            "deadline_candidate": deadline,
            "detail_url_candidate": detail_url,
        })
    return rows


def normalize_call_index(raw: bytes, *, authority_url: str, fetched_at: str, run_id: str,
                         raw_hash: str | None = None) -> dict[str, Any]:
    raw_hash = raw_hash or sha256_bytes(raw)
    rows = extract_creative_europe_candidates(raw, authority_url=authority_url)
    records: list[dict[str, Any]] = []
    for row in rows:
        semantic = {
            "call_reference_candidate": row["call_reference_candidate"],
            "programme_strand_candidate": row["programme_strand_candidate"],
            "title_candidate": row["title_candidate"],
            "status_candidate": row["status_candidate"],
            "deadline_candidate": row["deadline_candidate"],
            "detail_url_candidate": row["detail_url_candidate"],
            "authority_url": authority_url,
        }
        record = {
            "schema": "PARTENER_EU_CREATIVE_EUROPE_CALL_INDEX_OBSERVATION_V1",
            "adapter_id": ADAPTER_ID,
            "parser_version": PARSER_VERSION,
            "source_family": SOURCE_FAMILY,
            "programme_family": PROGRAMME_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            "observation_state": OBSERVATION_STATE,
            **semantic,
            "exact_call_identifier": None,
            "current_status_label": None,
            "requires_exact_call_evidence": True,
            "requires_funding_tenders_structured_reconcile": True,
            "requires_reconcile": True,
            "market_intelligence_only": True,
            "publication_effect": "NONE",
            "canonical_corpus_mutation": False,
            "fetched_at": fetched_at,
            "raw_sha256": raw_hash,
            "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
            "run_id": run_id,
            "missing_for_open_confirmation": [
                "exact current Funding & Tenders topic readback",
                "explicit current official topic status",
                "call-specific deadline/budget/eligibility/participation evidence",
                "semantic reconciliation against previous observation/LKG",
            ],
        }
        for key in MATERIAL_FLAGS:
            record[key] = False
        records.append(record)

    batch = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_CALL_INDEX_BATCH_V1",
        "adapter_id": ADAPTER_ID,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": authority_url,
        "observation_state": OBSERVATION_STATE,
        "record_count": len(records),
        "records": records,
        "market_intelligence_only": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "fetched_at": fetched_at,
        "raw_sha256": raw_hash,
        "run_id": run_id,
    }
    for key in MATERIAL_FLAGS:
        batch[key] = False
    validate_call_index_batch(batch)
    return batch


def validate_call_index_batch(batch: dict[str, Any]) -> None:
    if batch.get("schema") != "PARTENER_EU_CREATIVE_EUROPE_CALL_INDEX_BATCH_V1":
        raise ValueError("Creative Europe call-index schema mismatch")
    if batch.get("adapter_id") != ADAPTER_ID or batch.get("parser_version") != PARSER_VERSION:
        raise ValueError("Creative Europe adapter/parser identity drift")
    if batch.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("Creative Europe observation state drift")
    if batch.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe index left market-intelligence boundary")
    if batch.get("publication_effect") != "NONE" or batch.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe index attempted canonical/public mutation")
    for key in MATERIAL_FLAGS:
        if batch.get(key) is not False:
            raise ValueError(f"Creative Europe index became authorizing: {key}")
    raw_hash = str(batch.get("raw_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("Creative Europe raw SHA-256 missing or invalid")
    seen: set[str] = set()
    for row in batch.get("records") or []:
        reference = str(row.get("call_reference_candidate") or "")
        if not REF_RE.fullmatch(reference) or not reference.upper().startswith("CREA-"):
            raise ValueError(f"non-CREA row admitted: {reference}")
        if reference in seen:
            raise ValueError(f"duplicate Creative Europe reference: {reference}")
        seen.add(reference)
        if row.get("exact_call_identifier") is not None or row.get("current_status_label") is not None:
            raise ValueError(f"Creative Europe index invented exact/current evidence: {reference}")
        if row.get("requires_exact_call_evidence") is not True or row.get("requires_reconcile") is not True:
            raise ValueError(f"Creative Europe exact-evidence gate missing: {reference}")
        if row.get("requires_funding_tenders_structured_reconcile") is not True:
            raise ValueError(f"Creative Europe F&T reconcile gate missing: {reference}")
        for key in MATERIAL_FLAGS:
            if row.get(key) is not False:
                raise ValueError(f"Creative Europe row became authorizing: {reference} {key}")
        if row.get("raw_sha256") != raw_hash:
            raise ValueError(f"Creative Europe raw provenance drift: {reference}")
        semantic_fp = str(row.get("semantic_fingerprint") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", semantic_fp):
            raise ValueError(f"Creative Europe semantic fingerprint invalid: {reference}")
