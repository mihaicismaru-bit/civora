#!/usr/bin/env python3
"""Read-only exact-call inventory scout for the official MySMIS reporting table.

This diagnostic exists to close the gap between a page-level semantic hash and
call-level identity. It never authorizes publication or material facts. The
listing's volatile project/contract counters are retained as diagnostics but
excluded from the material semantic fingerprint.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as html_lib
import json
import os
import re
import ssl
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(
    os.getenv(
        "MYSMIS_CALL_INVENTORY_OUT",
        ROOT / "partener-eu" / "validation" / "mysmis_call_inventory_latest.json",
    )
)
CANONICAL_URL = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
EXPECTED_HOST = "reporting.mysmis2021.gov.ro"
EXPECTED_PATH = "/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
PARSER_VERSION = "MYSMIS_EXACT_CALL_INVENTORY_V2"
UA = "PARTENER.EU-CIVORA-MySMIS-ExactCallInventory/1.0 (+https://partener.eu)"
MAX_BYTES = 5_000_000


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_id() -> str:
    return os.getenv("GITHUB_RUN_ID") or os.getenv("GITHUB_SHA") or f"local-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def key_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def decode_js_unicode(value: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), html_lib.unescape(value or ""))


def call_code_from_href(href: str) -> str | None:
    decoded = decode_js_unicode(href)
    match = re.search(r"[?&]p201_cod_apel=([^&'\"\s,)]+)", decoded, re.I)
    if not match:
        return None
    value = match.group(1)
    for _ in range(3):
        unquoted = urllib.parse.unquote(value)
        if unquoted == value:
            break
        value = unquoted
    value = clean(value)
    return value or None


class ReportTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self.row: list[dict[str, Any]] | None = None
        self.cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"tag": tag, "text": [], "hrefs": []}
        elif tag == "a" and self.cell is not None:
            href = dict(attrs).get("href")
            if href:
                self.cell["hrefs"].append(href)

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.cell["text"] = clean(" ".join(self.cell["text"]))
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
            self.cell = None


HEADER_ALIASES = {
    "program operational": "programme",
    "tip apel": "callType",
    "apel": "callTitle",
    "stare apel": "status",
    "entitati participante": "entities",
    "nr schite": "drafts",
    "nr proiecte inregistrate depuse": "submitted",
    "nr contracte": "contracts",
    "nr proiecte retrase": "withdrawn",
    "buget nerambursabil apel": "callBudgetRon",
    "buget total proiecte schite depuse": "totalProjectBudgetRon",
    "buget nerambursabil proiecte depuse": "submittedGrantBudgetRon",
    "info": "info",
}
MATERIAL_FIELDS = ("callCode", "programme", "callType", "callTitle", "status", "callBudgetRon")
OPERATIONAL_FIELDS = ("entities", "drafts", "submitted", "contracts", "withdrawn", "totalProjectBudgetRon", "submittedGrantBudgetRon")


def total_from_html(raw: str) -> int | None:
    match = re.search(r"\b\d+\s*-\s*\d+\s*of\s*([0-9][0-9.,]*)\b", clean(raw), re.I)
    return int(re.sub(r"\D", "", match.group(1))) if match else None


def semantic_sha(rows: list[dict[str, Any]]) -> str:
    payload = [{field: row.get(field, "") for field in MATERIAL_FIELDS} for row in sorted(rows, key=lambda row: row["callCode"])]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def parse_inventory(raw: str) -> dict[str, Any]:
    if "Apeluri validate 2021-2027" not in raw:
        raise RuntimeError("expected MySMIS registry marker missing")
    parser = ReportTableParser()
    parser.feed(raw)

    header: dict[str, int] | None = None
    data_rows: list[list[dict[str, Any]]] = []
    for row in parser.rows:
        mapped = {HEADER_ALIASES.get(key_text(cell["text"])): index for index, cell in enumerate(row)}
        if all(name in mapped for name in ("programme", "callType", "callTitle", "status", "callBudgetRon", "info")):
            header = {name: index for name, index in mapped.items() if name}
            continue
        if header and len(row) > max(header.values()):
            data_rows.append(row)

    if not header:
        raise RuntimeError("MySMIS registry headers not recognized")

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_by_code: dict[str, dict[str, Any]] = {}
    conflicting_duplicates: list[str] = []
    mirrored_duplicates: list[str] = []
    for position, cells in enumerate(data_rows, 1):
        programme = clean(cells[header["programme"]]["text"])
        call_title = clean(cells[header["callTitle"]]["text"])
        if not programme or not call_title:
            continue
        info_cell = cells[header["info"]]
        codes = [call_code_from_href(href) for href in info_cell.get("hrefs", [])]
        codes = [code for code in codes if code]
        code = codes[0] if len(set(codes)) == 1 else None
        if not code:
            failures.append({"row": position, "programme": programme, "callTitle": call_title, "reason": "EXACT_CALL_CODE_MISSING_OR_AMBIGUOUS"})
            continue

        def value(name: str) -> str:
            index = header.get(name)
            return clean(cells[index]["text"]) if index is not None and index < len(cells) else ""

        item = {
            "callCode": code,
            "programme": programme,
            "callType": value("callType"),
            "callTitle": call_title,
            "status": value("status"),
            "callBudgetRon": value("callBudgetRon"),
            "operationalCounters": {field: value(field) for field in OPERATIONAL_FIELDS},
        }
        previous = seen_by_code.get(code)
        if previous is not None:
            if previous == item:
                mirrored_duplicates.append(code)
            else:
                conflicting_duplicates.append(code)
            continue
        seen_by_code[code] = item
        rows.append(item)

    if not data_rows:
        raise RuntimeError("MySMIS registry parsed with zero visible data rows")

    total = total_from_html(raw)
    resolved_row_count = len(rows) + len(mirrored_duplicates)
    exact_ok = not failures and not conflicting_duplicates and resolved_row_count == len(data_rows)
    return {
        "validatedCallCount": total,
        "visibleRowCount": len(data_rows),
        "exactIdentityRowCount": len(rows),
        "identityFailures": failures,
        "duplicateCallCodes": sorted(set(conflicting_duplicates)),
        "mirroredDuplicateCallCodes": sorted(set(mirrored_duplicates)),
        "mirroredDuplicateRowCount": len(mirrored_duplicates),
        "exactIdentityCompleteForVisiblePage": exact_ok,
        "pageComplete": total is not None and exact_ok and len(data_rows) == total,
        "paginationRequired": total is None or len(data_rows) < total,
        "materialSemanticSha256": semantic_sha(rows) if rows else None,
        "rows": rows,
    }



# Offline replay boundary only. The live scout remains single-page until the
# official APEX pagination request/response contract is independently acquired.
REPLAY_VERSION = "MYSMIS_PAGINATED_RECEIPT_REPLAY_V1"
MAX_REPLAY_PAGES = 100
MAX_REPLAY_BYTES = 50_000_000


def replay_paginated_inventory(
    pages: list[tuple[dict[str, Any], bytes]], expected_run_id: str
) -> dict[str, Any]:
    """Verify a complete ordered set of full official HTML page receipts.

    Input is externally acquired raw bytes plus a receipt, never a URL to fetch.
    Reject ambiguity rather than claiming completeness. This does not establish
    receipt authenticity by itself; the trusted acquisition handoff is required.
    No canonical writes, freshness reset, or status admission occur here.
    """
    if not expected_run_id or not pages or len(pages) > MAX_REPLAY_PAGES:
        raise ValueError("invalid replay run or page count")
    if sum(len(raw) for _, raw in pages) > MAX_REPLAY_BYTES:
        raise ValueError("replay byte limit exceeded")
    next_row = 1
    total = None
    unique: dict[str, dict[str, Any]] = {}
    mirrored = 0
    seen_hashes: set[str] = set()
    seen_identity_pages: set[tuple[str, ...]] = set()
    coverage = []
    for receipt, raw in pages:
        # V1 accepts only full documents with the exact stable official URL.
        # Session-specific URLs / APEX fragments need a separately reviewed
        # transport contract; never persist session cookies or tokens here.
        required = {
            "url": CANONICAL_URL,
            "runId": expected_run_id,
            "parserVersion": PARSER_VERSION,
            "sourceFamily": "ROMANIA_MIPE_MYSMIS",
            "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
            "observationState": "ACQUIRED_CANDIDATE_ONLY",
            "programmeFamily": "ROMANIA_MULTI_PROGRAMME",
        }
        if any(receipt.get(k) != v for k, v in required.items()):
            raise ValueError("receipt provenance mismatch")
        if receipt.get("httpStatus") != 200 or "html" not in str(receipt.get("contentType", "")).lower():
            raise ValueError("invalid page transport receipt")
        try:
            fetched_at = dt.datetime.fromisoformat(receipt["fetchedAt"].replace("Z", "+00:00"))
            if fetched_at.utcoffset() != dt.timedelta(0):
                raise ValueError("timestamp must be UTC")
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise ValueError("invalid fetchedAt") from exc
        if not raw or len(raw) >= MAX_BYTES:
            raise ValueError("empty or potentially truncated page")
        digest = hashlib.sha256(raw).hexdigest()
        if receipt.get("rawSha256") != digest or digest in seen_hashes:
            raise ValueError("raw digest mismatch or repeated page")
        seen_hashes.add(digest)
        doc = raw.decode("utf-8", errors="strict")
        if not re.search(r"</html>\s*$", doc, re.I):
            raise ValueError("incomplete HTML document")
        ranges = {
            tuple(int(re.sub(r"\D", "", value)) for value in match)
            for match in re.findall(r"\b([0-9][0-9.,]*)\s*-\s*([0-9][0-9.,]*)\s*of\s*([0-9][0-9.,]*)\b", clean(doc), re.I)
        }
        if len(ranges) != 1:
            raise ValueError("missing or ambiguous pagination range")
        start, end, reported_total = ranges.pop()
        if total is None:
            total = reported_total
        if reported_total != total or start != next_row or not start <= end <= total:
            raise ValueError("noncontiguous page range or changing total")
        parsed = parse_inventory(doc)
        if (
            not parsed["exactIdentityCompleteForVisiblePage"]
            or parsed["validatedCallCount"] != total
            or parsed["visibleRowCount"] != end - start + 1
        ):
            raise ValueError("page identity or row count mismatch")
        identities = tuple(sorted(row["callCode"] for row in parsed["rows"]))
        if not identities or identities in seen_identity_pages:
            raise ValueError("repeated page identity set")
        seen_identity_pages.add(identities)
        mirrored += parsed["mirroredDuplicateRowCount"]
        for row in parsed["rows"]:
            code = row["callCode"]
            if code in unique:
                if unique[code] != row:
                    raise ValueError("conflicting cross-page duplicate")
                mirrored += 1
            else:
                unique[code] = row
        coverage.append({
            **required,
            "fetchedAt": receipt["fetchedAt"],
            "rawSha256": digest,
            "httpStatus": 200,
            "contentType": receipt["contentType"],
            "firstRow": start,
            "lastRow": end,
            "reportedTotal": total,
        })
        next_row = end + 1
    if total is None or next_row != total + 1 or len(unique) + mirrored != total:
        raise ValueError("incomplete inventory coverage")
    rows = sorted(unique.values(), key=lambda row: row["callCode"])
    return {
        "schema": REPLAY_VERSION,
        "runId": expected_run_id,
        "status": "COMPLETE_REPLAY_CANDIDATE_ONLY",
        "validatedCallCount": total,
        "exactIdentityRowCount": len(rows),
        "mirroredDuplicateRowCount": mirrored,
        "pageCount": len(coverage),
        "pageReceipts": coverage,
        "coverageSha256": hashlib.sha256(json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "materialSemanticSha256": semantic_sha(rows),
        "rows": rows,
        "materialFactUse": False,
        "publishAuthorized": False,
        "openCallAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
        "publicationEffect": "NONE",
    }


def official_final_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == EXPECTED_HOST and parsed.path.rstrip("/") == EXPECTED_PATH.rstrip("/")


def fetch_html(timeout: int = 25) -> tuple[str, bytes, str]:
    request = urllib.request.Request(CANONICAL_URL, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ro,en;q=0.7", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        raw_bytes = response.read(MAX_BYTES)
        status = getattr(response, "status", 200)
    if not (200 <= status < 400):
        raise RuntimeError(f"unexpected HTTP status {status}")
    if not official_final_url(final_url):
        raise RuntimeError(f"redirected outside exact official MySMIS report: {final_url}")
    if "html" not in content_type.lower():
        raise RuntimeError(f"unexpected content type: {content_type}")
    return raw_bytes.decode("utf-8", errors="ignore"), raw_bytes, content_type


def build_payload(raw: str, raw_bytes: bytes, content_type: str) -> dict[str, Any]:
    inventory = parse_inventory(raw)
    integrity = inventory["exactIdentityCompleteForVisiblePage"]
    return {
        "schema": "CIVORA_MYSMIS_EXACT_CALL_INVENTORY_V1",
        "observedAt": now(),
        "runId": run_id(),
        "parserVersion": PARSER_VERSION,
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "canonicalUrl": CANONICAL_URL,
        "rawSha256": hashlib.sha256(raw_bytes).hexdigest(),
        "contentType": content_type,
        "status": "PASS_CANDIDATE_ONLY" if integrity else "PROVISIONAL_FAIL_CLOSED",
        "materialFactUse": False,
        "publishAuthorized": False,
        "openCallAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
        "candidateInventory": inventory,
        "semanticPolicy": {
            "identity": "exact p201_cod_apel from each official Info link",
            "includedInMaterialSemanticHash": list(MATERIAL_FIELDS),
            "excludedAsOperationallyVolatile": list(OPERATIONAL_FIELDS),
            "identicalDuplicateRows": "collapse only when the full normalized call row, including operational counters, is identical; conflicting repeats remain fail-closed",
            "publicationEffect": "NONE",
            "nextRequiredStep": "paginate the official report and reconcile each exact call identity before any material publication",
        },
    }


def transport_failure_payload(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "CIVORA_MYSMIS_EXACT_CALL_INVENTORY_V1",
        "observedAt": now(),
        "runId": run_id(),
        "parserVersion": PARSER_VERSION,
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "canonicalUrl": CANONICAL_URL,
        "status": "SOURCE_UNAVAILABLE_FAIL_CLOSED",
        "materialFactUse": False,
        "publishAuthorized": False,
        "openCallAuthorized": False,
        "error": f"{type(exc).__name__}: {exc}",
        "publicationEffect": "NONE",
    }


def main() -> int:
    parser_integrity_failure = False
    try:
        raw, raw_bytes, content_type = fetch_html()
        payload = build_payload(raw, raw_bytes, content_type)
        parser_integrity_failure = payload["status"] == "PROVISIONAL_FAIL_CLOSED"
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        payload = transport_failure_payload(exc)
    except Exception as exc:  # fetched/parsing semantic drift must be visible to the gate
        payload = transport_failure_payload(exc)
        payload["status"] = "PARSER_SEMANTIC_DRIFT_FAIL_CLOSED"
        parser_integrity_failure = True
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": payload["status"],
        "validatedCallCount": (payload.get("candidateInventory") or {}).get("validatedCallCount"),
        "visibleRowCount": (payload.get("candidateInventory") or {}).get("visibleRowCount"),
        "exactIdentityRowCount": (payload.get("candidateInventory") or {}).get("exactIdentityRowCount"),
        "paginationRequired": (payload.get("candidateInventory") or {}).get("paginationRequired"),
        "publishAuthorized": False,
        "output": str(OUT),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if parser_integrity_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
