#!/usr/bin/env python3
"""AFIR 3/2026 solar >1 MW final selection: original evidence only, no publication."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

INDEX_URL = "https://www.afir.ro/rapoarte/rapoarte-feadr/selectie/"
NOTICE_URL = "https://www.afir.ro/info-la-zi/raport-final-de-selectie-schema-de-energie-solar-peste-1-mw/"
BLOB_HOST = "stportalafirprod.blob.core.windows.net"
PARSER_VERSION = "afir-energy-solar-final-selection-acquisition-v1"
CATEGORIES = ("Selectate", "Nefinanțate")

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()

class ReportTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None
    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"parts": [], "links": []}
        elif tag == "a" and self.cell is not None:
            href = dict(attrs).get("href")
            if href:
                self.cell["links"].append(href)
    def handle_data(self, data):
        if self.cell is not None:
            self.cell["parts"].append(data)
    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None and self.row is not None:
            self.row.append({"text": clean(" ".join(self.cell["parts"])), "links": self.cell["links"]})
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row, self.cell = None, None

def delegated_xlsx_url(href):
    # Delegation is ONLY from the original AFIR report-index table, never
    # from an externally discovered URL or a redirect.
    url = urllib.parse.urljoin(INDEX_URL, href)
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or (p.hostname or "").lower() != BLOB_HOST
        or p.username is not None or p.password is not None
        or p.port not in (None, 443) or p.query or p.fragment
        or not re.fullmatch(r"/media/media/[a-z0-9_-]+/[a-z0-9._-]+\.xlsx", p.path, flags=re.I)):
        raise ValueError("Untrusted AFIR delegated XLSX URL")
    return url

def parse_index(raw):
    parser = ReportTable()
    parser.feed(raw.decode("utf-8-sig", errors="replace"))
    matches = {}
    for row in parser.rows:
        if len(row) < 8:
            continue
        cells = [c["text"] for c in row]
        # The AFIR index also contains other reporting sessions. Ignore
        # unrelated periods, but fail closed on contradictory rows for the
        # exact solar 3/2026 session (type, category, date or delegation).
        if (cells[2].upper() != "ENERGIE"
            or cells[3] != "3" or cells[4] != "2026"
            or "solar peste 1mw" not in cells[5].lower()
            or "15.06.2026" not in cells[5] or "14.08.2026" not in cells[5]):
            continue
        if (cells[0] != "Final" or cells[1] not in CATEGORIES
            or cells[6] != "03.11.2026"):
            raise ValueError("Unverified AFIR final-report category/session/date")
        links = row[7]["links"]
        if len(links) != 1 or cells[1] in matches:
            raise ValueError("Ambiguous or duplicate report link")
        matches[cells[1]] = delegated_xlsx_url(links[0])
    if set(matches) != set(CATEGORIES) or len(set(matches.values())) != 2:
        raise ValueError("Two exact selected/unfunded AFIR reports required")
    return matches

def validate_workbook(raw):
    if not raw.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(BytesIO(raw)):
        raise ValueError("Not original XLSX ZIP bytes")
    with zipfile.ZipFile(BytesIO(raw)) as z:
        infos = z.infolist()
        names = set(z.namelist())
        if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
            raise ValueError("Missing XLSX workbook parts")
        if len(infos) > 1000 or sum(x.file_size for x in infos) > 100_000_000:
            raise ValueError("XLSX expansion limit")
        if any(x.file_size > 30_000_000 or
               (x.file_size > 100_000 and x.file_size > 100 * max(1, x.compress_size))
               for x in infos):
            raise ValueError("Potential decompression bomb")
        if not any(n.startswith("xl/worksheets/") and n.endswith(".xml") for n in names):
            raise ValueError("Missing worksheet")
        if any(x.flag_bits & 1 for x in infos):
            raise ValueError("Encrypted XLSX")
    return True

class NeverRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Untrusted source redirect")

def download_exact(url, max_bytes, kind, *, delegated_urls=()):
    # An Azure path is not sufficient authority: the URL must come from the
    # official index fetched and parsed in THIS acquisition run.
    if kind == "html":
        if url not in (INDEX_URL, NOTICE_URL):
            raise ValueError("Unknown official AFIR HTML source")
    elif kind == "xlsx":
        if url not in delegated_urls or url != delegated_xlsx_url(url):
            raise ValueError("Unverified AFIR XLSX delegation")
    else:
        raise ValueError("Unsupported source content kind")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Unsafe source URL")
    opener = urllib.request.build_opener(
        NeverRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-AFIR-Selection-Receipt/1.0",
        "Accept-Encoding": "identity"})
    with opener.open(request, timeout=25) as res:
        if res.geturl() != url or getattr(res, "status", 200) != 200:
            raise ValueError("Source identity or status mismatch")
        ctype = res.headers.get("Content-Type", "").lower()
        if kind == "html" and "html" not in ctype:
            raise ValueError("AFIR index is not HTML")
        if kind == "xlsx" and ("html" in ctype or "json" in ctype):
            raise ValueError("AFIR XLSX is HTML or JSON")
        raw = res.read(max_bytes + 1)
        length = res.headers.get("Content-Length")
        if not raw or len(raw) > max_bytes or (
            length is not None and (not length.isdigit() or int(length) != len(raw))
        ):
            raise ValueError("Empty/incomplete/oversized source bytes")
        return raw, ctype

def run(outdir, run_id, observed_at):
    if not run_id:
        raise ValueError("Missing run_id")
    root = Path(outdir)
    # Each acquisition must own a fresh evidence directory. An existing path
    # (even an empty one) is a prior run, not a place to overwrite receipts.
    # In particular, a retry must never upload stale XLSX files under a new
    # FETCH_FAILED manifest or mutate an earlier immutable checkpoint.
    root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "PARTENER_EU_AFIR_SELECTION_RAW_EVIDENCE_V1",
        "status": "FETCH_FAILED", "official_index_url": INDEX_URL,
        "official_notice_url": NOTICE_URL, "fetched_at": observed_at,
        "parser_version": PARSER_VERSION, "run_id": str(run_id),
        "source_family": "AFIR", "programme": "FONDUL_MODERNIZARE_ENERGIE_SOLAR",
        "authority_class": "OFFICIAL_AFIR_REPORT_INDEX_DELEGATED_DOCUMENT",
        "observation_state": "SELECTION_RESULTS_DISCOVERY_PENDING_RECONCILIATION",
        "open_call_authorized": False, "publish_authorized": False,
        "material_fact_use": False, "publication_effect": "NONE", "documents": [],
    }
    try:
        raw_index, content_type = download_exact(INDEX_URL, 5_000_000, "html")
        (root / "afir-selection-index.raw.html").write_bytes(raw_index)
        manifest["official_index"] = {
            "url": INDEX_URL, "sha256": hashlib.sha256(raw_index).hexdigest(),
            "bytes": len(raw_index), "content_type": content_type}
        manifest["official_index"]["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        refs = parse_index(raw_index)
        # Both original workbooks must pass delegation, transport and ZIP
        # validation before either is committed into this immutable bundle.
        # A successful partial acquisition is NOT a valid selection report.
        staged = []
        for category in CATEGORIES:
            url = refs[category]
            raw, ctype = download_exact(url, 25_000_000, "xlsx", delegated_urls=tuple(refs.values()))
            validate_workbook(raw)
            fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
            staged.append((category, url, raw, ctype, fetched_at))
        for category, url, raw, ctype, fetched_at in staged:
            fname = "solar-3-2026-" + ("selectate" if category == "Selectate" else "nefinantate") + ".raw.xlsx"
            (root / fname).write_bytes(raw)
            manifest["documents"].append({
                "category": category, "requested_url": url, "final_url": url,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "content_type": ctype, "file": fname,
                "fetched_at": fetched_at, "parser_version": PARSER_VERSION,
                "run_id": str(run_id), "source_family": "AFIR",
                "authority_class": "OFFICIAL_AFIR_REPORT_INDEX_DELEGATED_DOCUMENT",
                "observation_state": "SELECTION_RESULTS_DISCOVERY_PENDING_RECONCILIATION",
                "status": "RAW_FETCHED_NOT_RECONCILED",
            })
        manifest["status"] = "RAW_CAPTURED_PENDING_RECONCILIATION"
    except Exception as exc:
        # Also protect against partial disk writes after both downloads pass:
        # no failed run may retain an apparently complete workbook artifact.
        for partial in root.glob("solar-3-2026-*.raw.xlsx"):
            partial.unlink()
        manifest["documents"] = []
        manifest["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "documents": len(manifest["documents"]),
                      "error": manifest.get("error"), "run_id": str(run_id)}, ensure_ascii=False))
    return 0 if manifest["status"] == "RAW_CAPTURED_PENDING_RECONCILIATION" else 2

if __name__ == "__main__":
    path = os.environ.get("PARTENER_AFIR_SELECTION_EVIDENCE_DIR")
    if not path:
        raise SystemExit("PARTENER_AFIR_SELECTION_EVIDENCE_DIR required")
    raise SystemExit(run(path, os.environ.get("GITHUB_RUN_ID", ""),
                         dt.datetime.now(dt.timezone.utc).isoformat()))
