#!/usr/bin/env python3
"""Fail-closed European Urban Initiative Portico call-index adapter.

Portico's call-for-proposals index is useful discovery evidence for candidate
call titles, visible lifecycle labels, deadlines and detail links. It is not
sufficient evidence for a material PARTENER.EU call fact. In particular, an
"Open" label on the index MUST NOT authorize OPEN_CALL. Promotion requires an
exact call identifier, a current exact official detail/application endpoint,
explicit material evidence and semantic reconciliation against previous/LKG
state.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

ADAPTER_ID = "EUI_CALLS_V1"
PARSER_VERSION = "EUI_CALLS_V2"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "EUROPEAN_URBAN_INITIATIVE"
AUTHORITY_CLASS = "EUROPEAN_URBAN_INITIATIVE_PORTICO"
OBSERVATION_STATE = "CALL_INDEX_DISCOVERY"
EUI_AUTHORITY_LABEL = "European Urban Initiative"
STATUS_LABELS = {"Open", "Upcoming", "Closed"}
GENERIC_TEXT = {
    "Status", "Filters", "Filters reset", "Call for Proposals",
    "Find out the different calls in urban development", "Find out more",
    "Open", "Upcoming", "Closed",
}


class _EventParser(HTMLParser):
    """Capture visible text/link events in document order without a DOM dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, str | None]] = []
        self._link_href: str | None = None
        self._link_parts: list[str] | None = None
        self._suppressed_depth = 0

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
            values = self._attrs(attrs)
            self._link_href = values.get("href") or None
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


def _parse(raw: bytes) -> _EventParser:
    parser = _EventParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def _value(event: dict[str, str | None]) -> str:
    return str(event.get("value") or "").strip()


def _nearest_title(events: list[dict[str, str | None]], status_index: int) -> str | None:
    # A Portico card renders title immediately before its lifecycle label. Bound
    # the look-back so menus/filter labels cannot become titles after layout drift.
    for idx in range(status_index - 1, max(-1, status_index - 7), -1):
        value = _value(events[idx])
        if not value or value in GENERIC_TEXT:
            continue
        if value.lower().startswith("deadline date") or value.startswith("By "):
            continue
        return value
    return None


def _candidate_detail_url(segment: list[dict[str, str | None]], authority_url: str) -> str | None:
    for event in segment:
        if event.get("kind") != "link":
            continue
        if "find out more" not in _value(event).lower():
            continue
        href = str(event.get("href") or "").strip()
        if not href:
            return None
        return urljoin(authority_url, href)
    return None


def _owner_label(segment: list[dict[str, str | None]]) -> str | None:
    # Use the first explicit card-owner label. Looking for EUI anywhere in the
    # remainder of the page can incorrectly capture a non-EUI final card because
    # the Portico footer itself names the European Urban Initiative.
    for event in segment:
        value = _value(event)
        if value.startswith("By "):
            return value[3:].strip() or None
    return None


def _deadline_candidate(segment: list[dict[str, str | None]]) -> str | None:
    for idx, event in enumerate(segment):
        value = _value(event)
        if not value.lower().startswith("deadline date"):
            continue
        suffix = value.split(":", 1)[1].strip() if ":" in value else ""
        if suffix:
            return f"Deadline date : {suffix}"
        # Portico currently renders the label and date in adjacent text nodes.
        # Bind only the immediate next text node to avoid pulling unrelated copy.
        if idx + 1 < len(segment) and segment[idx + 1].get("kind") == "text":
            next_value = _value(segment[idx + 1])
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", next_value):
                return f"Deadline date : {next_value}"
        return value
    return None


def extract_call_candidates(raw: bytes, *, authority_url: str) -> list[dict[str, str | None]]:
    """Extract EUI-owned index cards as non-authorizing discovery candidates."""
    events = _parse(raw).events
    status_indexes = [i for i, event in enumerate(events) if _value(event) in STATUS_LABELS]
    rows: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()

    for pos, status_index in enumerate(status_indexes):
        next_status = status_indexes[pos + 1] if pos + 1 < len(status_indexes) else len(events)
        segment = events[status_index + 1:next_status]
        if _owner_label(segment) != EUI_AUTHORITY_LABEL:
            continue
        title = _nearest_title(events, status_index)
        status = _value(events[status_index])
        if not title or status not in STATUS_LABELS:
            continue
        deadline = _deadline_candidate(segment)
        detail_url = _candidate_detail_url(segment, authority_url)
        dedup_key = (title, status, deadline, detail_url)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        rows.append({
            "title": title,
            "status_candidate": status,
            "deadline_candidate": deadline,
            "detail_url_candidate": detail_url,
        })
    return rows


