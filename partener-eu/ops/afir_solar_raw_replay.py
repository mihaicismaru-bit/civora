#!/usr/bin/env python3
"""Read-only AFIR solar 3/2026 original-XLSX row replay; never authorizes a call."""
import argparse
from decimal import Decimal
from datetime import datetime, timedelta
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "partener-eu/validation/afir-solar-3-2026-aggregate-observation.json"
ACQUIRE = ROOT / "partener-eu/ingest/afir_selection_results_acquire.py"
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s).casefold())
                   if not unicodedata.combining(c))


def number(s):
    d = Decimal(str(s).replace(",", ""))
    if not d.is_finite() or d < 0 or d != d.to_integral_value():
        raise ValueError("Nonintegral source amount/serial")
    return int(d)


def totals(raw, category, expected, observation, collector):
    collector.validate_workbook(raw)
    with zipfile.ZipFile(BytesIO(raw)) as z:
        strings = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in i.findall(".//x:t", NS))
                  for i in strings.findall("x:si", NS)]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = {}
        for row in sheet.findall(".//x:sheetData/x:row", NS):
            n = int(row.attrib["r"])
            if n in rows:
                raise ValueError("Duplicate worksheet row")
            cells = {}
            for c in row.findall("x:c", NS):
                match = re.fullmatch(r"([A-Z]+)(\d+)", c.attrib["r"])
                if not match or int(match[2]) != n or match[1] in cells:
                    raise ValueError("Duplicate/invalid cell")
                v = c.find("x:v", NS)
                value = v.text if v is not None else None
                cells[match[1]] = (value, c.attrib.get("t"), c.find("x:f", NS) is not None)
            rows[n] = cells
    session = "Sesiunea nr. " + observation["workbook_internal_session_identifier"] + " Masura FM"
    if sum(norm(s) == norm(session) for s in shared) != 1:
        raise ValueError("Workbook session header mismatch")
    # AFIR's official index delegates two distinct 3/2026 reports, but the
    # original workbooks use the internal FM-06/26 code. Verify their common
    # dated reporting period and category, WITHOUT equating those two IDs or
    # claiming an exact funding-call identity.
    period = observation["report_period"].split("–")
    if len(period) != 2:
        raise ValueError("Invalid pinned index report period")
    labels = [norm(s) for s in shared]
    expected_group = ("lista proiectelor selectate pentru finantare"
                      if category == "Selectate" else "lista proiectelor nefinantate")
    if labels.count(expected_group) != 1:
        raise ValueError("Workbook category mismatches official index delegation")
    count_headers = [s for s in labels
                     if s.startswith("numarul proiectelor selectate pentru finantare:")]
    if len(count_headers) != 1:
        raise ValueError("Missing or duplicate dated selection header")
    dated = re.fullmatch(
        r"numarul proiectelor selectate pentru finantare:\s*\((\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})\):\s*(\d+)",
        count_headers[0],
    )
    if (dated is None or
        (dated[1], dated[2], int(dated[3])) !=
        (period[0], period[1], observation["aggregates"]["selected_projects"])):
        raise ValueError("Original workbook/report-index date range or count mismatch")
    for snippet, target in (
        ("numarul proiectelor depuse :", observation["aggregates"]["submitted_projects"]),
        ("valoarea publica totala a proiectelor depuse :", observation["aggregates"]["submitted_public_value_eur"]),
        ("suma alocata pe sesiune:", observation["aggregates"]["session_allocation_eur"]),
        ("valoarea publica totala a proiectelor selectate pentru finantare :", observation["aggregates"]["selected_public_value_eur"]),
    ):
        source = [norm(s) for s in shared if norm(s).startswith(snippet)]
        if len(source) != 1:
            raise ValueError("Missing original aggregate header")
        m = re.search(r"([\d,]+(?:\.\d\d)?)\s*(?:euro)?\s*$", source[0])
        if not m or number(m[1]) != target:
            raise ValueError("Workbook header amount mismatch")
    start, end, money = (20, 79, "Z") if category == "Selectate" else (17, 26, "Y")
    serial, values = [], []
    for i in range(start, end + 1):
        row = rows.get(i, {})
        for col in ("B", money):
            if col not in row or row[col][0] is None or row[col][1] or row[col][2]:
                raise ValueError("Missing/formula/non-numeric original row")
        serial.append(number(row["B"][0]))
        values.append(number(row[money][0]))
    if serial != list(range(1, expected["count"] + 1)) or any(v <= 0 for v in values):
        raise ValueError("Noncontiguous serials or invalid original values")
    if sum(values) != number(expected["total_public_eur"]):
        raise ValueError("Project-row sum differs from pinned source")
    footer_row, count_col, total_col = (80, "N", "AA") if category == "Selectate" else (28, "N", "Y")
    footer = rows[footer_row]
    if number(footer[count_col][0]) != expected["count"] or number(footer[total_col][0]) != sum(values):
        raise ValueError("Original worksheet footer mismatch")
    if category != "Selectate":
        cell = rows[16]["B"][0]
        if cell is None or "neeligibile" not in norm(shared[int(cell)]):
            raise ValueError("Unfinanced source class is not proven")
    return len(serial), sum(values)


def utc_stamp(value):
    # Evidence timestamps are comparable UTC instants, never naive local times.
    if not isinstance(value, str):
        raise ValueError("Missing UTC provenance timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("Non-UTC provenance timestamp")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid UTC provenance timestamp") from exc
    return parsed


