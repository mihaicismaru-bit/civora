#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ADAPTER_ID = "INS_TEMPO_MATRIX_METADATA_V1"
PARSER_VERSION = "INS_TEMPO_MATRIX_FETCH_V1"
SOURCE_ID = "SRC-INS-TEMPO-MATRIX-METADATA"
BASE_URL = "https://statistici.insse.ro/tempoins/index.jsp"
ALLOWED_HOST = "statistici.insse.ro"
ALLOWED_PATH = "/tempoins/index.jsp"
MAX_BYTES = 4 * 1024 * 1024
MATRIX_RE = re.compile(r"^[A-Z][A-Z0-9]{2,15}$")
MATRIX_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{2,15}\b")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self._in_title:
            self.title_parts.append(text)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_matrix_code(matrix_code: str) -> str:
    code = str(matrix_code or "").strip().upper()
    if not MATRIX_RE.fullmatch(code):
        raise ValueError(f"invalid TEMPO matrix code: {matrix_code!r}")
    return code


def build_matrix_url(matrix_code: str, lang: str = "ro") -> str:
    code = normalize_matrix_code(matrix_code)
    if lang not in {"ro", "en"}:
        raise ValueError("TEMPO language must be ro or en")
    return f"{BASE_URL}?{urlencode({'ind': code, 'lang': lang, 'page': 'tempo3'})}"


def validate_matrix_url(url: str, expected_matrix: str | None = None) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != ALLOWED_HOST:
        raise ValueError(f"TEMPO URL escaped official HTTPS authority: {url}")
    if parsed.path != ALLOWED_PATH:
        raise ValueError(f"TEMPO URL escaped exact matrix path: {url}")
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if qs.get("page") != ["tempo3"]:
        raise ValueError(f"TEMPO URL is not an exact matrix page: {url}")
    codes = qs.get("ind") or []
    if len(codes) != 1:
        raise ValueError(f"TEMPO URL must contain one matrix code: {url}")
    actual = normalize_matrix_code(codes[0])
    if expected_matrix and actual != normalize_matrix_code(expected_matrix):
        raise ValueError(f"TEMPO redirect changed matrix identity: {actual} != {expected_matrix}")


def fetch_bytes(url: str, timeout: float = 25.0) -> tuple[bytes, str, int, str]:
    validate_matrix_url(url)
    req = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU/INS-TEMPO-METADATA/1.0 (+official-source-verification)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    context = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=context) as response:
        final_url = response.geturl()
        validate_matrix_url(final_url, parse_qs(urlparse(url).query)["ind"][0])
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"unexpected TEMPO content type: {content_type}")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("TEMPO matrix response exceeded bounded acquisition limit")
        if status < 200 or status >= 300:
            raise ValueError(f"TEMPO matrix endpoint returned HTTP {status}")
        return payload, final_url, status, content_type


