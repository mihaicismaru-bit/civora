#!/usr/bin/env python3
"""Official Interreg programme/territory matrix relevant to Romania.

Acquisition-only and non-authorizing. This verifies programme-level Romanian
territorial fit from official programme authorities or Interact/keep.eu
registry evidence with explicit provenance. It never authorizes a call status,
deadline, budget, applicant eligibility, publication or alert.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_INTERREG_ROMANIA_PROGRAMME_MATRIX_V1"
PARSER_VERSION = "INTERREG_ROMANIA_PROGRAMME_MATRIX_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_ROMANIA_RELEVANT_2021_2027"
AUTHORITY_CLASS = "INTERREG_OFFICIAL_PROGRAMME_EVIDENCE"
OBSERVATION_STATE = "PROGRAMME_GEOGRAPHY_RESEARCH_NON_AUTHORIZING"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)

PROGRAMMES: tuple[dict[str, Any], ...] = (
    {
        "id": "RO_BG", "programme": "Interreg VI-A Romania-Bulgaria", "mode": "CBC_INTERNAL",
        "url": "https://keep.eu/programmes/342/2021-2027-Romania-Bulgaria/",
        "hosts": ("keep.eu", "www.keep.eu"),
        "anchors": ("2021 - 2027 Interreg VI-A Romania-Bulgaria", "Eligible geographical area", "Mehedinti", "Dolj", "Olt", "Teleorman", "Giurgiu", "Calarasi", "Constanta"),
        "romania_scope": ("Mehedinti", "Dolj", "Olt", "Teleorman", "Giurgiu", "Calarasi", "Constanta"),
        "evidence_note": "keep.eu Interact registry; programme-validated fundamental information",
    },
    {
        "id": "RO_HU", "programme": "Interreg VI-A Romania-Hungary", "mode": "CBC_INTERNAL",
        "url": "https://interreg-rohu.eu/en/",
        "hosts": ("interreg-rohu.eu", "www.interreg-rohu.eu"),
        "anchors": ("Interreg VI-A Romania-Hungary", "Arad", "Bihor", "Satu Mare", "Timis"),
        "romania_scope": ("Arad", "Bihor", "Satu Mare", "Timis"),
        "evidence_note": "official programme authority",
    },
    {
        "id": "RO_RS", "programme": "Interreg IPA Romania-Serbia", "mode": "CBC_IPA",
        "url": "https://romania-serbia.net/programme/about-the-programme/",
        "hosts": ("romania-serbia.net", "www.romania-serbia.net"),
        "anchors": ("Interreg IPA Romania-Serbia", "Timis", "Caras-Severin", "Mehedinti", "six districts in Serbia"),
        "romania_scope": ("Timis", "Caras-Severin", "Mehedinti"),
        "evidence_note": "official programme authority",
    },
    {
        "id": "RO_UA", "programme": "Interreg NEXT Romania-Ukraine", "mode": "CBC_NEXT",
        "url": "https://keep.eu/programmes/341/2021-2027-Romania-Ukraine/",
        "hosts": ("keep.eu", "www.keep.eu"),
        "anchors": ("2021 - 2027 Interreg VI-A NEXT Romania - Ukraine", "Eligible geographical area", "Satu Mare", "Maramures", "Suceava", "Botosani", "Tulcea"),
        "romania_scope": ("Satu Mare", "Maramures", "Suceava", "Botosani", "Tulcea"),
        "evidence_note": "keep.eu Interact registry fallback; direct programme host failed verified TLS in runner; geography research only",
    },
    {
        "id": "RO_MD", "programme": "Interreg NEXT Romania-Republic of Moldova", "mode": "CBC_NEXT",
        "url": "https://keep.eu/programmes/339/2021-2027-Romania-Moldova/",
        "hosts": ("keep.eu", "www.keep.eu"),
        "anchors": ("2021 - 2027 Interreg VI-A NEXT Romania - Rep.Moldova", "Eligible geographical area", "Botosani", "Iasi", "Vaslui", "Galati"),
        "romania_scope": ("Botosani", "Iasi", "Vaslui", "Galati"),
        "evidence_note": "keep.eu Interact registry fallback; direct programme host failed verified TLS in runner; geography research only",
    },
    {
        "id": "DANUBE", "programme": "Interreg Danube Region Programme", "mode": "TRANSNATIONAL",
        "url": "https://interreg-danube.eu/how-to-apply",
        "hosts": ("interreg-danube.eu", "www.interreg-danube.eu"),
        "anchors": ("14 countries", "Romania", "Danube region", "eligible to apply"),
        "romania_scope": ("ALL_ROMANIA",),
        "evidence_note": "official programme authority",
    },
    {
        "id": "INTERREG_EUROPE", "programme": "Interreg Europe", "mode": "INTERREGIONAL",
        "url": "https://keep.eu/programmes/394/2021-2027-lnterreg-Europe/",
        "hosts": ("keep.eu", "www.keep.eu"),
        "anchors": ("2021 - 2027 Interreg VI-C Interreg Europe", "Eligible geographical area", "Romania", "Programme validated the information"),
        "romania_scope": ("ALL_ROMANIA",),
        "evidence_note": "keep.eu Interact registry; programme-validated fundamental information; direct programme page timed out in runner",
    },
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def normal(value: str) -> str:
    text = html.unescape(value).casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


class TextProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"official Interreg response exceeds 5 MB: {url}")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"official Interreg source returned HTTP {meta['status']}: {url}")
    return raw, meta


def require(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    hay = normal(text)
    missing = [anchor for anchor in anchors if normal(anchor) not in hay]
    if missing:
        raise ValueError(f"{source} missing required official territorial anchors: {missing}")


def host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    return host in {x.casefold() for x in allowed}


def collect(*, run_id: str, fetched_at: str | None = None, fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    raw_by_id: dict[str, bytes] = {}
    sources: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []

    for spec in PROGRAMMES:
        raw, meta = fetcher(spec["url"])
        final_url = str(meta.get("final_url") or meta.get("requested_url") or "")
        if int(meta.get("status") or 0) != 200 or not host_allowed(final_url, spec["hosts"]):
            raise ValueError(f"{spec['id']} left its official Interreg evidence authority")
        require(html_text(raw), spec["anchors"], source=spec["programme"])
        raw_by_id[spec["id"]] = raw
        source_hash = sha256_bytes(raw)
        sources.append({
            "programme_id": spec["id"], "authority_url": spec["url"], **dict(meta),
            "sha256": source_hash, "authority_class": AUTHORITY_CLASS,
            "evidence_note": spec["evidence_note"],
        })
        matrix.append({
            "programme_id": spec["id"], "programme": spec["programme"], "cooperation_mode": spec["mode"],
            "authority_url": spec["url"], "authority_class": AUTHORITY_CLASS,
            "evidence_note": spec["evidence_note"],
            "programme_period": "2021-2027", "romania_scope": list(spec["romania_scope"]),
            "territorial_fit_state": "ROMANIA_PROGRAMME_TERRITORY_VERIFIED_NON_AUTHORIZING",
            "observation_state": OBSERVATION_STATE, "observed_at": observed,
            "market_intelligence_only": True, "call_fact_authorized": False,
            "applicant_eligibility_authorized": False, "source_sha256": source_hash,
        })

    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION, "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY, "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE, "fetched_at": observed, "run_id": run_id,
        "source_health": "HEALTHY", "market_intelligence_only": True,
        "programme_count": len(matrix), "sources": sources, "programmes": matrix,
        "missing_for_open_call_confirmation": [
            "selected exact programme call identifier", "fresh current official call endpoint readback",
            "same-identity semantic reconciliation", "call-specific applicant/territory eligibility evidence",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    receipt["semantic_fingerprint"] = sha256_json({
        "programmes": matrix,
        "source_hashes": sorted((x["programme_id"], x["sha256"]) for x in sources),
    })
    validate_receipt(receipt)
    return receipt, raw_by_id


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("Interreg Romania matrix schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Interreg Romania matrix family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS or receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("Interreg Romania authority/observation drift")
    if receipt.get("source_health") != "HEALTHY" or receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("Interreg Romania matrix crossed non-authorizing boundary")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"Interreg Romania matrix attempted authorization: {flag}")

    sources = receipt.get("sources")
    rows = receipt.get("programmes")
    if not isinstance(sources, list) or not isinstance(rows, list) or len(sources) != 7 or len(rows) != 7:
        raise ValueError("Interreg Romania matrix requires exactly seven verified programme sources")
    expected = {x["id"] for x in PROGRAMMES}
    if {x.get("programme_id") for x in rows} != expected or {x.get("programme_id") for x in sources} != expected:
        raise ValueError("Interreg Romania programme set drift")

    specs = {x["id"]: x for x in PROGRAMMES}
    for source in sources:
        pid = str(source.get("programme_id") or "")
        if int(source.get("status") or 0) != 200 or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256") or "")):
            raise ValueError(f"Interreg source {pid} lacks healthy hash-bound evidence")
        if not host_allowed(str(source.get("final_url") or source.get("requested_url") or ""), specs[pid]["hosts"]):
            raise ValueError(f"Interreg source {pid} escaped official evidence authority")
        if source.get("evidence_note") != specs[pid]["evidence_note"]:
            raise ValueError(f"Interreg source {pid} evidence provenance drift")

    for row in rows:
        pid = str(row.get("programme_id") or "")
        if row.get("observation_state") != OBSERVATION_STATE or row.get("territorial_fit_state") != "ROMANIA_PROGRAMME_TERRITORY_VERIFIED_NON_AUTHORIZING":
            raise ValueError(f"Interreg programme {pid} escaped programme-level geography research")
        if row.get("market_intelligence_only") is not True or row.get("call_fact_authorized") is not False or row.get("applicant_eligibility_authorized") is not False:
            raise ValueError(f"Interreg programme {pid} attempted call/applicant eligibility authorization")
        if row.get("authority_url") != specs[pid]["url"] or list(row.get("romania_scope") or []) != list(specs[pid]["romania_scope"]):
            raise ValueError(f"Interreg programme {pid} territory/authority drift")
        if row.get("evidence_note") != specs[pid]["evidence_note"]:
            raise ValueError(f"Interreg programme {pid} evidence provenance drift")
        source = next(x for x in sources if x.get("programme_id") == pid)
        if row.get("source_sha256") != source.get("sha256"):
            raise ValueError(f"Interreg programme {pid} source hash binding drift")

    expected_fp = sha256_json({
        "programmes": rows,
        "source_hashes": sorted((x["programme_id"], x["sha256"]) for x in sources),
    })
    if receipt.get("semantic_fingerprint") != expected_fp:
        raise ValueError("Interreg Romania semantic fingerprint mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    receipt, raw = collect(run_id=args.run_id)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    for pid, body in raw.items():
        (raw_dir / f"{pid.lower()}.html").write_bytes(body)
    target = out / "interreg-romania-programme-matrix.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_count": receipt["programme_count"],
        "source_health": receipt["source_health"],
        "semantic_fingerprint": receipt["semantic_fingerprint"],
        "output": str(target),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())