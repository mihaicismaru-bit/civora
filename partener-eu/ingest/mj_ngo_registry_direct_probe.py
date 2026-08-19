#!/usr/bin/env python3
"""Direct fallback probe for the Ministry of Justice NGO register XLSX.

Uses the latest currently published machine-readable Foundations resource known
on data.gov.ro (06.07.2026). This is a fallback for CKAN API timeouts; source
refresh is expected to replace the URL when a newer Foundations resource appears.
"""
from __future__ import annotations

import io
import json
import re
import ssl
import sys
import unicodedata
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

URL = "https://data.gov.ro/dataset/1dd0b5c0-5fa4-4780-a7b8-8a03cd377a3f/resource/5c19d64c-c3cd-4309-8ca5-29044e3c3ccb/download/06_07_2026fundatii.xlsx"
TARGET = "FUNDATIA ANTREPRENORIAT SOCIAL"
UA = "PARTENER.EU-CIVORA-MJ-ONG-Probe/1.0 (+https://partener.eu)"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", s).strip()).upper()


def col_num(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "A1").group(0)
    n = 0
    for c in letters:
        n = n * 26 + ord(c) - 64
    return n


def rows_from_xlsx(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", NS)))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rid_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        first = wb.find("m:sheets/m:sheet", NS)
        rid = first.attrib[f"{{{rid_ns}}}id"]
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.attrib["Target"] for r in rels if r.attrib.get("Id") == rid)
        path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        sheet = ET.fromstring(z.read(path))
        out = []
        for row in sheet.findall(".//m:sheetData/m:row", NS):
            vals, last = [], 0
            for cell in row.findall("m:c", NS):
                col = col_num(cell.attrib.get("r", "A1"))
                while last + 1 < col:
                    vals.append("")
                    last += 1
                typ = cell.attrib.get("t")
                v = cell.find("m:v", NS)
                value = "" if v is None else (v.text or "")
                if typ == "s" and value:
                    value = shared[int(value)]
                elif typ == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                vals.append(value)
                last = col
            out.append(vals)
        return out


def main() -> int:
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    with urllib.request.urlopen(req, timeout=90, context=ssl.create_default_context()) as r:
        data = r.read(10_000_000)
    rows = rows_from_xlsx(data)
    wanted = norm(TARGET)
    hit_i = next((i for i, row in enumerate(rows) if any(wanted == norm(v) or wanted in norm(v) for v in row if v)), None)
    if hit_i is None:
        print(json.dumps({"status": "NOT_FOUND", "sourceUrl": URL}, ensure_ascii=False, indent=2))
        return 2
    header = None
    for i in range(max(0, hit_i - 15), hit_i):
        joined = norm(" ".join(rows[i]))
        if "DENUM" in joined and ("JUDET" in joined or "LOCALIT" in joined or "ADRESA" in joined):
            header = rows[i]
    hit = rows[hit_i]
    if header:
        width = max(len(header), len(hit))
        fields = {(header[k] if k < len(header) and header[k] else f"col_{k+1}"): (hit[k] if k < len(hit) else "") for k in range(width)}
    else:
        fields = {f"col_{i+1}": value for i, value in enumerate(hit)}
    print(json.dumps({
        "status": "OK",
        "source": "Ministerul Justitiei via data.gov.ro",
        "resource": "Fundatii 06.07.2026.xlsx",
        "sourceUrl": URL,
        "rowIndex": hit_i + 1,
        "fields": fields,
        "governancePublicInstant": False,
        "governanceContact": "ongmj@just.ro"
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
