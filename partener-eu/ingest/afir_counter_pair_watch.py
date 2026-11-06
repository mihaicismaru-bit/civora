#!/usr/bin/env python3
"""AFIR's two official dynamic counters: paired, non-authorizing raw evidence.

Acquisition and read-only reconciliation only. NEVER infer OPEN_CALL, available
budget, eligibility or editorial publication from either counter. When the
agency and delegated-submission surfaces differ, retain both source originals
and report a review task rather than selecting the newest/largest number.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from build_afir_live_funds import parse_rows, parse_table

AGENCY_URL = "https://www.afir.ro/finantare/contor-fonduri-disponibile/"
DELEGATED_URL = "https://depunerepspac.afir.ro/Sesiune/Lista"
URLS = {"agency": AGENCY_URL, "delegated": DELEGATED_URL}
PARSER_VERSION = "afir-dr12-official-counter-pair-v6"
SECTORS = ("SECTOR ZOOTEHNIC", "ALTE SECTOARE")
MAX_BYTES = 5_000_000
MAX_PAIR_SECONDS = 90
MAX_CACHE_SKEW_SECONDS = 300
HEADERS = {
    "User-Agent": "PARTENER.EU-AFIR-Paired-Source-Health/1.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("AFIR counter redirects require separate authority review")


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError("counter receipt requires UTC timestamp")
    return parsed


def strict_url(url: str, source: str) -> bool:
    if url != URLS[source]:
        return False
    p = urllib.parse.urlsplit(url)
    return (
        p.scheme == "https" and p.hostname in ("www.afir.ro", "depunerepspac.afir.ro")
        and p.username is None and p.password is None and p.port in (None, 443)
        and not p.fragment and not p.query
    )


def acquire(source: str) -> dict:
    url = URLS[source]
    if not strict_url(url, source):
        raise ValueError("untrusted AFIR source URL")
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with opener.open(req, timeout=25) as res:
        observed = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        if res.geturl() != url or getattr(res, "status", 200) != 200:
            raise ValueError("counter authority or HTTP status mismatch")
        ctype = res.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            raise ValueError("counter returned non-HTML source")
        # The server may ignore Accept-Encoding: identity. Never persist or
        # parse compressed bytes as an official HTML counter receipt.
        content_encoding = (res.headers.get("Content-Encoding") or "identity").strip().lower()
        if content_encoding != "identity":
            raise ValueError("unsupported encoded AFIR counter body")
        raw = res.read(MAX_BYTES + 1)
        announced = res.headers.get("Content-Length")
        if (
            not raw or len(raw) > MAX_BYTES
            or (announced is not None and
                (not announced.strip().isdigit() or int(announced) != len(raw)))
        ):
            raise ValueError("AFIR counter body missing, truncated or oversized")
        return {
            "ok": True, "url": url, "status": 200, "content_type": ctype,
            "data": raw, "fetched_at_utc": observed,
            "content_encoding": content_encoding,
            "source_date_header": res.headers.get("Date"),
            "source_etag": res.headers.get("ETag"),
            "source_last_modified": res.headers.get("Last-Modified"),
            "source_age_header": res.headers.get("Age"),
            "source_cache_control": res.headers.get("Cache-Control"),
        }


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def normalize_sector(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value).upper()
    for sector in SECTORS:
        if value.startswith("COMPONENTA " + sector):
            return sector
    return None


def parse_agency(raw: bytes) -> dict[str, dict]:
    rows = parse_rows(parse_table(raw))
    found = {}
    for row in rows:
        if row["interventionCode"] != "DR-12":
            continue
        sector = normalize_sector(row["sector"])
        if not sector or sector in found:
            raise ValueError("unknown/duplicate AFIR DR-12 component")
        found[sector] = {
            "opens_at": row["opensAtLocal"],
            "session_allocation_eur": row["sessionAllocationEur"],
            "submitted_value_eur": row["submittedPublicValueEur"],
            "submitted_count": row["submittedProjectCount"],
            "funds_eur": row["availableFundsEur"],
            "funds_status": row["availableFundsStatus"],
            "closes_at": row["closesAtLocal"],
        }
    if set(found) != set(SECTORS):
        raise ValueError("AFIR counter lacks two exact DR-12 components")
    return found


def parse_delegated_amount(value: str) -> str | None:
    value = value.strip().replace("\u00a0", "")
    if value in ("-", "–", "—"):
        return None
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", value):
        raise ValueError("invalid delegated counter monetary value")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif "." in value and not re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        pass  # delegated platform uses dot decimals, e.g. 120000.00000
    else:
        value = value.replace(".", "")
    try:
        return f"{Decimal(value):.2f}"
    except InvalidOperation as exc:
        raise ValueError("invalid delegated decimal") from exc


def parse_delegated(raw: bytes) -> dict[str, dict]:
    parser = TextOnly()
    parser.feed(raw.decode("utf-8", "replace"))
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    # Delegated DR-12 session and each component must agree on their time window.
    # A conflicting/duplicated session header cannot be masked by matching cards.
    # Multiple DR-12 session banners are conflicting evidence even if one
    # is malformed: do not accept a single valid match and silently ignore it.
    banner = r"\bSesiune depunere dosare de finan.are\s+DR[-–]12\b"
    if len(re.findall(banner, text, flags=re.I)) != 1:
        raise ValueError("delegated DR-12 session banner missing or ambiguous")
    session_headers = re.findall(
        banner +
        r"\s+DAT.\s+.NCEPUT\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"
        r"\s*(?:\|\s*)?DAT.\s+FINAL\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})",
        text, flags=re.I,
    )
    if len(session_headers) != 1:
        raise ValueError("delegated DR-12 session header missing, duplicate or malformed")
    session_open, session_close = session_headers[0]
    chunks = re.split(r"\bDESCRIERE\s+ALOCARE\b", text, flags=re.I)
    found = {}
    for chunk in chunks[1:]:
        if not re.search(r"\bDR[-–]12\b", chunk[:600], re.I):
            continue
        component_pattern = r"\bComponenta\s+(SECTOR\s+ZOOTEHNIC|ALTE\s+SECTOARE)\b"
        components = re.findall(component_pattern, chunk[:600], re.I)
        if len(components) != 1:
            raise ValueError("missing or ambiguous delegated DR-12 component")
        sector = re.sub(r"\s+", " ", components[0]).upper()
        if sector in found:
            raise ValueError("duplicate delegated DR-12 component")
        # Every material metric must have ONE label within this exact card.
        # Otherwise a second contradictory field is silently hidden by
        # re.search selecting the first apparently valid value.
        labels = (
            r"\bDAT.\s+.I\s+OR.\s+LANSARE\b",
            r"\bALOCARE\s+FINANCIAR.\b",
            r"\bDAT.\s+.I\s+OR.\s+.NCHIDERE\b",
            r"\bVALOAREA\s+PROIECTELOR\s+DEPUSE\b",
            r"\bNUM.R\s+DOSARE\s+DEPUSE\b",
            r"\bFONDURI\s+DISPONIBILE\b",
        )
        if any(len(re.findall(label, chunk, re.I)) != 1 for label in labels):
            raise ValueError("delegated DR-12 card contains missing or repeated material field")
        opened = re.search(
            r"\bDAT.\s+.I\s+OR.\s+LANSARE\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})", chunk, re.I
        )
        allocation = re.search(
            r"\bALOCARE\s+FINANCIAR.\s+([-–—]|\d+(?:[.,]\d+)*)", chunk, re.I
        )
        submitted = re.search(
            r"\bVALOAREA\s+PROIECTELOR\s+DEPUSE\b(?:\s*\*\s*1)?\s+([-–—]|\d+(?:[.,]\d+)*)", chunk, re.I
        )
        count = re.search(r"\bNUM.R\s+DOSARE\s+DEPUSE\b\s+(\d+)\b", chunk, re.I)
        funds = re.search(
            r"\bFONDURI\s+DISPONIBILE\b(?:\s*\*?\s*2)?\s+"
            r"(FONDURI\s+EPUIZATE|[-–—]|\d+(?:[.,]\d+)*)",
            chunk, re.I,
        )
        # A withheld dash may be followed by punctuation rather than a word
        # boundary; avoid treating missing values as zeros.
        if funds is None:
            funds = re.search(r"\bFONDURI\s+DISPONIBILE\b(?:\s*\*?\s*2)?\s+([-–—])(?=\s|$)", chunk, re.I)
        closed = re.search(r"\bDAT.\s+.I\s+OR.\s+.NCHIDERE\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})", chunk, re.I)
        if not count or not funds or not closed or not opened or not allocation or not submitted:
            raise ValueError("delegated DR-12 dates/allocation/submitted-value/count/funds not parseable")
        funds_raw = funds.group(1).strip().upper()
        amount = "0.00" if funds_raw == "FONDURI EPUIZATE" else parse_delegated_amount(funds_raw)
        if opened.group(1) != session_open or closed.group(1) != session_close:
            raise ValueError("delegated DR-12 component window differs from session header")
        day, month, year = closed.group(1)[:10].split("/")
        open_day, open_month, open_year = opened.group(1)[:10].split("/")
        found[sector] = {
            "opens_at": f"{open_day}.{open_month}.{open_year} {opened.group(1)[11:]}",
            "session_allocation_eur": parse_delegated_amount(allocation.group(1)),
            "submitted_value_eur": parse_delegated_amount(submitted.group(1)),
            "submitted_count": int(count.group(1)),
            "funds_eur": amount,
            "funds_status": ("EXHAUSTED" if funds_raw == "FONDURI EPUIZATE" else
                             "UNKNOWN" if amount is None else "REPORTED"),
            "closes_at": f"{day}.{month}.{year} {closed.group(1)[11:]}",
        }
    if set(found) != set(SECTORS):
        raise ValueError("delegated page lacks two exact DR-12 allocations")
    return found


def reconcile(raws: dict[str, bytes], span_seconds: float) -> dict:
    try:
        agency, delegated = parse_agency(raws["agency"]), parse_delegated(raws["delegated"])
    except (ValueError, KeyError) as exc:
        return {
            "observation_state": "SOURCE_COUNTER_PARSE_REVIEW",
            "reason": str(exc), "components": {}, "material_fact_action": "NONE",
        }
    comparable = {}
    any_count_or_date_difference = False
    any_financial_difference = False
    any_funds_unreported = False
    any_non_fund_amount_unreported = False
    for sector in SECTORS:
        a, b = agency[sector], delegated[sector]
        count_equal = a["submitted_count"] == b["submitted_count"]
        open_equal = a["opens_at"] == b["opens_at"]
        close_equal = a["closes_at"] == b["closes_at"]
        checks = {}
        for key in ("session_allocation_eur", "submitted_value_eur", "funds_eur"):
            known = a[key] is not None and b[key] is not None
            # The parser canonizes monetary amounts to two decimal places.
            matches = (a[key] == b[key]) if known else None
            checks[key] = {"comparable": known, "matches_if_comparable": matches}
            any_financial_difference |= matches is False
            if not known:
                if key == "funds_eur":
                    any_funds_unreported = True
                else:
                    any_non_fund_amount_unreported = True
        # An exhausted counter must not silently equate to a reported zero.
        funds_status_equal = a["funds_status"] == b["funds_status"]
        if checks["funds_eur"]["comparable"] and not funds_status_equal:
            any_financial_difference = True
        any_count_or_date_difference |= not count_equal or not open_equal or not close_equal
        comparable[sector] = {
            "agency": a, "delegated": b,
            "submitted_count_matches": count_equal,
            "opening_time_matches": open_equal,
            "closing_time_matches": close_equal,
            "amount_checks": checks,
            "funds_status_matches": funds_status_equal,
            "funds_comparable": checks["funds_eur"]["comparable"],
            "funds_match_if_comparable": checks["funds_eur"]["matches_if_comparable"],
        }
    state = (
        "SOURCE_COUNTER_DIVERGENCE_REVIEW"
        if any_count_or_date_difference or any_financial_difference else
        "SOURCE_COUNTER_CAPTURE_SKEW_REVIEW"
        if span_seconds > MAX_PAIR_SECONDS else
        "SOURCE_COUNTER_NON_FUND_AMOUNTS_WITHHELD_REVIEW"
        if any_non_fund_amount_unreported else
        "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW"
        if any_funds_unreported else
        "SOURCE_COUNTER_PAIR_MATCH_REVIEW"
    )
    return {
        "observation_state": state, "components": comparable,
        "capture_span_seconds": span_seconds, "material_fact_action": "NONE",
    }


def cache_health(source_meta: dict[str, dict]) -> dict:
    """Assess response-cache headers without inventing a source freshness claim.

    Receipt capture times reflect when our client read the HTTP response, NOT
    necessarily when the official server generated its cached body. Preserve
    stale or malformed server headers as review evidence instead of treating a
    fast paired fetch as semantically contemporaneous.
    """
    findings = {}
    for source in URLS:
        meta = source_meta[source]
        reasons = []
        age = meta.get("age_header")
        if age is not None:
            if not isinstance(age, str) or not re.fullmatch(r"\\d+", age.strip()):
                reasons.append("INVALID_HTTP_AGE")
            elif int(age.strip()) > MAX_CACHE_SKEW_SECONDS:
                reasons.append("HTTP_AGE_EXCEEDS_300_SECONDS")
        server_date = meta.get("date_header")
        if server_date is not None:
            try:
                if not isinstance(server_date, str):
                    raise ValueError("non-string HTTP Date")
                parsed = parsedate_to_datetime(server_date)
                if parsed.tzinfo is None:
                    raise ValueError("timezone-free HTTP Date")
                delta = abs((timestamp(meta["fetched_at_utc"]) -
                             parsed.astimezone(dt.timezone.utc)).total_seconds())
                if delta > MAX_CACHE_SKEW_SECONDS:
                    reasons.append("HTTP_DATE_SKEW_EXCEEDS_300_SECONDS")
            except (TypeError, ValueError, OverflowError, IndexError):
                reasons.append("INVALID_HTTP_DATE")
        findings[source] = {
            "cache_status": "REVIEW_REQUIRED" if reasons else
                            "UNKNOWN" if age is None and server_date is None else
                            "NO_STALENESS_INDICATOR",
            "reasons": reasons,
        }
    return {"review_required": any(v["reasons"] for v in findings.values()),
            "sources": findings}


def reconcile_with_cache(raws: dict[str, bytes], span: float, sources: dict[str, dict]) -> dict:
    normalized = reconcile(raws, span)
    health = cache_health(sources)
    normalized["cache_health"] = health
    # Preserve the higher-priority parser/divergence diagnosis. A cached
    # otherwise-matching pair is never presented as a fresh matched pair.
    if health["review_required"] and normalized["observation_state"] in (
        "SOURCE_COUNTER_PAIR_MATCH_REVIEW",
        "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW",
        "SOURCE_COUNTER_NON_FUND_AMOUNTS_WITHHELD_REVIEW",
    ):
        normalized["pre_cache_observation_state"] = normalized["observation_state"]
        normalized["observation_state"] = "SOURCE_COUNTER_CACHE_FRESHNESS_REVIEW"
    return normalized


def capture(fetched: dict[str, dict], destination: Path, run_id: str, run_attempt: str = "1") -> dict:
    if not run_id or not run_id.isdigit() or not run_attempt.isdigit() or destination.exists():
        raise ValueError("counter receipt must be new and run-scoped")
    raw_by_source = {}
    sources = {}
    for source, url in URLS.items():
        row = fetched[source]
        data = row.get("data")
        if (
            row.get("ok") is not True or row.get("url") != url
            or row.get("status") != 200
            or "html" not in str(row.get("content_type") or "").lower()
            or row.get("content_encoding", "identity") != "identity"
            or not isinstance(data, bytes) or not data or len(data) > MAX_BYTES
            or not strict_url(url, source)
        ):
            raise ValueError("incomplete or untrusted paired official source")
        stamp = timestamp(row["fetched_at_utc"])
        raw_by_source[source] = data
        sources[source] = {
            "requested_url": url, "final_url": url, "fetched_at_utc": stamp.isoformat().replace("+00:00", "Z"),
            "raw_file": f"{source}.raw.html", "sha256": hashlib.sha256(data).hexdigest(),
            "byte_count": len(data), "content_type": row["content_type"],
            "content_encoding": "identity", "http_status": 200,
            "date_header": row.get("source_date_header"), "etag": row.get("source_etag"),
            "last_modified": row.get("source_last_modified"),
            "age_header": row.get("source_age_header"),
            "cache_control": row.get("source_cache_control"),
        }
    stamps = [timestamp(sources[s]["fetched_at_utc"]) for s in URLS]
    elapsed = (max(stamps) - min(stamps)).total_seconds()
    normalized = reconcile_with_cache(raw_by_source, elapsed, sources)
    manifest = {
        "schema_version": "1.0", "run_id": run_id, "run_attempt": run_attempt,
        "parser_version": PARSER_VERSION, "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR", "authority_class": "T1_OFFICIAL_AGENCY_DELEGATED_PLATFORM",
        "observation_state": normalized["observation_state"],
        "sources": sources, "reconciliation": normalized,
        "last_known_good_action": "PRESERVE",
        "open_call_authorized": False, "publish_authorized": False,
        "distribution_authorized": False, "budget_authorized": False,
        "eligibility_authorized": False, "material_fact_action": "NONE",
    }
    destination.mkdir(parents=True, exist_ok=False)
    for source in URLS:
        (destination / sources[source]["raw_file"]).write_bytes(raw_by_source[source])
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def replay(destination: Path) -> dict:
    # Evidence is a closed immutable file set. Reject arbitrary files and
    # symlinks even when their pointed-to bytes would match the manifest.
    expected_files = {"manifest.json", *(f"{source}.raw.html" for source in URLS)}
    if (not destination.is_dir() or destination.is_symlink()
            or {entry.name for entry in destination.iterdir()} != expected_files
            or any(entry.is_symlink() or not entry.is_file() for entry in destination.iterdir())):
        raise ValueError("counter proof has orphaned, missing or symlinked files")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("parser_version") != PARSER_VERSION
        or not str(manifest.get("run_id", "")).isdigit()
        or not str(manifest.get("run_attempt", "")).isdigit()
        or manifest.get("programme") != "PS_PAC_2023_2027/DR12"
        or manifest.get("source_family") != "AFIR"
        or manifest.get("authority_class") != "T1_OFFICIAL_AGENCY_DELEGATED_PLATFORM"
        or manifest.get("last_known_good_action") != "PRESERVE"
        or any(manifest.get(key) is not False for key in
               ("open_call_authorized", "publish_authorized", "distribution_authorized",
                "budget_authorized", "eligibility_authorized"))
        or manifest.get("material_fact_action") != "NONE"
        or set(manifest.get("sources", {})) != set(URLS)
    ):
        raise ValueError("counter-pair manifest authorization/identity changed")
    raws = {}
    stamps = []
    for source, url in URLS.items():
        meta = manifest["sources"][source]
        if (
            meta.get("requested_url") != url or meta.get("final_url") != url
            or meta.get("raw_file") != f"{source}.raw.html"
            or meta.get("http_status") != 200
            or "html" not in str(meta.get("content_type", "")).lower()
            or meta.get("content_encoding") != "identity"
            or not strict_url(url, source)
        ):
            raise ValueError("counter source identity changed")
        stamps.append(timestamp(meta["fetched_at_utc"]))
        raw = (destination / meta["raw_file"]).read_bytes()
        if (
            not raw or len(raw) > MAX_BYTES or len(raw) != meta.get("byte_count")
            or hashlib.sha256(raw).hexdigest() != meta.get("sha256")
        ):
            raise ValueError("counter raw proof changed")
        raws[source] = raw
    elapsed = (max(stamps) - min(stamps)).total_seconds()
    expected = reconcile_with_cache(raws, elapsed, manifest["sources"])
    if expected != manifest.get("reconciliation") or expected["observation_state"] != manifest.get("observation_state"):
        raise ValueError("counter semantic replay changed")
    return {"verified": True, "observation_state": expected["observation_state"],
            "run_id": manifest["run_id"], "publish_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path)
    args = parser.parse_args()
    if args.replay_dir:
        print(json.dumps(replay(args.replay_dir), ensure_ascii=False, sort_keys=True))
        return 0
    dest_env = os.environ.get("PARTENER_AFIR_COUNTER_PAIR_EVIDENCE_DIR")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not dest_env or not run_id:
        print("counter-pair acquisition requires run-scoped evidence directory and run_id", file=sys.stderr)
        return 2
    try:
        sources = {source: acquire(source) for source in URLS}
        receipt = capture(sources, Path(dest_env), run_id, os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        print(json.dumps({"status": receipt["observation_state"], "run_id": run_id,
                          "publish_authorized": False}, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Acquisition errors cannot delete evidence or alter the public LKG.
        print(json.dumps({"status": "SOURCE_COUNTER_PAIR_UNAVAILABLE_REVIEW",
                          "error_type": type(exc).__name__, "publish_authorized": False,
                          "last_known_good_action": "PRESERVE"}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
