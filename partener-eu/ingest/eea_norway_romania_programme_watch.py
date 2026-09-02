#!/usr/bin/env python3
"""Official Romania EEA/Norway Grants 2021-2028 programme/source watch.

This adapter is acquisition-only and deliberately non-authorizing. It binds the
current Financial Mechanism Office (FMO) Romania cooperation announcement, the
EEA and Norway Memoranda of Understanding landing pages, the FMO National Focal
Point directory, and the official EEA Civil Society Fund Romania calls index.

Programme/operator facts and call links are market/programming intelligence.
They cannot authorize OPEN/CLOSED status, deadlines, budgets, eligibility,
publication, distribution, or alerts. A call becomes material only in a later
call-specific lane that has an exact call identifier, current official call
endpoint, semantic reconciliation, and field-scoped admission.
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

EXPECTED_PROGRAMMES: tuple[tuple[str, str], ...] = (
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

REQUIRED_COOPERATION_ANCHORS = (
    "EEA and Norway Grants 2021–2028",
    "nine programmes in Romania",
    "Programmes 2021-2028",
    "EEA Civil Society Fund Romania",
)
REQUIRED_EEA_MOU_ANCHORS = ("MoU Romania 2021-2028 EEA", "2021-2028")
REQUIRED_NORWAY_MOU_ANCHORS = ("MoU Romania 2021-2028 Norway", "2021-2028")
REQUIRED_NFP_DIRECTORY_ANCHORS = (
    "National Focal Points",
    "main contact institutions for the EEA and Norway Grants",
    "2021–2028 funding period",
)
REQUIRED_CALL_INDEX_ANCHORS = ("Calls", "Call for projects")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def normal(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value).casefold()).strip()


class _HTMLProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._label_hint: str | None = None
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self._suppressed += 1
            return
        if low == "a" and not self._suppressed:
            attr_map = dict(attrs)
            self._href = attr_map.get("href")
            self._label_hint = (
                attr_map.get("data-untranslated-label")
                or attr_map.get("aria-label")
                or attr_map.get("title")
            )
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self._suppressed = max(0, self._suppressed - 1)
            return
        if low == "a" and not self._suppressed:
            label = (self._label_hint or " ".join(self._anchor_parts)).strip()
            if self._href:
                self.links.append({"text": label, "href": self._href})
            self._href = None
            self._label_hint = None
            self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._href is not None:
            self._anchor_parts.append(cleaned)


def parse_html(raw: bytes, *, base_url: str) -> dict[str, Any]:
    parser = _HTMLProbe()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return {
        "text": re.sub(r"\s+", " ", html.unescape(" ".join(parser.text_parts))).strip(),
        "links": [
            {
                "text": re.sub(r"\s+", " ", item.get("text") or "").strip(),
                "url": urllib.parse.urljoin(base_url, item.get("href") or ""),
            }
            for item in parser.links
            if item.get("href")
        ],
    }


def default_fetch(url: str, *, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"official EEA/Norway response exceeds bounded 5 MB limit: {url}")
        status = int(getattr(response, "status", 200) or 200)
        final_url = str(response.geturl())
        content_type = str(response.headers.get("Content-Type") or "")
    if status != 200:
        raise ValueError(f"official EEA/Norway source returned HTTP {status}: {url}")
    return raw, {
        "requested_url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
    }


def require_anchors(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    haystack = normal(text)
    missing = [anchor for anchor in anchors if normal(anchor) not in haystack]
    if missing:
        raise ValueError(f"{source} missing required official semantic anchors: {missing}")


def extract_call_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    prefix = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/"
    for item in links:
        url = str(item.get("url") or "")
        if not url.startswith(prefix) or url.rstrip("/") == CIVIL_SOCIETY_CALLS_URL.rstrip("/"):
            continue
        result[url] = {"label": str(item.get("text") or "").strip(), "url": url}
    return [result[key] for key in sorted(result)]


def build_receipt(
    *,
    sources_raw: Mapping[str, bytes],
    sources_meta: Mapping[str, Mapping[str, Any]],
    fetched_at: str,
    run_id: str,
) -> dict[str, Any]:
    required = {
        "romania-cooperation": ROMANIA_COOPERATION_URL,
        "eea-mou": EEA_MOU_URL,
        "norway-mou": NORWAY_MOU_URL,
        "nfp-directory": NFP_DIRECTORY_URL,
        "civil-society-calls": CIVIL_SOCIETY_CALLS_URL,
    }
    if set(sources_raw) != set(required) or set(sources_meta) != set(required):
        raise ValueError("EEA/Norway watch requires the exact bounded official source set")

    parsed = {
        key: parse_html(sources_raw[key], base_url=url)
        for key, url in required.items()
    }
    require_anchors(parsed["romania-cooperation"]["text"], REQUIRED_COOPERATION_ANCHORS, source="Romania cooperation page")
    require_anchors(parsed["eea-mou"]["text"], REQUIRED_EEA_MOU_ANCHORS, source="Romania EEA MoU page")
    require_anchors(parsed["norway-mou"]["text"], REQUIRED_NORWAY_MOU_ANCHORS, source="Romania Norway MoU page")
    require_anchors(parsed["nfp-directory"]["text"], REQUIRED_NFP_DIRECTORY_ANCHORS, source="FMO NFP directory")
    require_anchors(parsed["civil-society-calls"]["text"], REQUIRED_CALL_INDEX_ANCHORS, source="Romania Civil Society calls index")

    cooperation_text = normal(parsed["romania-cooperation"]["text"])
    programmes: list[dict[str, Any]] = []
    for name, operator in EXPECTED_PROGRAMMES:
        if normal(name) not in cooperation_text or normal(operator) not in cooperation_text:
            raise ValueError(f"Romania cooperation page lost programme/operator anchor: {name} / {operator}")
        programmes.append(
            {
                "programme": name,
                "operator": operator,
                "authority_url": ROMANIA_COOPERATION_URL,
                "observation_state": "PROGRAMMING",
                "market_intelligence_only": True,
                "call_fact_authorized": False,
                "eligibility_fact_authorized": False,
            }
        )

    nfp_text = normal(parsed["nfp-directory"]["text"])
    if "romania" in nfp_text:
        nfp_state = "ROMANIA_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY_NON_AUTHORIZING"
    else:
        nfp_state = "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY"

    call_links = extract_call_links(parsed["civil-society-calls"]["links"])
    if not call_links:
        raise ValueError("Romania Civil Society official calls index exposed no call-specific links")
    call_discovery = [
        {
            **item,
            "observation_state": "CALL_DISCOVERY_ONLY",
            "authority_class": "EEA_NORWAY_FMO_OFFICIAL_CALL_SURFACE",
            "observed_at": fetched_at,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
        }
        for item in call_links
    ]

    programme_fit_facts = {
        "fit_state": "ROMANIA_BENEFICIARY_STATE_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING",
        "funding_period": "2021-2028",
        "mou_state": "SIGNED",
        "programme_count": len(programmes),
        "programme_names": [row["programme"] for row in programmes],
        "nfp_directory_state": nfp_state,
        "civil_society_call_surface_present": True,
    }
    programme_fit = {
        "observation_state": "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING",
        "authority_class": AUTHORITY_CLASS,
        "authority_url": ROMANIA_COOPERATION_URL,
        "facts": programme_fit_facts,
        "semantic_fingerprint": sha256_json(programme_fit_facts),
        "eligibility_fact_authorized": False,
        "call_fact_authorized": False,
    }

    programming_observations = [
        {
            "title": "Romania EEA Grants 2021-2028 Memorandum of Understanding",
            "observation_state": "PROGRAMMING",
            "source_url": EEA_MOU_URL,
            "authority_class": AUTHORITY_CLASS,
            "observed_at": fetched_at,
            "open_call_authorized": False,
            "material_fact_use": False,
        },
        {
            "title": "Romania Norway Grants 2021-2028 Memorandum of Understanding",
            "observation_state": "PROGRAMMING",
            "source_url": NORWAY_MOU_URL,
            "authority_class": AUTHORITY_CLASS,
            "observed_at": fetched_at,
            "open_call_authorized": False,
            "material_fact_use": False,
        },
    ]

    source_receipts = []
    for key, url in required.items():
        meta = dict(sources_meta[key])
        source_receipts.append(
            {
                **meta,
                "source_key": key,
                "authority_url": url,
                "sha256": sha256_bytes(sources_raw[key]),
            }
        )

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "source_health": "HEALTHY",
        "market_intelligence_only": True,
        "sources": source_receipts,
        "programme_fit_evidence": programme_fit,
        "programmes": programmes,
        "programming_observations": programming_observations,
        "national_focal_point_observation": {
            "state": nfp_state,
            "source_url": NFP_DIRECTORY_URL,
            "observed_at": fetched_at,
            "material_fact_use": False,
        },
        "call_discovery": call_discovery,
        "missing_for_open_call_confirmation": [
            "selected exact call identifier",
            "fresh call-specific official endpoint readback",
            "semantic reconciliation against same-identity previous evidence",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False

    receipt["semantic_fingerprint"] = sha256_json(
        {
            "programme_fit_evidence": programme_fit,
            "programmes": programmes,
            "programming_observations": programming_observations,
            "national_focal_point_observation": receipt["national_focal_point_observation"],
            "call_discovery": call_discovery,
            "source_hashes": [row["sha256"] for row in source_receipts],
        }
    )
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("EEA/Norway Romania programme watch schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA/Norway Romania family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("EEA/Norway Romania authority drift")
    if receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("EEA/Norway Romania observation state drift")
    if receipt.get("source_health") != "HEALTHY" or receipt.get("market_intelligence_only") is not True:
        raise ValueError("EEA/Norway Romania watch is not healthy market intelligence")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("EEA/Norway Romania watch attempted publication effect")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EEA/Norway Romania watch attempted authorization: {key}")

    sources = receipt.get("sources")
    if not isinstance(sources, list) or len(sources) != 5:
        raise ValueError("EEA/Norway Romania watch requires five official source receipts")
    source_keys = {str(row.get("source_key") or "") for row in sources if isinstance(row, Mapping)}
    if source_keys != {"romania-cooperation", "eea-mou", "norway-mou", "nfp-directory", "civil-society-calls"}:
        raise ValueError("EEA/Norway Romania source-set drift")
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("EEA/Norway Romania source receipt malformed")
        final_url = str(source.get("final_url") or source.get("requested_url") or "")
        if not final_url.startswith("https://eeagrants.org/"):
            raise ValueError(f"EEA/Norway source left official FMO authority: {final_url}")
        if int(source.get("status") or 0) != 200:
            raise ValueError("EEA/Norway source receipt is not HTTP 200")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256") or "")):
            raise ValueError("EEA/Norway source receipt lacks sha256")

    fit = receipt.get("programme_fit_evidence")
    if not isinstance(fit, Mapping):
        raise ValueError("EEA/Norway programme fit evidence missing")
    if fit.get("observation_state") != "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING":
        raise ValueError("EEA/Norway programme fit state drift")
    if fit.get("eligibility_fact_authorized") is not False or fit.get("call_fact_authorized") is not False:
        raise ValueError("EEA/Norway programme fit attempted call/eligibility authorization")
    if fit.get("semantic_fingerprint") != sha256_json(fit.get("facts") or {}):
        raise ValueError("EEA/Norway programme fit semantic fingerprint mismatch")

    programmes = receipt.get("programmes")
    if not isinstance(programmes, list) or len(programmes) != 9:
        raise ValueError("EEA/Norway Romania programme registry must contain nine programmes")
    if {str(row.get("programme") or "") for row in programmes if isinstance(row, Mapping)} != {name for name, _ in EXPECTED_PROGRAMMES}:
        raise ValueError("EEA/Norway Romania programme registry drift")
    for row in programmes:
        if not isinstance(row, Mapping) or row.get("observation_state") != "PROGRAMMING":
            raise ValueError("EEA/Norway programme registry crossed programming boundary")
        if row.get("call_fact_authorized") is not False or row.get("eligibility_fact_authorized") is not False:
            raise ValueError("EEA/Norway programme registry attempted material authorization")

    programming = receipt.get("programming_observations")
    if not isinstance(programming, list) or len(programming) != 2:
        raise ValueError("EEA/Norway Romania MoU programming observations missing")
    for row in programming:
        if not isinstance(row, Mapping) or row.get("observation_state") != "PROGRAMMING":
            raise ValueError("EEA/Norway MoU observation escaped PROGRAMMING")
        if row.get("open_call_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError("EEA/Norway MoU observation attempted OPEN/material authorization")

    nfp = receipt.get("national_focal_point_observation")
    if not isinstance(nfp, Mapping) or nfp.get("material_fact_use") is not False:
        raise ValueError("EEA/Norway NFP observation crossed non-authorizing boundary")
    if nfp.get("state") not in {
        "ROMANIA_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY_NON_AUTHORIZING",
        "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY",
    }:
        raise ValueError("EEA/Norway NFP observation state drift")

    calls = receipt.get("call_discovery")
    if not isinstance(calls, list) or not calls:
        raise ValueError("EEA/Norway Romania call discovery missing")
    seen: set[str] = set()
    for row in calls:
        if not isinstance(row, Mapping):
            raise ValueError("EEA/Norway call discovery malformed")
        url = str(row.get("url") or "")
        if not url.startswith("https://eeagrants.org/en/eea-civil-society-fund-romania/calls/"):
            raise ValueError("EEA/Norway call discovery left official call surface")
        if url in seen:
            raise ValueError("EEA/Norway call discovery duplicate URL")
        seen.add(url)
        if row.get("observation_state") != "CALL_DISCOVERY_ONLY":
            raise ValueError("EEA/Norway call discovery attempted material state")
        for key in ("open_call_authorized", "deadline_authorized", "budget_authorized", "eligibility_authorized"):
            if row.get(key) is not False:
                raise ValueError(f"EEA/Norway call discovery attempted authorization: {key}")

    expected = sha256_json(
        {
            "programme_fit_evidence": fit,
            "programmes": programmes,
            "programming_observations": programming,
            "national_focal_point_observation": nfp,
            "call_discovery": calls,
            "source_hashes": [row["sha256"] for row in sources],
        }
    )
    if receipt.get("semantic_fingerprint") != expected:
        raise ValueError("EEA/Norway Romania programme watch semantic fingerprint mismatch")


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    fetched_at = fetched_at or utc_now()
    fetcher = fetcher or default_fetch
    urls = {
        "romania-cooperation": ROMANIA_COOPERATION_URL,
        "eea-mou": EEA_MOU_URL,
        "norway-mou": NORWAY_MOU_URL,
        "nfp-directory": NFP_DIRECTORY_URL,
        "civil-society-calls": CIVIL_SOCIETY_CALLS_URL,
    }
    raw: dict[str, bytes] = {}
    meta: dict[str, Mapping[str, Any]] = {}
    for key, url in urls.items():
        raw[key], meta[key] = fetcher(url)
    receipt = build_receipt(
        sources_raw=raw,
        sources_meta=meta,
        fetched_at=fetched_at,
        run_id=run_id,
    )
    return receipt, raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    receipt, raw = collect(run_id=args.run_id)
    (out_dir / "eea-norway-romania-programme-watch.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    names = {
        "romania-cooperation": "romania-cooperation.html",
        "eea-mou": "romania-eea-mou.html",
        "norway-mou": "romania-norway-mou.html",
        "nfp-directory": "fmo-national-focal-points.html",
        "civil-society-calls": "romania-civil-society-calls.html",
    }
    for key, body in raw.items():
        (raw_dir / names[key]).write_bytes(body)
    print(json.dumps({
        "schema": receipt["schema"],
        "source_health": receipt["source_health"],
        "programme_count": len(receipt["programmes"]),
        "call_discovery_count": len(receipt["call_discovery"]),
        "nfp_state": receipt["national_focal_point_observation"]["state"],
        "semantic_fingerprint": receipt["semantic_fingerprint"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
