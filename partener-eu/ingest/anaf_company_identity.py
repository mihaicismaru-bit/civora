#!/usr/bin/env python3
"""Stable public ANAF identity/fiscal/address lookup by Romanian CUI."""
from __future__ import annotations

import datetime as dt
import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

ANAF_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
UA = "PARTENER.EU-CIVORA-ANAF-Identity/1.0 (+https://partener.eu)"
MAX_RESPONSE_BYTES = 4_000_000


def _post_json(body: bytes, timeout: float = 20.0, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            ANAF_URL,
            data=body,
            headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("ANAF identity response exceeds safety limit")
                payload = json.loads(raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
                if not isinstance(payload, dict):
                    raise ValueError("ANAF identity response root is not an object")
                return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
        time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(f"ANAF identity lookup failed: {type(last_error).__name__}: {last_error}")


def fetch_identity(cui: str, query_date: str | None = None) -> dict[str, Any]:
    date = query_date or dt.date.today().isoformat()
    body = json.dumps([{"cui": int(cui), "data": date}]).encode("utf-8")
    payload = _post_json(body)
    found = payload.get("found") or []
    if not found:
        return {
            "available": False,
            "sourceUrl": ANAF_URL,
            "message": payload.get("message"),
            "notFound": payload.get("notFound"),
        }
    item = found[0]
    general = item.get("date_generale") or {}
    social = item.get("adresa_sediu_social") or {}
    fiscal = item.get("adresa_domiciliu_fiscal") or {}
    return {
        "available": True,
        "sourceUrl": ANAF_URL,
        "entity": {
            "cui": str(general.get("cui") or cui),
            "name": general.get("denumire"),
            "registrationNumber": general.get("nrRegCom"),
            "registrationState": general.get("stare_inregistrare"),
            "registrationDate": general.get("data_inregistrare"),
            "caen": general.get("cod_CAEN"),
            "legalForm": general.get("forma_juridica"),
            "organisationForm": general.get("forma_organizare"),
            "ownershipForm": general.get("forma_de_proprietate"),
            "taxAuthority": general.get("organFiscalCompetent"),
            "eFactura": general.get("statusRO_e_Factura"),
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
        "vatOnReceipt": item.get("inregistrare_RTVAI") or {},
        "inactive": item.get("stare_inactiv") or {},
        "splitVat": item.get("inregistrare_SplitTVA") or {},
    }
