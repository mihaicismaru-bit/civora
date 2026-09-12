#!/usr/bin/env python3
"""Official Interreg IPA Romania-Serbia planned-calls calendar acquisition.

This is programming / market intelligence only. The official programme page and
its latest linked XLSX calendar are acquired with bounded provenance. Workbook
content is preserved for analysis, but nothing in this module can authorize an
OPEN/CLOSED call, deadline, budget, eligibility, publication, distribution, or
alert.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any, Callable

SCHEMA = "PARTENER_EU_INTERREG_RO_RS_CALLS_PLANNING_V1"
PARSER_VERSION = "INTERREG_RO_RS_CALLS_PLANNING_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_IPA_RO_RS_2021_2027"
AUTHORITY_CLASS = "T1_OFFICIAL_PROGRAMME_CALLS_PLANNING_CALENDAR"
OBSERVATION_STATE = "PLANNED"
INDEX_URL = "https://romania-serbia.net/implementation/calls-for-proposals-calendar/"
ALLOWED_HOSTS = ("romania-serbia.net", "www.romania-serbia.net")
MAX_BODY = 12_000_000
MAX_CELLS = 5_000
MAX_PREVIEW_ROWS = 200
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
    "canonical_corpus_mutation",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def host_allowed(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    return host in {value.casefold() for value in ALLOWED_HOSTS}


def assert_https_official(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.casefold() != "https" or not host_allowed(url):
        raise ValueError(f"Interreg RO-RS planning source left the official HTTPS authority: {url}")


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_href: str | None = None
        self.current_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript"}:
            self.suppressed += 1
            return
        if lowered == "a" and not self.suppressed:
            values = {k.casefold(): v for k, v in attrs}
            self.current_href = values.get("href")
            self.current_parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)
            return
        if lowered == "a" and self.current_href is not None:
            text = " ".join(" ".join(self.current_parts).split())
            self.anchors.append((self.current_href, html.unescape(text)))
            self.current_href = None
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.current_href is not None and not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.current_parts.append(value)


CALENDAR_LABEL = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+Calls\s+planning\s+timetable", re.IGNORECASE)


def discover_latest_calendar(index_raw: bytes, *, base_url: str = INDEX_URL) -> dict[str, str]:
    parser = AnchorParser()
    parser.feed(index_raw.decode("utf-8", errors="replace"))
    candidates: list[tuple[dt.date, str, str]] = []
    for href, label in parser.anchors:
        match = CALENDAR_LABEL.search(" ".join(label.split()))
        if not match:
            continue
        absolute = urllib.parse.urljoin(base_url, href)
        assert_https_official(absolute)
        if not urllib.parse.urlparse(absolute).path.casefold().endswith(".xlsx"):
            raise ValueError(f"latest planned-calls calendar is not an XLSX resource: {absolute}")
        parsed_date = dt.datetime.strptime(match.group("date"), "%d.%m.%Y").date()
        candidates.append((parsed_date, label.strip(), absolute))
    if not candidates:
        raise ValueError("official RO-RS calls calendar page exposes no dated XLSX planning timetable")
    parsed_date, label, url = max(candidates, key=lambda row: row[0])
    return {
        "calendar_date": parsed_date.isoformat(),
        "calendar_label": label,
        "calendar_url": url,
    }


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    assert_https_official(url)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream",
            "Accept-Language": "en,ro;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(MAX_BODY + 1)
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
            "bytes": len(raw),
        }
    if len(raw) > MAX_BODY:
        raise ValueError(f"official RO-RS planning response exceeds {MAX_BODY} bytes")
    if meta["http_status"] != 200:
        raise ValueError(f"official RO-RS planning source returned HTTP {meta['http_status']}")
    assert_https_official(meta["final_url"])
    return raw, meta


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    values: list[str] = []
    for si in root.findall("{*}si"):
        parts = [node.text or "" for node in si.iter() if node.tag.endswith("}t") or node.tag == "t"]
        values.append("".join(parts))
    return values


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = str(cell.attrib.get("t") or "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t") or node.tag == "t").strip()
    value_node = cell.find("{*}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared[int(value)].strip()
        except (ValueError, IndexError):
            raise ValueError("XLSX shared-string index is invalid") from None
    return value


def parse_xlsx(raw: bytes) -> dict[str, Any]:
    if not raw.startswith(b"PK"):
        raise ValueError("planned-calls workbook is not an XLSX/ZIP payload")
    rows_preview: list[dict[str, Any]] = []
    normalized_cells: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared = _shared_strings(zf)
        sheet_paths = sorted(
            name for name in zf.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        if not sheet_paths:
            raise ValueError("planned-calls workbook contains no worksheets")
        for sheet_index, path in enumerate(sheet_paths, start=1):
            root = ET.fromstring(zf.read(path))
            for row in root.findall(".//{*}row"):
                row_values: list[dict[str, str]] = []
                for cell in row.findall("{*}c"):
                    ref = str(cell.attrib.get("r") or "")
                    value = " ".join(_cell_value(cell, shared).split())
                    if not value:
                        continue
                    normalized_cells.append((str(sheet_index), ref, value))
                    if len(normalized_cells) > MAX_CELLS:
                        raise ValueError(f"planned-calls workbook exceeds {MAX_CELLS} non-empty cells")
                    row_values.append({"cell": ref, "value": value})
                if row_values and len(rows_preview) < MAX_PREVIEW_ROWS:
                    rows_preview.append({
                        "sheet_index": sheet_index,
                        "row": int(row.attrib.get("r") or 0),
                        "cells": row_values,
                    })
    return {
        "sheet_count": len(sheet_paths),
        "nonempty_cell_count": len(normalized_cells),
        "rows_preview": rows_preview,
        "normalized_cells_sha256": sha256_json(normalized_cells),
    }


def _receipt(url: str, raw: bytes, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_url": url,
        "final_url": str(meta.get("final_url") or meta.get("requested_url") or url),
        "http_status": int(meta.get("http_status") or meta.get("status") or 0),
        "content_type": str(meta.get("content_type") or ""),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "authority_class": AUTHORITY_CLASS,
    }


def _base(*, run_id: str, fetched_at: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme": "Interreg IPA Romania-Serbia Programme 2021-2027",
        "authority_class": AUTHORITY_CLASS,
        "authority_url": INDEX_URL,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "observation_state": OBSERVATION_STATE,
        "market_intelligence_only": True,
        "planning_evidence_non_authorizing": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
    }
    payload.update({flag: False for flag in MATERIAL_FLAGS})
    return payload


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    evidence = _base(run_id=run_id, fetched_at=observed)
    raws: dict[str, bytes] = {}
    try:
        index_raw, index_meta = fetcher(INDEX_URL)
        raws["index"] = index_raw
        if int(index_meta.get("http_status") or index_meta.get("status") or 0) != 200:
            raise ValueError("official RO-RS planning index is not HTTP 200")
        assert_https_official(str(index_meta.get("final_url") or INDEX_URL))
        discovery = discover_latest_calendar(index_raw)

        workbook_raw, workbook_meta = fetcher(discovery["calendar_url"])
        raws["workbook"] = workbook_raw
        if int(workbook_meta.get("http_status") or workbook_meta.get("status") or 0) != 200:
            raise ValueError("official RO-RS planning workbook is not HTTP 200")
        assert_https_official(str(workbook_meta.get("final_url") or discovery["calendar_url"]))
        workbook = parse_xlsx(workbook_raw)

        semantic = {
            "programme_family": PROGRAMME_FAMILY,
            "calendar_date": discovery["calendar_date"],
            "calendar_url": discovery["calendar_url"],
            "normalized_cells_sha256": workbook["normalized_cells_sha256"],
        }
        evidence.update({
            "source_health_state": "HEALTHY",
            "lkg_required": False,
            "latest_calendar": {
                **discovery,
                "workbook_sha256": sha256_bytes(workbook_raw),
                **workbook,
            },
            "provenance": {
                "index": _receipt(INDEX_URL, index_raw, index_meta),
                "workbook": _receipt(discovery["calendar_url"], workbook_raw, workbook_meta),
            },
            "semantic_fingerprint": sha256_json(semantic),
        })
    except Exception as exc:
        evidence.update({
            "source_health_state": "DEGRADED",
            "lkg_required": True,
            "latest_calendar": None,
            "semantic_fingerprint": None,
            "failure_class": type(exc).__name__,
            "failure": str(exc),
        })
    return evidence, raws


def validate(evidence: dict[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ValueError("RO-RS planning schema/parser drift")
    if evidence.get("observation_state") != "PLANNED":
        raise ValueError("RO-RS planning evidence must remain PLANNED")
    if not evidence.get("market_intelligence_only") or not evidence.get("planning_evidence_non_authorizing"):
        raise ValueError("RO-RS planning evidence lost non-authorizing boundary")
    if any(bool(evidence.get(flag)) for flag in MATERIAL_FLAGS):
        raise ValueError("RO-RS planning evidence widened material authorization")
    if evidence.get("publication_effect") != "NONE":
        raise ValueError("RO-RS planning evidence cannot publish")
    if evidence.get("source_health_state") == "HEALTHY":
        calendar = evidence.get("latest_calendar") or {}
        if not calendar.get("calendar_date") or not calendar.get("calendar_url") or not calendar.get("workbook_sha256"):
            raise ValueError("HEALTHY RO-RS planning evidence lacks exact workbook provenance")
        assert_https_official(str(calendar["calendar_url"]))
        if evidence.get("lkg_required") is not False:
            raise ValueError("HEALTHY RO-RS planning evidence cannot require LKG")
    elif evidence.get("source_health_state") == "DEGRADED":
        if evidence.get("latest_calendar") is not None or evidence.get("lkg_required") is not True:
            raise ValueError("DEGRADED RO-RS planning evidence must clear current calendar truth and require LKG")
    else:
        raise ValueError("unexpected RO-RS planning source health state")


def write_output(out_dir: pathlib.Path, evidence: dict[str, Any], raws: dict[str, bytes]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "interreg-ro-rs-calls-planning.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    if "index" in raws:
        (raw_dir / "calls-planning-index.html").write_bytes(raws["index"])
    if "workbook" in raws:
        (raw_dir / "calls-planning-latest.xlsx").write_bytes(raws["workbook"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fetched-at")
    args = parser.parse_args()
    evidence, raws = collect(run_id=args.run_id, fetched_at=args.fetched_at)
    validate(evidence)
    write_output(args.output_dir, evidence, raws)
    print(json.dumps({
        "source_health_state": evidence["source_health_state"],
        "observation_state": evidence["observation_state"],
        "latest_calendar_date": (evidence.get("latest_calendar") or {}).get("calendar_date"),
        "latest_calendar_url": (evidence.get("latest_calendar") or {}).get("calendar_url"),
        "semantic_fingerprint": evidence.get("semantic_fingerprint"),
        "lkg_required": evidence.get("lkg_required"),
        "publication_effect": evidence.get("publication_effect"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