def replay(directory):
    d = Path(directory)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    obs = json.loads(OBS.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("acq", ACQUIRE)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    if manifest["status"] != "RAW_CAPTURED_PENDING_RECONCILIATION" or len(manifest["documents"]) != 2:
        raise ValueError("Incomplete original source pair")
    for record in (manifest, obs):
        if record["source_family"] != "AFIR" or record["authority_class"] != "OFFICIAL_AFIR_REPORT_INDEX_DELEGATED_DOCUMENT":
            raise ValueError("Untrusted authority")
        if any(record[k] is not False for k in ("open_call_authorized", "publish_authorized", "material_fact_use")):
            raise ValueError("Illegal publication/OPEN_CALL")
    if obs["session_identity_reconciliation"] != "REQUIRED":
        raise ValueError("Index/workbook identity NOT independently reconciled")
    # Bind a fresh live capture to the SAME official authority, collector,
    # programme and per-run observation scope as its pinned baseline. Do not
    # require a current index hash to equal a historical hash: AFIR may add
    # unrelated rows without changing the exact delegated session.
    # Historical v1 provenance is replayable only at the exact pinned run;
    # all subsequent receipts must use the strict-MIME v2 acquisition.
    parser_version = manifest.get("parser_version")
    pinned_legacy = (parser_version == obs["raw_acquisition_parser_version"]
                     and manifest.get("run_id") == obs["run_id"])
    if (manifest.get("schema") != "PARTENER_EU_AFIR_SELECTION_RAW_EVIDENCE_V1"
        or manifest.get("programme") != obs["programme"]
        or (parser_version != collector.PARSER_VERSION and not pinned_legacy)
        or manifest.get("official_index_url") != obs["official_index_url"]
        or manifest.get("official_notice_url") != obs["official_notice_url"]
        or manifest.get("observation_state") != "SELECTION_RESULTS_DISCOVERY_PENDING_RECONCILIATION"
        or not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]):
        raise ValueError("Unbound AFIR acquisition manifest provenance")
    acquired_at = utc_stamp(manifest["fetched_at"])
    index_meta = manifest["official_index"]
    index_at = utc_stamp(index_meta["fetched_at"])
    if (index_at < acquired_at or index_meta["url"] != obs["official_index_url"]
        or not collector.accepted_media_type("html", index_meta["content_type"])):
        raise ValueError("Untrusted official index provenance")
    index = (d / "afir-selection-index.raw.html").read_bytes()
    if (len(index) != index_meta["bytes"]
        or hashlib.sha256(index).hexdigest() != index_meta["sha256"]):
        raise ValueError("Official index raw hash/length mismatch")
    # Only the original pinned acquisition is required to retain its exact
    # historical index. Later live recaptures may have unrelated HTML changes.
    if (manifest["run_id"] == obs["run_id"]
        and index_meta["sha256"] != obs["official_index_sha256"]):
        raise ValueError("Pinned original index identity mismatch")
    delegated = collector.parse_index(index)
    result = {}
    if {x["category"] for x in manifest["documents"]} != set(collector.CATEGORIES):
        raise ValueError("Unverified original report categories")
    for source in manifest["documents"]:
        cat = source["category"]
        pinned = obs["source_documents"][cat]
        name = "solar-3-2026-" + ("selectate" if cat == "Selectate" else "nefinantate") + ".raw.xlsx"
        if (source["file"] != name or source["final_url"] != delegated[cat]
            or source["requested_url"] != pinned["source_url"] or source["sha256"] != pinned["sha256"]
            or source["run_id"] != manifest["run_id"] or source["parser_version"] != parser_version
            or source.get("source_family") != manifest["source_family"]
            or source.get("authority_class") != manifest["authority_class"]
            or source.get("observation_state") != manifest["observation_state"]
            or source.get("status") != "RAW_FETCHED_NOT_RECONCILED"
            or not collector.accepted_media_type("xlsx", source["content_type"])
            or utc_stamp(source["fetched_at"]) < index_at):
            raise ValueError("Unpinned raw delegation/provenance")
        if (manifest["run_id"] == obs["run_id"]
            and (source["fetched_at"] != pinned["fetched_at"] or source["bytes"] != pinned["bytes"])):
            raise ValueError("Pinned original document provenance mismatch")
        raw = (d / name).read_bytes()
        if len(raw) != source["bytes"] or hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Original XLSX bytes changed")
        result[cat] = totals(raw, cat, pinned, obs, collector)
    if (sum(x[0] for x in result.values()) != obs["aggregates"]["submitted_projects"]
        or sum(x[1] for x in result.values()) != obs["aggregates"]["submitted_public_value_eur"]):
        raise ValueError("Cross-report source totals differ")
    return {"status": "RAW_ROWS_REPLAYED_NOT_PUBLISHED", "run_id": manifest["run_id"],
            "selected": result["Selectate"][0], "unfunded": result["Nefinanțate"][0],
            "selected_eur": result["Selectate"][1], "unfunded_eur": result["Nefinanțate"][1],
            "report_index_document_binding": "CATEGORY_DELEGATION_AND_PERIOD_VERIFIED",
            "index_session_identifier": obs["index_session_identifier"],
            "workbook_internal_session_identifier": obs["workbook_internal_session_identifier"],
            "identifier_alias_established": False,
            "session_identity_reconciled": False, "publish_authorized": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--evidence-dir", required=True)
    args = p.parse_args()
    print(json.dumps(replay(args.evidence_dir), sort_keys=True))
