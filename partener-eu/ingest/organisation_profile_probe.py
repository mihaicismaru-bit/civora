#!/usr/bin/env python3
"""Probe official Romanian public sources for a company/ONG profile by CUI/name.

Current scope:
- ANAF general taxpayer information (v9) for registered address and status.
- Ministry of Justice National NGO Register for current public registry row.

The MJ register is currently published with a reduced public field set; the probe
reports only what is actually present and flags restricted governance fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import re
import ssl
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

ANAF_URL = "https://webservicesp.anaf.ro/PlatitorTvaRest/api/v9/ws/tva"
MJ_REGISTRY = "https://www.just.ro/registrul-national-ong/"
UA = "PARTENER.EU-CIVORA-Organisation-Profile/1.0 (+https://partener.eu)"


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).strip().upper()
    return re.sub(r"\s+", " ", value)


def req(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 35) -> bytes:
    h = {"User-Agent": UA, "Accept-Language": "ro,en;q=0.7"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(r, timeout=timeout, context=ssl.create_default_context()) as resp:
        return resp.read(30_000_000)


def anaf_general(cui: str, query_date: str) -> dict:
    body = json.dumps([{"cui": int(cui), "data": query_date}]).encode("utf-8")
    raw = req(ANAF_URL, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
    payload = json.loads(raw.decode("utf-8"))
    found = payload.get("found") or []
    if not found:
        return {"available": False, "rawStatus": payload.get("cod"), "message": payload.get("message")}
    item = found[0]
    dg = item.get("date_generale") or {}
    social = item.get("adresa_sediu_social") or {}
    fiscal = item.get("adresa_domiciliu_fiscal") or {}
    return {
        "available": True,
        "entity": {
            "cui": str(dg.get("cui") or cui),
            "name": dg.get("denumire"),
            "registrationState": dg.get("stare_inregistrare"),
            "registrationDate": dg.get("data_inregistrare"),
            "legalForm": dg.get("forma_juridica"),
            "organisationForm": dg.get("forma_organizare"),
            "ownershipForm": dg.get("forma_de_proprietate"),
            "caen": dg.get("cod_CAEN"),
            "taxAuthority": dg.get("organFiscalCompetent"),
            "eFactura": dg.get("statusRO_e_Factura"),
        },
        "registeredAddress": {
            "street": social.get("sdenumire_Strada"),
            "number": social.get("snumar_Strada"),
            "locality": social.get("sdenumire_Localitate"),
            "county": social.get("sdenumire_Judet"),
            "postalCode": social.get("scod_Postal"),
            "details": social.get("sdetalii_Adresa"),
            "country": social.get("stara"),
        },
        "fiscalAddress": {
            "street": fiscal.get("ddenumire_Strada"),
            "number": fiscal.get("dnumar_Strada"),
            "locality": fiscal.get("ddenumire_Localitate"),
            "county": fiscal.get("ddenumire_Judet"),
            "postalCode": fiscal.get("dcod_Postal"),
            "details": fiscal.get("ddetalii_Adresa"),
            "country": fiscal.get("dtara"),
        },
        "vat": item.get("inregistrare_scop_Tva") or {},
        "inactive": item.get("stare_inactiv") or {},
    }


def find_foundations_xlsx(page: str) -> str:
    # Prefer links whose nearby anchor text refers to foundations and XLSX/XLS.
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        href = html.unescape(m.group(1)).strip()
        label = norm_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        target = href.lower()
        if "FUND" in label and (target.endswith(".xlsx") or target.endswith(".xls")):
            return urllib.parse.urljoin(MJ_REGISTRY, href)
    # Fallback: inspect surrounding source text around spreadsheet links.
    links = re.findall(r'href=["\']([^"\']+\.(?:xlsx|xls)(?:\?[^"\']*)?)["\']', page, re.I)
    for href in links:
        if "fund" in href.lower():
            return urllib.parse.urljoin(MJ_REGISTRY, html.unescape(href))
    raise RuntimeError("Could not locate Foundations spreadsheet link on MJ registry page")


def xlsx_rows(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        ns = {
            "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        first_sheet = workbook.find("m:sheets/m:sheet", ns)
        rel_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target")
                break
        if not target:
            raise RuntimeError("XLSX first worksheet target missing")
        sheet_path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(sheet_path))
        mns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        out = []
        for row in root.findall(".//m:sheetData/m:row", mns):
            vals = []
            last_col = 0
            for c in row.findall("m:c", mns):
                ref = c.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", ref).group(0)
                col = 0
                for ch in letters:
                    col = col * 26 + (ord(ch) - 64)
                while last_col + 1 < col:
                    vals.append("")
                    last_col += 1
                typ = c.attrib.get("t")
                v = c.find("m:v", mns)
                value = "" if v is None else (v.text or "")
                if typ == "s" and value:
                    value = shared[int(value)]
                elif typ == "inlineStr":
                    value = "".join(t.text or "" for t in c.findall(".//m:t", mns))
                vals.append(value)
                last_col = col
            out.append(vals)
        return out


def mj_lookup(name: str) -> dict:
    page = req(MJ_REGISTRY).decode("utf-8", "ignore")
    url = find_foundations_xlsx(page)
    raw = req(url)
    if raw[:2] != b"PK":
        return {"available": False, "sourceUrl": url, "error": "Foundation spreadsheet is not XLSX/ZIP"}
    rows = xlsx_rows(raw)
    target = norm_text(name)
    hit_index = None
    for i, row in enumerate(rows):
        if any(target == norm_text(cell) or target in norm_text(cell) for cell in row if cell):
            hit_index = i
            break
    if hit_index is None:
        return {"available": False, "sourceUrl": url, "error": "Organisation not found in current public Foundations XLSX"}
    # Find a likely header row among up to 8 rows above the match.
    header = None
    for j in range(max(0, hit_index - 8), hit_index):
        candidate = rows[j]
        joined = norm_text(" ".join(candidate))
        if "DENUM" in joined and ("JUDET" in joined or "LOCALIT" in joined):
            header = candidate
    hit = rows[hit_index]
    if header:
        mapped = {header[k] if k < len(header) and header[k] else f"col_{k+1}": hit[k] if k < len(hit) else "" for k in range(max(len(header), len(hit)))}
    else:
        mapped = {f"col_{k+1}": value for k, value in enumerate(hit)}
    return {
        "available": True,
        "sourceUrl": url,
        "rowIndex": hit_index + 1,
        "publicFields": mapped,
        "governanceAccess": {
            "publicInstant": False,
            "reason": "MJ states that the currently published registry extracts use a reduced data set; additional composition/governing-board information must be requested from the NGO Registry Office.",
            "contact": "ongmj@just.ro",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cui", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args()
    cui = re.sub(r"\D", "", args.cui)
    result = {
        "schemaVersion": "1.0",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "query": {"cui": cui, "name": args.name, "date": args.date},
        "sources": {},
    }
    errors = []
    try:
        result["sources"]["anafGeneral"] = anaf_general(cui, args.date)
    except Exception as exc:
        errors.append({"source": "ANAF_GENERAL_V9", "error": f"{type(exc).__name__}: {exc}"})
    try:
        result["sources"]["ministryJusticeNgo"] = mj_lookup(args.name)
    except Exception as exc:
        errors.append({"source": "MJ_NATIONAL_NGO_REGISTER", "error": f"{type(exc).__name__}: {exc}"})
    result["errors"] = errors
    result["status"] = "OK" if not errors else "PARTIAL"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["sources"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
