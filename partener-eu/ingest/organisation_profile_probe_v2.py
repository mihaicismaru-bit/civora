#!/usr/bin/env python3
"""PARTENER.EU official organisation profile probe by CUI/name.

Sources:
- ANAF public taxpayer-info API v9 for identity, registration state and addresses.
- data.gov.ro / Ministry of Justice National NGO Register for machine-readable
  public NGO registry fields.

Governance-person fields are never inferred. The Ministry of Justice currently
publishes reduced public NGO extracts and directs requests for composition / the
governing board to its NGO Registry Office.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import ssl
import unicodedata
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

ANAF_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
DATA_GOV_PACKAGE = "https://data.gov.ro/api/3/action/package_show?id=registrul-national-ong-2026"
UA = "PARTENER.EU-CIVORA-Organisation-Profile/2.0 (+https://partener.eu)"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).strip().upper()
    return re.sub(r"\s+", " ", value)


def fetch(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 35) -> bytes:
    h = {"User-Agent": UA, "Accept-Language": "ro,en;q=0.7"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read(35_000_000)


def anaf_general(cui: str, query_date: str) -> dict:
    body = json.dumps([{"cui": int(cui), "data": query_date}]).encode("utf-8")
    raw = fetch(ANAF_URL, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
    payload = json.loads(raw.decode("utf-8"))
    found = payload.get("found") or []
    if not found:
        return {"available": False, "message": payload.get("message"), "notFound": payload.get("notFound")}
    item = found[0]
    dg = item.get("date_generale") or {}
    social = item.get("adresa_sediu_social") or {}
    fiscal = item.get("adresa_domiciliu_fiscal") or {}
    return {
        "available": True,
        "sourceUrl": ANAF_URL,
        "entity": {
            "cui": str(dg.get("cui") or cui),
            "name": dg.get("denumire"),
            "registrationNumber": dg.get("nrRegCom"),
            "registrationState": dg.get("stare_inregistrare"),
            "registrationDate": dg.get("data_inregistrare"),
            "caen": dg.get("cod_CAEN"),
            "legalForm": dg.get("forma_juridica"),
            "organisationForm": dg.get("forma_organizare"),
            "ownershipForm": dg.get("forma_de_proprietate"),
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


def col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "A1").group(0)
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value


def read_xlsx_rows(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        first = wb.find("m:sheets/m:sheet", ns)
        rel_id = first.attrib[f"{{{rns}}}id"]
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(rel.attrib["Target"] for rel in rels if rel.attrib.get("Id") == rel_id)
        sheet_path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            vals: list[str] = []
            last = 0
            for c in row.findall("m:c", ns):
                ci = col_index(c.attrib.get("r", "A1"))
                while last + 1 < ci:
                    vals.append("")
                    last += 1
                typ = c.attrib.get("t")
                v = c.find("m:v", ns)
                value = "" if v is None else (v.text or "")
                if typ == "s" and value:
                    value = shared[int(value)]
                elif typ == "inlineStr":
                    value = "".join(t.text or "" for t in c.findall(".//m:t", ns))
                vals.append(value)
                last = ci
            rows.append(vals)
        return rows


def latest_foundations_resource() -> dict:
    payload = json.loads(fetch(DATA_GOV_PACKAGE, timeout=25).decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError("data.gov.ro package_show returned success=false")
    resources = payload["result"].get("resources") or []
    candidates = []
    for r in resources:
        name = norm(r.get("name") or "")
        url = r.get("url") or ""
        fmt = (r.get("format") or "").lower()
        if "FUNDATII" in name and (fmt in {"xlsx", ".xlsx"} or url.lower().split("?")[0].endswith(".xlsx")):
            candidates.append(r)
    if not candidates:
        raise RuntimeError("No Foundations XLSX resource found in 2026 NGO dataset")
    # CKAN resources are appended chronologically; use timestamp when present, then position.
    candidates.sort(key=lambda r: (r.get("last_modified") or r.get("created") or "", int(r.get("position") or 0)))
    return candidates[-1]


def mj_lookup(name: str) -> dict:
    resource = latest_foundations_resource()
    url = resource["url"]
    raw = fetch(url, timeout=35)
    if raw[:2] != b"PK":
        raise RuntimeError("Selected Ministry of Justice resource is not XLSX")
    rows = read_xlsx_rows(raw)
    wanted = norm(name)
    hit_i = None
    for i, row in enumerate(rows):
        if any(wanted == norm(cell) or wanted in norm(cell) for cell in row if cell):
            hit_i = i
            break
    if hit_i is None:
        return {"available": False, "sourceUrl": url, "error": "Organisation not found in Foundations XLSX"}
    header = None
    for j in range(max(0, hit_i - 12), hit_i):
        joined = norm(" ".join(rows[j]))
        if "DENUM" in joined and ("JUDET" in joined or "LOCALIT" in joined or "ADRESA" in joined):
            header = rows[j]
    hit = rows[hit_i]
    if header:
        width = max(len(header), len(hit))
        mapped = {
            (header[k] if k < len(header) and header[k] else f"col_{k+1}"): (hit[k] if k < len(hit) else "")
            for k in range(width)
        }
    else:
        mapped = {f"col_{k+1}": value for k, value in enumerate(hit)}
    return {
        "available": True,
        "dataset": "Registrul National ONG 2026",
        "publisher": "Ministerul Justitiei",
        "resourceName": resource.get("name"),
        "resourceModified": resource.get("last_modified") or resource.get("created"),
        "sourceUrl": url,
        "rowIndex": hit_i + 1,
        "publicFields": mapped,
        "governanceAccess": {
            "publicInstant": False,
            "reason": "Current Ministry of Justice public NGO extracts use a reduced data set; composition and governing-board details require an information request.",
            "contact": "ongmj@just.ro",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cui", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--date", default=dt.date.today().isoformat())
    args = p.parse_args()
    cui = re.sub(r"\D", "", args.cui)
    result = {
        "schemaVersion": "2.0",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "query": {"cui": cui, "name": args.name, "date": args.date},
        "sources": {},
        "errors": [],
    }
    for source, fn in (
        ("anafGeneral", lambda: anaf_general(cui, args.date)),
        ("ministryJusticeNgo", lambda: mj_lookup(args.name)),
    ):
        try:
            result["sources"][source] = fn()
        except Exception as exc:
            result["errors"].append({"source": source, "error": f"{type(exc).__name__}: {exc}"})
    result["status"] = "OK" if not result["errors"] else ("PARTIAL" if result["sources"] else "ERROR")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["sources"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