def normalize_call_index(raw: bytes, *, authority_url: str, fetched_at: str, run_id: str,
                         raw_hash: str | None = None) -> dict[str, Any]:
    raw_hash = raw_hash or sha256_bytes(raw)
    rows = extract_call_candidates(raw, authority_url=authority_url)
    records: list[dict[str, Any]] = []

    for row in rows:
        semantic = {
            "title": row["title"],
            "status_candidate": row["status_candidate"],
            "deadline_candidate": row["deadline_candidate"],
            "detail_url_candidate": row["detail_url_candidate"],
            "authority_url": authority_url,
        }
        records.append({
            "schema": "PARTENER_EU_EUI_CALL_INDEX_OBSERVATION_V1",
            "adapter_id": ADAPTER_ID,
            "source_family": SOURCE_FAMILY,
            "programme_family": PROGRAMME_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            **semantic,
            "exact_call_identifier": None,
            "current_status_label": None,
            "observation_state": OBSERVATION_STATE,
            "material_fact_use": False,
            "publish_authorized": False,
            "open_call_authorized": False,
            "requires_exact_call_evidence": True,
            "requires_reconcile": True,
            "fetched_at": fetched_at,
            "raw_hash": raw_hash,
            "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
            "parser_version": PARSER_VERSION,
            "run_id": run_id,
            "missing_for_open_confirmation": [
                "exact call/topic identifier",
                "current exact official call/application endpoint",
                "explicit current status evidence at that endpoint",
                "semantic reconciliation against previous observation/LKG",
            ],
        })

    batch = {
        "schema": "PARTENER_EU_EUI_CALL_INDEX_BATCH_V1",
        "adapter_id": ADAPTER_ID,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": authority_url,
        "observation_state": OBSERVATION_STATE,
        "records": records,
        "record_count": len(records),
        "fetched_at": fetched_at,
        "raw_hash": raw_hash,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "material_fact_use": False,
        "publish_authorized": False,
        "open_call_authorized": False,
        "requires_reconcile": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    validate_call_index_batch(batch)
    return batch


def validate_call_index_batch(batch: dict[str, Any]) -> None:
    if batch.get("schema") != "PARTENER_EU_EUI_CALL_INDEX_BATCH_V1":
        raise ValueError("EUI call-index schema mismatch")
    if batch.get("adapter_id") != ADAPTER_ID:
        raise ValueError("EUI call-index adapter id mismatch")
    if batch.get("parser_version") != PARSER_VERSION:
        raise ValueError("EUI call-index parser version mismatch")
    if batch.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("EUI call-index observation-state drift")
    if batch.get("publication_effect") != "NONE" or batch.get("canonical_corpus_mutation") is not False:
        raise ValueError("EUI call index attempted canonical/public mutation")
    if batch.get("material_fact_use") is not False or batch.get("publish_authorized") is not False:
        raise ValueError("EUI call index became material/publishing")
    if batch.get("open_call_authorized") is not False:
        raise ValueError("EUI call index attempted OPEN authorization")

    raw_hash = batch.get("raw_hash")
    if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("EUI call-index raw hash missing or invalid")

    for row in batch.get("records", []):
        title = row.get("title")
        if not title:
            raise ValueError("EUI call-index observation missing title")
        if row.get("adapter_id") != ADAPTER_ID:
            raise ValueError(f"EUI call-index adapter drift: {title}")
        if row.get("parser_version") != PARSER_VERSION or row.get("raw_hash") != raw_hash:
            raise ValueError(f"EUI call-index provenance drift: {title}")
        if row.get("observation_state") != OBSERVATION_STATE:
            raise ValueError(f"EUI call-index row state drift: {title}")
        if row.get("current_status_label") is not None or row.get("exact_call_identifier") is not None:
            raise ValueError(f"EUI call index invented exact/current evidence: {title}")
        if row.get("material_fact_use") is not False or row.get("publish_authorized") is not False:
            raise ValueError(f"EUI call index leaked material fact: {title}")
        if row.get("open_call_authorized") is not False:
            raise ValueError(f"EUI call index auto-authorized OPEN: {title}")
        if row.get("requires_exact_call_evidence") is not True or row.get("requires_reconcile") is not True:
            raise ValueError(f"EUI call-index evidence/reconcile gate missing: {title}")
        if row.get("status_candidate") not in STATUS_LABELS:
            raise ValueError(f"EUI call-index status candidate invalid: {title}")
