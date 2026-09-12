#!/usr/bin/env python3
"""Official Romania EEA/Norway Grants 2021-2028 programme/source watch.

Acquisition-only and non-authorizing. Programme/operator facts, MoUs, NFP
presence and call links are market/programming intelligence only. OPEN/CLOSED,
deadline, budget and eligibility require a later call-specific exact lane.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1"
PARSER_VERSION = "EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA_NORWAY_ROMANIA_2021_2028"
AUTHORITY_CLASS = "EEA_NORWAY_FMO_OFFICIAL"
OBSERVATION_STATE = "PROGRAMME_AND_CALL_DISCOVERY_NON_AUTHORIZING"

ROMANIA_COOPERATION_URL = "https://eeagrants.org/en/fmo/news/renewed-cooperation-romania"
EEA_MOU_URL = "https://eeagrants.org/en/fmo/documents-library/mou-romania-2021-2028-eea-1"
NORWAY_MOU_URL = "https://eeagrants.org/en/fmo/documents-library/mou-romania-2021-2028-norway"
NFP_DIRECTORY_URL = "https://eeagrants.org/en/fmo/national-focal-points"
CIVIL_SOCIETY_CALLS_URL = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
CALL_PREFIX = CIVIL_SOCIETY_CALLS_URL + "/call-"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)
EXPECTED_PROGRAMMES = (
    ("Green Transition", "Ministry of Environment, Water and Forestry"),
    ("Clean Energy Transition", "The Financial Mechanism Office"),
    ("Local Development", "Romanian Social Development Fund"),
    ("Research and Innovation", "Executive Agency for Higher Education, Research, Development and Innovation Funding"),
    ("Green Business and Innovation", "The Financial Mechanism Office"),
    ("Culture", "Ministry of Culture"),
    ("Justice", "Ministry of Justice"),
    ("Home Affairs", "Ministry of Internal Affairs"),
    ("Institutional Cooperation and Capacity Building", "Ministry of Investments and European Projects"),
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
    return re.sub(r"\s+", " ", html.unescape(value).casefold()).strip()


class Probe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[dict[str, str]] = []
        self.href: str | None = None
        self.anchor: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self.suppressed += 1
        elif low == "a" and not self.suppressed:
            self.href = dict(attrs).get("href")
            self.anchor = []

    def handle_endtag(self, tag: str) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)
        elif low == "a" and not self.suppressed:
            if self.href:
                self.links.append({"text": " ".join(self.anchor).strip(), "href": self.href})
            self.href = None
            self.anchor = []

    def handle_data(self, data: str) -> None:
        if self.suppressed:
            return
        value = " ".join(data.split())
        if value:
            self.text.append(value)
            if self.href is not None:
                self.anchor.append(value)


def parse_html(raw: bytes, base_url: str) -> dict[str, Any]:
    p = Probe()
    p.feed(raw.decode("utf-8", errors="replace"))
    return {
        "text": re.sub(r"\s+", " ", html.unescape(" ".join(p.text))).strip(),
        "links": [
            {"text": " ".join(x["text"].split()), "url": urllib.parse.urljoin(base_url, x["href"])}
            for x in p.links if x.get("href")
        ],
    }


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"official EEA/Norway response exceeds 5 MB: {url}")
        meta = {
            "requested_url": url, "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"official EEA/Norway source returned HTTP {meta['status']}: {url}")
    return raw, meta


def require(text: str, *anchors: str, source: str) -> None:
    hay = normal(text)
    missing = [a for a in anchors if normal(a) not in hay]
    if missing:
        raise ValueError(f"{source} missing required official semantic anchors: {missing}")


def extract_call_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in links:
        url, label = str(item.get("url") or ""), str(item.get("text") or "").strip()
        if url.startswith(CALL_PREFIX) and re.match(r"(?i)^call\s*#?\s*\d+\b", label):
            out[url] = {"label": label, "url": url}
    return [out[k] for k in sorted(out)]


def build_receipt(*, sources_raw: Mapping[str, bytes], sources_meta: Mapping[str, Mapping[str, Any]], fetched_at: str, run_id: str) -> dict[str, Any]:
    urls = {
        "romania-cooperation": ROMANIA_COOPERATION_URL,
        "eea-mou": EEA_MOU_URL,
        "norway-mou": NORWAY_MOU_URL,
        "nfp-directory": NFP_DIRECTORY_URL,
        "civil-society-calls": CIVIL_SOCIETY_CALLS_URL,
    }
    if set(sources_raw) != set(urls) or set(sources_meta) != set(urls):
        raise ValueError("EEA/Norway watch requires the exact bounded official source set")
    parsed = {k: parse_html(sources_raw[k], u) for k, u in urls.items()}
    require(parsed["romania-cooperation"]["text"], "EEA and Norway Grants 2021–2028", "nine programmes in Romania", "Programmes 2021-2028", "EEA Civil Society Fund Romania", source="Romania cooperation page")
    require(parsed["eea-mou"]["text"], "MoU Romania 2021-2028 EEA", "2021-2028", source="Romania EEA MoU page")
    require(parsed["norway-mou"]["text"], "MoU Romania 2021-2028 Norway", "2021-2028", source="Romania Norway MoU page")
    require(parsed["nfp-directory"]["text"], "National Focal Points", "main contact institutions for the EEA and Norway Grants", "2021–2028 funding period", source="FMO NFP directory")
    require(parsed["civil-society-calls"]["text"], "Calls", "Call for projects", source="Romania Civil Society calls index")

    coop = normal(parsed["romania-cooperation"]["text"])
    programmes = []
    for name, operator in EXPECTED_PROGRAMMES:
        if normal(name) not in coop or normal(operator) not in coop:
            raise ValueError(f"Romania cooperation page lost programme/operator anchor: {name} / {operator}")
        programmes.append({
            "programme": name, "operator": operator, "authority_url": ROMANIA_COOPERATION_URL,
            "observation_state": "PROGRAMMING", "market_intelligence_only": True,
            "call_fact_authorized": False, "eligibility_fact_authorized": False,
        })

    nfp_state = (
        "ROMANIA_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY_NON_AUTHORIZING"
        if "romania" in normal(parsed["nfp-directory"]["text"])
        else "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY"
    )
    call_links = extract_call_links(parsed["civil-society-calls"]["links"])
    if not call_links:
        raise ValueError("Romania Civil Society official calls index exposed no numbered call-specific links")
    calls = [{
        **x, "observation_state": "CALL_DISCOVERY_ONLY",
        "authority_class": "EEA_NORWAY_FMO_OFFICIAL_CALL_SURFACE", "observed_at": fetched_at,
        "open_call_authorized": False, "deadline_authorized": False,
        "budget_authorized": False, "eligibility_authorized": False,
    } for x in call_links]

    fit_facts = {
        "fit_state": "ROMANIA_BENEFICIARY_STATE_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING",
        "funding_period": "2021-2028", "mou_state": "SIGNED",
        "programme_count": len(programmes), "programme_names": [x["programme"] for x in programmes],
        "nfp_directory_state": nfp_state, "civil_society_call_surface_present": True,
    }
    fit = {
        "observation_state": "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING", "authority_class": AUTHORITY_CLASS,
        "authority_url": ROMANIA_COOPERATION_URL, "facts": fit_facts,
        "semantic_fingerprint": sha256_json(fit_facts),
        "eligibility_fact_authorized": False, "call_fact_authorized": False,
    }
    programming = [{
        "title": title, "observation_state": "PROGRAMMING", "source_url": url,
        "authority_class": AUTHORITY_CLASS, "observed_at": fetched_at,
        "open_call_authorized": False, "material_fact_use": False,
    } for title, url in (
        ("Romania EEA Grants 2021-2028 Memorandum of Understanding", EEA_MOU_URL),
        ("Romania Norway Grants 2021-2028 Memorandum of Understanding", NORWAY_MOU_URL),
    )]
    sources = [{
        **dict(sources_meta[k]), "source_key": k, "authority_url": u,
        "sha256": sha256_bytes(sources_raw[k]),
    } for k, u in urls.items()]
    nfp = {"state": nfp_state, "source_url": NFP_DIRECTORY_URL, "observed_at": fetched_at, "material_fact_use": False}

    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION, "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY, "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE, "fetched_at": fetched_at, "run_id": run_id,
        "source_health": "HEALTHY", "market_intelligence_only": True,
        "sources": sources, "programme_fit_evidence": fit, "programmes": programmes,
        "programming_observations": programming, "national_focal_point_observation": nfp,
        "call_discovery": calls,
        "missing_for_open_call_confirmation": [
            "selected exact call identifier", "fresh call-specific official endpoint readback",
            "semantic reconciliation against same-identity previous evidence", "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    receipt["semantic_fingerprint"] = sha256_json({
        "programme_fit_evidence": fit, "programmes": programmes, "programming_observations": programming,
        "national_focal_point_observation": nfp, "call_discovery": calls,
        "source_hashes": [x["sha256"] for x in sources],
    })
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("EEA/Norway Romania programme watch schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA/Norway Romania family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS or receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("EEA/Norway Romania authority/observation drift")
    if receipt.get("source_health") != "HEALTHY" or receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("EEA/Norway Romania watch crossed non-authorizing boundary")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EEA/Norway Romania watch attempted authorization: {key}")

    sources = receipt.get("sources")
    if not isinstance(sources, list) or len(sources) != 5:
        raise ValueError("EEA/Norway Romania watch requires five official source receipts")
    for x in sources:
        if not isinstance(x, Mapping) or not str(x.get("final_url") or x.get("requested_url") or "").startswith("https://eeagrants.org/"):
            raise ValueError("EEA/Norway source left official FMO authority")
        if int(x.get("status") or 0) != 200 or not re.fullmatch(r"[0-9a-f]{64}", str(x.get("sha256") or "")):
            raise ValueError("EEA/Norway source receipt lacks healthy hash-bound evidence")

    fit = receipt.get("programme_fit_evidence")
    if not isinstance(fit, Mapping) or fit.get("observation_state") != "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING":
        raise ValueError("EEA/Norway programme fit evidence missing")
    if fit.get("eligibility_fact_authorized") is not False or fit.get("call_fact_authorized") is not False:
        raise ValueError("EEA/Norway programme fit attempted call/eligibility authorization")
    if fit.get("semantic_fingerprint") != sha256_json(fit.get("facts") or {}):
        raise ValueError("EEA/Norway programme fit semantic fingerprint mismatch")

    programmes = receipt.get("programmes")
    if not isinstance(programmes, list) or len(programmes) != 9 or {x.get("programme") for x in programmes} != {x[0] for x in EXPECTED_PROGRAMMES}:
        raise ValueError("EEA/Norway Romania programme registry drift")
    if any(x.get("observation_state") != "PROGRAMMING" or x.get("call_fact_authorized") is not False or x.get("eligibility_fact_authorized") is not False for x in programmes):
        raise ValueError("EEA/Norway programme registry attempted material authorization")

    programming = receipt.get("programming_observations")
    if not isinstance(programming, list) or len(programming) != 2 or any(x.get("observation_state") != "PROGRAMMING" or x.get("open_call_authorized") is not False or x.get("material_fact_use") is not False for x in programming):
        raise ValueError("EEA/Norway MoU observation escaped PROGRAMMING")

    nfp = receipt.get("national_focal_point_observation")
    if not isinstance(nfp, Mapping) or nfp.get("material_fact_use") is not False or nfp.get("state") not in {
        "ROMANIA_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY_NON_AUTHORIZING",
        "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY",
    }:
        raise ValueError("EEA/Norway NFP observation crossed non-authorizing boundary")

    calls = receipt.get("call_discovery")
    if not isinstance(calls, list) or not calls:
        raise ValueError("EEA/Norway Romania call discovery missing")
    seen: set[str] = set()
    for x in calls:
        url, label = str(x.get("url") or ""), str(x.get("label") or "")
        if not url.startswith(CALL_PREFIX) or not re.match(r"(?i)^call\s*#?\s*\d+\b", label):
            raise ValueError("EEA/Norway call discovery includes non-call page")
        if url in seen:
            raise ValueError("EEA/Norway call discovery duplicate URL")
        seen.add(url)
        if x.get("observation_state") != "CALL_DISCOVERY_ONLY":
            raise ValueError("EEA/Norway call discovery attempted material state")
        for key in ("open_call_authorized", "deadline_authorized", "budget_authorized", "eligibility_authorized"):
            if x.get(key) is not False:
                raise ValueError(f"EEA/Norway call discovery attempted authorization: {key}")

    expected = sha256_json({
        "programme_fit_evidence": fit, "programmes": programmes, "programming_observations": programming,
        "national_focal_point_observation": nfp, "call_discovery": calls,
        "source_hashes": [x["sha256"] for x in sources],
    })
    if receipt.get("semantic_fingerprint") != expected:
        raise ValueError("EEA/Norway Romania programme watch semantic fingerprint mismatch")


def collect(*, run_id: str, fetched_at: str | None = None, fetcher: Callable[[str], tuple[bytes, Mapping[str, Any]]] | None = None) -> tuple[dict[str, Any], dict[str, bytes]]:
    fetched_at, fetcher = fetched_at or utc_now(), fetcher or default_fetch
    urls = {
        "romania-cooperation": ROMANIA_COOPERATION_URL, "eea-mou": EEA_MOU_URL,
        "norway-mou": NORWAY_MOU_URL, "nfp-directory": NFP_DIRECTORY_URL,
        "civil-society-calls": CIVIL_SOCIETY_CALLS_URL,
    }
    raw: dict[str, bytes] = {}
    meta: dict[str, Mapping[str, Any]] = {}
    for k, u in urls.items():
        raw[k], meta[k] = fetcher(u)
    return build_receipt(sources_raw=raw, sources_meta=meta, fetched_at=fetched_at, run_id=run_id), raw


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--out-dir", required=True); p.add_argument("--run-id", required=True); a = p.parse_args()
    out = pathlib.Path(a.out_dir); raw_dir = out / "raw"; raw_dir.mkdir(parents=True, exist_ok=True)
    receipt, raw = collect(run_id=a.run_id)
    (out / "eea-norway-romania-programme-watch.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    names = {"romania-cooperation":"romania-cooperation.html","eea-mou":"romania-eea-mou.html","norway-mou":"romania-norway-mou.html","nfp-directory":"fmo-national-focal-points.html","civil-society-calls":"romania-civil-society-calls.html"}
    for k, body in raw.items(): (raw_dir / names[k]).write_bytes(body)
    print(json.dumps({"schema":receipt["schema"],"source_health":receipt["source_health"],"programme_count":len(receipt["programmes"]),"call_discovery_count":len(receipt["call_discovery"]),"nfp_state":receipt["national_focal_point_observation"]["state"],"semantic_fingerprint":receipt["semantic_fingerprint"],"open_call_authorized":receipt["open_call_authorized"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
