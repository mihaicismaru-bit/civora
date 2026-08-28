#!/usr/bin/env python3
"""Fail-closed European Solidarity Corps annual-call action router.

The European Youth Portal annual call page is authoritative for the programme
framework, action labels, indicative/annual deadlines and application routes, but
it is not treated as sufficient evidence that an individual action is currently
OPEN. This adapter therefore emits reconciliation candidates only. Promotion to a
material OPEN_CALL requires a separate, current, exact action/application endpoint
with an action identifier and explicit status evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

PARSER_VERSION = "ESC_ACTION_ROUTER_V2"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "EUROPEAN_SOLIDARITY_CORPS"
AUTHORITY_CLASS = "EUROPEAN_YOUTH_PORTAL"
OBSERVATION_STATE = "CALL_FRAMEWORK"

CALL_ID_RE = re.compile(r"\b(EAC/A\d+/\d{4})\b", re.IGNORECASE)
OJ_ID_RE = re.compile(r"\b(C/\d{4}/\d+)\b", re.IGNORECASE)
CALL_YEAR_PATTERNS = (
    re.compile(r"\bCALL\s+FOR\s+PROPOSALS\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(20\d{2})\s+(?:EUROPEAN\s+SOLIDARITY\s+CORPS\s+)?CALL(?:\s+FOR\s+PROPOSALS)?\b", re.IGNORECASE),
)


class _EscPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.rows: list[list[str]] = []
        self._in_row = False
        self._cell_parts: list[str] | None = None
        self._row_cells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif self._in_row and tag in {"td", "th"}:
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_row and tag in {"td", "th"} and self._cell_parts is not None:
            value = " ".join(" ".join(self._cell_parts).split())
            self._row_cells.append(value)
            self._cell_parts = None
        elif tag == "tr" and self._in_row:
            if any(cell for cell in self._row_cells):
                self.rows.append(self._row_cells[:])
            self._row_cells = []
            self._in_row = False
            self._cell_parts = None

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._cell_parts is not None:
            self._cell_parts.append(value)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse(raw: bytes) -> _EscPageParser:
    parser = _EscPageParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def _framework_identifiers(flat_text: str) -> tuple[str | None, str | None, str | None]:
    call = CALL_ID_RE.search(flat_text)
    oj = OJ_ID_RE.search(flat_text)
    # The identifier EAC/A15/2025 is the notice identifier, not the programme
    # call year. The official page explicitly labels this notice as CALL FOR
    # PROPOSALS 2026, so deriving 2025 from the identifier would misclassify the
    # framework. If no explicit programme-call year is present, remain unknown.
    year = None
    for pattern in CALL_YEAR_PATTERNS:
        year_match = pattern.search(flat_text)
        if year_match:
            year = year_match.group(1)
            break
    return (call.group(1).upper() if call else None, oj.group(1).upper() if oj else None, year)


def _looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return (
        "activity type" in joined
        or "deadline" in joined and "where" in joined
        or "tip de activitate" in joined
        or "termen" in joined and "depune" in joined
    )


def _action_key(name: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return token[:120] or "unknown-action"


def extract_action_rows(raw: bytes) -> list[dict[str, str | None]]:
    """Extract annual-call action rows without assigning current OPEN semantics."""
    parser = _parse(raw)
    rows: list[dict[str, str | None]] = []
    for cells in parser.rows:
        cells = [" ".join(cell.split()) for cell in cells if cell.strip()]
        if len(cells) < 2 or _looks_like_header(cells):
            continue
        name = cells[0]
        deadline = cells[1] if len(cells) >= 2 else None
        route = cells[2] if len(cells) >= 3 else None
        # Only accept rows that look like action/deadline records; unrelated layout tables
        # must not become funding observations.
        deadline_signal = bool(
            re.search(r"\b20\d{2}\b|\bcontinuous\b|\brolling\b|\bcontinuu\b", deadline or "", re.IGNORECASE)
        )
        if not deadline_signal:
            continue
        rows.append({
            "action_key": _action_key(name),
            "action_name": name,
            "deadline_candidate": deadline,
            "application_route": route,
        })
    return rows


def normalize_framework(raw: bytes, *, authority_url: str, fetched_at: str, run_id: str,
                        raw_hash: str | None = None) -> dict[str, Any]:
    parser = _parse(raw)
    flat = " ".join(parser.text_parts)
    call_id, oj_id, call_year = _framework_identifiers(flat)
    rows = extract_action_rows(raw)
    raw_hash = raw_hash or sha256_bytes(raw)

    records: list[dict[str, Any]] = []
    for row in rows:
        semantic = {
            "framework_call_identifier": call_id,
            "official_journal_identifier": oj_id,
            "call_year": call_year,
            "action_key": row["action_key"],
            "action_name": row["action_name"],
            "deadline_candidate": row["deadline_candidate"],
            "application_route": row["application_route"],
            "authority_url": authority_url,
        }
        records.append({
            "schema": "PARTENER_EU_ESC_ACTION_OBSERVATION_V1",
            "source_family": SOURCE_FAMILY,
            "programme_family": PROGRAMME_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            **semantic,
            "exact_action_identifier": None,
            "exact_application_endpoint": None,
            "current_status_label": None,
            "observation_state": OBSERVATION_STATE,
            "material_fact_use": False,
            "publish_authorized": False,
            "open_call_authorized": False,
            "requires_exact_action_evidence": True,
            "requires_reconcile": True,
            "fetched_at": fetched_at,
            "raw_hash": raw_hash,
            "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
            "parser_version": PARSER_VERSION,
            "run_id": run_id,
        })

    return {
        "schema": "PARTENER_EU_ESC_ACTION_ROUTER_BATCH_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": authority_url,
        "framework_call_identifier": call_id,
        "official_journal_identifier": oj_id,
        "call_year": call_year,
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
        "missing_for_open_confirmation": [
            "exact action identifier",
            "current authoritative action/application endpoint",
            "explicit current status evidence for that action",
            "semantic reconciliation against previous observation/LKG",
        ],
    }


def validate_framework_batch(batch: dict[str, Any]) -> None:
    if batch.get("schema") != "PARTENER_EU_ESC_ACTION_ROUTER_BATCH_V1":
        raise ValueError("ESC router schema mismatch")
    if batch.get("parser_version") != PARSER_VERSION:
        raise ValueError("ESC router parser version mismatch")
    if not batch.get("framework_call_identifier"):
        raise ValueError("ESC annual framework missing call identifier")
    if not re.fullmatch(r"20\d{2}", str(batch.get("call_year") or "")):
        raise ValueError("ESC annual framework missing explicit programme call year")
    if batch.get("publication_effect") != "NONE" or batch.get("canonical_corpus_mutation") is not False:
        raise ValueError("ESC router attempted canonical/public mutation")
    if batch.get("material_fact_use") is not False or batch.get("publish_authorized") is not False:
        raise ValueError("ESC framework became material/publishing")
    for row in batch.get("records", []):
        if row.get("parser_version") != PARSER_VERSION or row.get("call_year") != batch.get("call_year"):
            raise ValueError(f"ESC action provenance/call-year drift: {row.get('action_name')}")
        if row.get("observation_state") == "OPEN_CALL" or row.get("open_call_authorized") is not False:
            raise ValueError(f"ESC annual framework auto-authorized OPEN: {row.get('action_name')}")
        if row.get("material_fact_use") is not False or row.get("publish_authorized") is not False:
            raise ValueError(f"ESC annual framework leaked material fact: {row.get('action_name')}")
        if not row.get("requires_exact_action_evidence"):
            raise ValueError(f"ESC action lost exact-evidence gate: {row.get('action_name')}")