def parse_metadata(payload: bytes, matrix_code: str) -> dict:
    text = payload.decode("utf-8", errors="replace")
    parser = _TextParser()
    parser.feed(text)
    normalized = " ".join(parser.parts)
    title = " ".join(parser.title_parts).strip()
    if len(normalized) < 120:
        raise ValueError("TEMPO matrix page is low-information")
    lowered = normalized.casefold()
    if "tempo" not in lowered or not any(marker in lowered for marker in ("institutul", "institute", "statistic")):
        raise ValueError("TEMPO matrix page identity markers are missing")
    requested = normalize_matrix_code(matrix_code)
    tokens = sorted({token for token in MATRIX_TOKEN_RE.findall(normalized) if any(ch.isdigit() for ch in token)})
    related = [token for token in tokens if token != requested][:40]
    semantic_basis = json.dumps(
        {"matrix_code": requested, "title": title, "text": normalized[:12000]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "title": title,
        "normalized_text_excerpt": normalized[:2000],
        "related_matrix_codes": related,
        "semantic_sha256": sha256_bytes(semantic_basis),
    }


def build_evidence(
    payload: bytes,
    *,
    matrix_code: str,
    requested_url: str,
    final_url: str,
    status: int,
    content_type: str,
    fetched_at: str,
    run_id: str,
) -> dict:
    code = normalize_matrix_code(matrix_code)
    validate_matrix_url(requested_url, code)
    validate_matrix_url(final_url, code)
    metadata = parse_metadata(payload, code)
    return {
        "schema_version": "1.0",
        "adapter_id": ADAPTER_ID,
        "parser_version": PARSER_VERSION,
        "source_id": SOURCE_ID,
        "source_family": "ROMANIA_INS",
        "programme_family": "CROSS_PROGRAMME_MARKET_INTELLIGENCE",
        "authority_class": "T1_OFFICIAL_STATISTICAL_AUTHORITY",
        "observation_state": "MATRIX_METADATA_DISCOVERY",
        "matrix_code": code,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "raw_sha256": sha256_bytes(payload),
        **metadata,
        "material_fact_use": False,
        "statistical_value_authorized": False,
        "publish_authorized": False,
        "eligibility_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "requires_exact_query_provenance": True,
        "requires_semantic_reconcile": True,
        "missing_for_statistical_value_confirmation": [
            "exact_dimension_selection",
            "exact_period_selection",
            "exact_territory_or_universe",
            "official_value_payload_or_export",
            "semantic_reconciliation",
        ],
    }


def validate_evidence(evidence: dict) -> None:
    if evidence.get("source_id") != SOURCE_ID or evidence.get("adapter_id") != ADAPTER_ID:
        raise ValueError("INS TEMPO evidence identity drift")
    if evidence.get("observation_state") != "MATRIX_METADATA_DISCOVERY":
        raise ValueError("INS TEMPO matrix metadata escaped discovery-only state")
    for key in (
        "material_fact_use",
        "statistical_value_authorized",
        "publish_authorized",
        "eligibility_authorized",
        "deadline_authorized",
        "budget_authorized",
    ):
        if evidence.get(key) is not False:
            raise ValueError(f"INS TEMPO evidence became authorizing: {key}")
    code = normalize_matrix_code(evidence.get("matrix_code"))
    validate_matrix_url(str(evidence.get("requested_url") or ""), code)
    validate_matrix_url(str(evidence.get("final_url") or ""), code)
    for key in ("raw_sha256", "semantic_sha256"):
        value = str(evidence.get(key) or "")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"invalid {key}")
    if not evidence.get("fetched_at") or not evidence.get("run_id"):
        raise ValueError("INS TEMPO provenance incomplete")
    required = {
        "exact_dimension_selection",
        "exact_period_selection",
        "exact_territory_or_universe",
        "official_value_payload_or_export",
        "semantic_reconciliation",
    }
    if not required.issubset(set(evidence.get("missing_for_statistical_value_confirmation") or [])):
        raise ValueError("INS TEMPO statistical proof requirements incomplete")


def write_receipt(output_dir: Path, payload: bytes, evidence: dict) -> None:
    raw_dir = output_dir / "raw"
    handoff_dir = output_dir / "handoff"
    raw_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    code = evidence["matrix_code"].lower()
    (raw_dir / f"tempo_{code}.html").write_bytes(payload)
    (handoff_dir / f"tempo_{code}_metadata.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire official INS TEMPO exact-matrix metadata fail-closed")
    parser.add_argument("--matrix", default="FOM106G")
    parser.add_argument("--lang", default="ro", choices=("ro", "en"))
    parser.add_argument("--output-dir", default="/tmp/ins-tempo-matrix")
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    code = normalize_matrix_code(args.matrix)
    requested_url = build_matrix_url(code, args.lang)
    fetched_at = utc_now()
    try:
        payload, final_url, status, content_type = fetch_bytes(requested_url)
        evidence = build_evidence(
            payload,
            matrix_code=code,
            requested_url=requested_url,
            final_url=final_url,
            status=status,
            content_type=content_type,
            fetched_at=fetched_at,
            run_id=str(args.run_id),
        )
        validate_evidence(evidence)
        write_receipt(Path(args.output_dir), payload, evidence)
        print(json.dumps({
            "matrix_code": code,
            "raw_sha256": evidence["raw_sha256"],
            "semantic_sha256": evidence["semantic_sha256"],
            "related_matrix_count": len(evidence["related_matrix_codes"]),
            "observation_state": evidence["observation_state"],
            "statistical_value_authorized": evidence["statistical_value_authorized"],
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"FAIL INS TEMPO exact-matrix acquisition: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
