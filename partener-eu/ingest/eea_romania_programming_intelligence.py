#!/usr/bin/env python3
"""Fail-closed EEA/Norway Grants Romania 2021-2028 programming intelligence.

The Financial Mechanism Office programme map is useful for programme/operator watch
routing and applicant-fit research. It is not a call registry. No text on this page,
including words such as "open" or programme-level allocations, may authorize a call.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import ssl
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

SOURCE_URL = "https://eeagrants.org/en/fmo/news/renewed-cooperation-romania"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA and Norway Grants Romania 2021-2028"
AUTHORITY_CLASS = "EEA_FMO_ROMANIA_PROGRAMME_MAP"
PARSER_VERSION = "EEA_ROMANIA_PROGRAMMING_INTELLIGENCE_V2"
REGISTRY_PATH = Path(__file__).with_name("eea_romania_programming_registry.json")
EXPECTED_PATH = "/en/fmo/news/renewed-cooperation-romania"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
MAX_BYTES = 4_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"

MISSING_TO_CONFIRM_CALL = (
    "exact_call_identifier",
    "official_current_open_status",
    "exact_official_call_endpoint",
    "semantic_reconciliation",
)

_FUND_OPERATOR_RE = re.compile(
    r"^(?P<programme>.+?)\.\s+(?P<fund>.+?)\s+is\s+appointed\s+Fund\s+Operator\.?$",
    flags=re.IGNORECASE,
)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clean(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split()).strip()


def _require_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise RuntimeError("raw_hash must be a lowercase SHA-256 hex digest")
    return normalized


def _official_source_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-official EEA/FMO URL: {value}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected authority components in URL: {value}")
    if parsed.path.rstrip("/") != EXPECTED_PATH:
        raise ValueError(f"unexpected Romania programme-map path: {value}")
    return urlunparse(("https", host, EXPECTED_PATH, "", "", ""))


def _load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schemaVersion") != "1.1":
        raise RuntimeError("unsupported EEA Romania programming registry schemaVersion")
    source = registry.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("EEA Romania programming registry source object missing")
    expected_source = {
        "sourceUrl": SOURCE_URL,
        "publishedDate": "2026-05-12",
        "programmeFamily": SOURCE_FAMILY,
        "authorityClass": "T1_EEA_OFFICIAL_FMO",
        "observationState": "PROGRAMMING_PIPELINE",
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise RuntimeError(f"EEA Romania programming registry {key} drift")
    if not str(source.get("sourceId") or "").strip():
        raise RuntimeError("EEA Romania programming registry sourceId missing")
    programmes = registry.get("programmes")
    if not isinstance(programmes, list) or len(programmes) != 9:
        raise RuntimeError("EEA Romania programming registry must contain exactly nine programmes")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for row in programmes:
        if not isinstance(row, dict):
            raise RuntimeError("EEA Romania programming registry programme row must be an object")
        programme_id = str(row.get("programmeId") or "").strip()
        name = _clean(str(row.get("programme") or ""))
        grant = _clean(str(row.get("programmeGrantEvidence") or ""))
        operator = _clean(str(row.get("programmeOperator") or ""))
        fund_operator = _clean(str(row.get("fundOperator") or ""))
        if not programme_id or not name or not grant or not operator:
            raise RuntimeError("EEA Romania programming registry row missing programme identity/grant/operator")
        if programme_id in seen_ids or name.casefold() in seen_names:
            raise RuntimeError("EEA Romania programming registry contains duplicate programme identity")
        seen_ids.add(programme_id)
        seen_names.add(name.casefold())
        if "fundOperator" in row and not fund_operator:
            raise RuntimeError("EEA Romania programming registry fundOperator cannot be blank")
    return registry


def _registry_by_name(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["programme"]): row for row in registry["programmes"]}


class _VisibleTextParser(HTMLParser):
    """Collect visible text chunks independent of Drupal's presentation markup."""

    IGNORED = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in self.IGNORED:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.IGNORED and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = _clean(data)
        if value:
            self.chunks.append(value)


def fetch_url(url: str = SOURCE_URL, *, timeout: float = 20.0) -> dict[str, Any]:
    requested_url = _official_source_url(url)
    request = Request(
        requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        status = int(response.getcode() or 0)
        final_url = _official_source_url(response.geturl())
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {requested_url}")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"response exceeds {MAX_BYTES} bytes for {requested_url}")
    if "text/html" not in content_type.lower() and "application/xhtml+xml" not in content_type.lower():
        raise RuntimeError(f"unexpected content type {content_type!r} for {requested_url}")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def _find_exact(chunks: list[str], needle: str, start: int) -> int:
    target = _clean(needle).casefold()
    for index in range(start, len(chunks)):
        if _clean(chunks[index]).casefold() == target:
            return index
    raise RuntimeError(f"official FMO programme map missing expected marker: {needle}")


def _field(lines: list[str], labels: tuple[str, ...]) -> str | None:
    normalized_labels = [(_clean(label), _clean(label).casefold()) for label in labels]
    for index, raw_line in enumerate(lines):
        line = _clean(raw_line)
        folded = line.casefold()
        for label, folded_label in normalized_labels:
            if not folded.startswith(folded_label):
                continue
            remainder = line[len(label):].lstrip(" :–—-").strip()
            if remainder:
                return remainder
            if index + 1 < len(lines):
                candidate = _clean(lines[index + 1])
                if candidate:
                    return candidate
    return None


def _split_operator(value: str) -> tuple[str, str | None]:
    normalized = _clean(value)
    match = _FUND_OPERATOR_RE.fullmatch(normalized)
    if not match:
        return normalized.rstrip("."), None
    return _clean(match.group("programme")).rstrip("."), _clean(match.group("fund")).rstrip(".")


def parse_programme_map(raw: bytes, *, registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = registry or _load_registry()
    expected = _registry_by_name(registry)
    expected_names = [str(row["programme"]) for row in registry["programmes"]]

    parser = _VisibleTextParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    chunks = parser.chunks

    anchor = _find_exact(chunks, "Programmes 2021-2028", 0)
    positions: list[tuple[str, int]] = []
    cursor = anchor + 1
    for name in expected_names:
        position = _find_exact(chunks, name, cursor)
        positions.append((name, position))
        cursor = position + 1

    rows: list[dict[str, Any]] = []
    for index, (name, position) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(chunks)
        lines = chunks[position + 1:end]
        grant = _field(lines, ("Programme grant",))
        operator_raw = _field(lines, ("Programme Operator",))
        donor = _field(lines, ("Donor Programme Partner(s)", "Donor Programme Partners"))
        international = _field(lines, ("International Partner Organisation(s)", "International Partner Organisations"))
        if not grant or not operator_raw:
            raise RuntimeError(f"incomplete FMO programme evidence for {name}: grant/operator required")
        operator, fund_operator = _split_operator(operator_raw)
        expected_row = expected[name]
        if _clean(grant) != _clean(str(expected_row["programmeGrantEvidence"])):
            raise RuntimeError(f"programme allocation drift requires semantic reconciliation: {name}")
        if operator != _clean(str(expected_row["programmeOperator"])):
            raise RuntimeError(f"programme operator drift requires semantic reconciliation: {name}")
        expected_fund = _clean(str(expected_row.get("fundOperator") or "")) or None
        if fund_operator != expected_fund:
            raise RuntimeError(f"fund operator drift requires semantic reconciliation: {name}")
        rows.append(
            {
                "programme_id": str(expected_row["programmeId"]),
                "programme_name": name,
                "programme_grant_evidence": _clean(grant),
                "programme_operator": operator,
                "fund_operator": fund_operator,
                "donor_programme_partners": donor,
                "international_partner_organisations": international,
            }
        )

    if len(rows) != len(expected_names):
        raise RuntimeError("official FMO programme map is incomplete; fail closed")
    return rows


def normalize_programmes(
    programme_rows: list[dict[str, Any]],
    *,
    authority_url: str,
    fetched_at: str,
    raw_hash: str,
    run_id: str,
    registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    registry = registry or _load_registry()
    source = registry["source"]
    authority_url = _official_source_url(authority_url)
    raw_hash = _require_sha256(raw_hash)
    if not str(fetched_at or "").strip() or not str(run_id or "").strip():
        raise RuntimeError("fetched_at and run_id are required")
    if len(programme_rows) != len(registry["programmes"]):
        raise RuntimeError("programme batch is incomplete; fail closed")

    names = [str(row.get("programme_name") or "").strip() for row in programme_rows]
    expected_names = [str(row["programme"]) for row in registry["programmes"]]
    if names != expected_names:
        raise RuntimeError(f"programme identity/order drift: {names}")

    normalized: list[dict[str, Any]] = []
    for row in programme_rows:
        name = str(row["programme_name"]).strip()
        programme_id = str(row.get("programme_id") or "").strip()
        grant = _clean(str(row.get("programme_grant_evidence") or ""))
        operator = _clean(str(row.get("programme_operator") or ""))
        fund_operator = _clean(str(row.get("fund_operator") or "")) or None
        if not programme_id or not grant or not operator:
            raise RuntimeError(f"incomplete programme evidence for {name}")
        semantic = {
            "programme_id": programme_id,
            "programme_name": name,
            "programme_grant_evidence": grant,
            "programme_operator": operator,
            "fund_operator": fund_operator,
            "donor_programme_partners": row.get("donor_programme_partners"),
            "international_partner_organisations": row.get("international_partner_organisations"),
        }
        normalized.append(
            {
                "schema": "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_OBSERVATION_V2",
                "source_family": SOURCE_FAMILY,
                "programme_family": PROGRAMME_FAMILY,
                "authority_class": AUTHORITY_CLASS,
                "programme_id": programme_id,
                "programme_name": name,
                "programme_operator": operator,
                "operator_watch_seed": operator,
                "fund_operator": fund_operator,
                "fund_operator_watch_seed": fund_operator,
                "programme_grant_evidence": grant,
                "programme_grant_scope": "PROGRAMME_ALLOCATION_NOT_CALL_BUDGET",
                "donor_programme_partners": semantic["donor_programme_partners"],
                "international_partner_organisations": semantic["international_partner_organisations"],
                "authority_url": authority_url,
                "source_id": source["sourceId"],
                "source_published_date": source["publishedDate"],
                "fetched_at": fetched_at,
                "raw_hash": raw_hash,
                "semantic_fingerprint": _sha256(_canonical_json(semantic)),
                "parser_version": PARSER_VERSION,
                "run_id": run_id,
                "observation_state": "PROGRAMMING_PIPELINE",
                "not_a_call": True,
                "material_fact_use": False,
                "open_call_authorized": False,
                "deadline_authorized": False,
                "budget_authorized": False,
                "eligibility_authorized": False,
                "publish_authorized": False,
                "distribution_authorized": False,
                "canonical_corpus_mutation": False,
                "requires_reconciliation": True,
                "publication_effect": "NONE",
                "missing_to_confirm_call": list(MISSING_TO_CONFIRM_CALL),
            }
        )
    return normalized


def collect_live(*, run_id: str, fetched_at: str | None = None) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    registry = _load_registry()
    response = fetch_url(SOURCE_URL)
    raw = bytes(response["raw"])
    raw_hash = _sha256(raw)
    records = normalize_programmes(
        parse_programme_map(raw, registry=registry),
        authority_url=str(response["final_url"]),
        fetched_at=fetched_at,
        raw_hash=raw_hash,
        run_id=run_id,
        registry=registry,
    )
    fund_operator_watch_seeds = sum(1 for row in records if row.get("fund_operator_watch_seed"))
    return {
        "schema": "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_EVIDENCE_V2",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "source": {
            "id": registry["source"]["sourceId"],
            "url": str(response["final_url"]),
            "published_date": registry["source"]["publishedDate"],
            "http_status": int(response["status"]),
            "content_type": str(response["content_type"]),
            "raw_hash": raw_hash,
            "bytes": len(raw),
        },
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "records": records,
        "stats": {
            "programme_records": len(records),
            "operator_watch_seeds": sum(1 for row in records if row.get("operator_watch_seed")),
            "fund_operator_watch_seeds": fund_operator_watch_seeds,
            "open_calls_authorized": 0,
        },
        "observation_state": "PROGRAMMING_PIPELINE",
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "canonical_corpus_mutation": False,
        "requires_reconciliation": True,
        "publication_effect": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    payload = collect_live(run_id=args.run_id)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
