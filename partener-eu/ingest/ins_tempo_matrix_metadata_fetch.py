#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SOURCE_ID = "SRC-INS-TEMPO-MATRIX-METADATA"
SOURCE_FAMILY = "ROMANIA_INS"
PROGRAMME_FAMILY = "STATISTICAL_INTELLIGENCE"
AUTHORITY_CLASS = "T1_OFFICIAL_STATISTICAL_DATABASE"
OBSERVATION_STATE = "MATRIX_METADATA_DISCOVERY"
ADAPTER_ID = "INS_TEMPO_MATRIX_METADATA_V1"
PARSER_VERSION = "INS_TEMPO_MATRIX_METADATA_FETCH_V1"
DEFAULT_MATRIX_CODE = "FOM106D"
DEFAULT_URL = "https://statistici.insse.ro/tempoins/index.jsp?ind=FOM106D&lang=ro&page=tempo3"
ALLOWED_HOSTS = {"statistici.insse.ro"}
ALLOWED_PATH_PREFIXES = ("/tempoins/",)
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "CIVORA-PARTENER-EU/1.0 (+https://civora.ro)"
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_authority_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("INS TEMPO acquisition requires HTTPS")
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError(f"unexpected INS TEMPO host: {parsed.hostname!r}")
    path = parsed.path or "/"
    if not any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        raise ValueError(f"unexpected INS TEMPO path: {path!r}")


def matrix_code_from_url(url: str) -> str | None:
    validate_authority_url(url)
    values = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("ind") or []
    if not values:
        return None
    value = normalize_space(values[0]).upper()
    return value if re.fullmatch(r"[A-Z0-9._-]{2,40}", value) else None


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        validate_authority_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


class VisibleTextParser(HTMLParser):
    HIDDEN = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in self.HIDDEN:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.HIDDEN and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            text = normalize_space(data)
            if text:
                self.parts.append(text)


def decode_html(raw: bytes) -> str:
    for encoding in ("utf-8", "iso-8859-2", "windows-1250"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def visible_text(raw: bytes) -> str:
    parser = VisibleTextParser()
    parser.feed(decode_html(raw))
    return normalize_space(html.unescape(" ".join(parser.parts)))


def _match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE)
        if found:
            return normalize_space(found.group(1))
    return None


def extract_matrix_metadata(raw: bytes, authority_url: str) -> dict:
    code = matrix_code_from_url(authority_url)
    text = visible_text(raw)
    if not code:
        raise ValueError("exact matrix metadata URL must carry an ind= matrix code")
    if code.lower() not in text.lower():
        raise ValueError(f"INS TEMPO response does not identify requested matrix {code}")

    title = _match(
        text,
        [
            rf"\b{re.escape(code)}\b\s*[-–:]\s*(.+?)(?=\s+(?:Periodicitate|Periodicit|Sursa datelor|Ultima actualizare|Definitie|Observatii)\b)",
            rf"\b{re.escape(code)}\b\s+(.+?)(?=\s+(?:Periodicitate|Periodicit|Sursa datelor|Ultima actualizare|Definitie|Observatii)\b)",
        ],
    )
    periodicity = _match(text, [r"Periodicitate\s*:?\s*([^.;]{2,80})", r"Periodicitatea\s*:?\s*([^.;]{2,80})"])
    data_source = _match(text, [r"Sursa datelor\s*:?\s*(.+?)(?=\s+(?:Periodicitate|Ultima actualizare|Definitie|Observatii|Ultima perioada)\b)"])
    last_period = _match(text, [r"Ultima perioada din aceasta serie\s*:?\s*([^.;]{2,100})"])
    continuation = _match(text, [r"(?:seria\s+se\s+continua\s+cu\s+matricea|se\s+continua\s+cu\s+matricea)\s+([A-Z0-9._-]{2,40})"])

    return {
        "matrix_code": code,
        "matrix_title": title,
        "periodicity": periodicity,
        "data_source_note": data_source,
        "last_period_note": last_period,
        "continuation_matrix_code": continuation.upper() if continuation else None,
        "metadata_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def fetch_raw(url: str = DEFAULT_URL) -> tuple[bytes, str, int, str]:
    validate_authority_url(url)
    if not matrix_code_from_url(url):
        raise ValueError("INS TEMPO metadata acquisition requires an exact ind= matrix code")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        StrictRedirectHandler(),
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            validate_authority_url(final_url)
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get_content_type().lower()
            if status != 200:
                raise RuntimeError(f"unexpected HTTP status {status}")
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise RuntimeError(f"unexpected content type {content_type!r}")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise RuntimeError("INS TEMPO response exceeded bounded acquisition limit")
            return data, final_url, status, content_type
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while acquiring INS TEMPO matrix metadata") from exc


def build_evidence(
    raw: bytes,
    *,
    requested_url: str,
    final_url: str,
    status: int,
    content_type: str,
    fetched_at: str,
    run_id: str,
) -> dict:
    validate_authority_url(requested_url)
    validate_authority_url(final_url)
    requested_code = matrix_code_from_url(requested_url)
    final_code = matrix_code_from_url(final_url)
    if not requested_code or not final_code or requested_code != final_code:
        raise ValueError("INS TEMPO redirect changed or removed the exact matrix identifier")
    metadata = extract_matrix_metadata(raw, final_url)
    return {
        "schema_version": "1.0",
        "adapter_id": ADAPTER_ID,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "source_id": SOURCE_ID,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw),
        **metadata,
        "material_fact_use": False,
        "statistical_value_authorized": False,
        "publish_authorized": False,
        "requires_exact_matrix_query": True,
        "requires_semantic_reconcile": True,
        "missing_for_statistical_value_confirmation": [
            "exact_matrix_code",
            "exact_dimension_and_value_selections",
            "exact_period",
            "exact_territory_or_universe",
            "official_query_or_export_response",
            "semantic_reconciliation",
        ],
    }


def validate_evidence(evidence: dict) -> None:
    if evidence.get("source_id") != SOURCE_ID:
        raise ValueError("unexpected source_id")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("unexpected authority class")
    if evidence.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("INS TEMPO matrix metadata must remain discovery-only")
    for key in ("material_fact_use", "statistical_value_authorized", "publish_authorized"):
        if evidence.get(key) is not False:
            raise ValueError(f"{key} must remain false for matrix metadata evidence")
    if evidence.get("requires_exact_matrix_query") is not True or evidence.get("requires_semantic_reconcile") is not True:
        raise ValueError("exact matrix query evidence and semantic reconcile are mandatory")
    validate_authority_url(str(evidence.get("requested_url", "")))
    validate_authority_url(str(evidence.get("final_url", "")))
    code = str(evidence.get("matrix_code") or "")
    if not re.fullmatch(r"[A-Z0-9._-]{2,40}", code):
        raise ValueError("invalid or missing matrix code")
    if matrix_code_from_url(str(evidence.get("requested_url"))) != code:
        raise ValueError("matrix code does not match requested URL")
    raw_hash = str(evidence.get("raw_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("invalid raw SHA-256")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded acquisition-only adapter for official INS TEMPO matrix metadata")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", default="partener-eu/ingest/evidence/ins-tempo-matrix-metadata")
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    raw, final_url, status, content_type = fetch_raw(args.url)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    evidence = build_evidence(
        raw,
        requested_url=args.url,
        final_url=final_url,
        status=status,
        content_type=content_type,
        fetched_at=fetched_at,
        run_id=args.run_id,
    )
    validate_evidence(evidence)

    out = Path(args.output_dir)
    raw_dir = out / "raw"
    handoff_dir = out / "handoff"
    raw_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{evidence['matrix_code'].lower()}.html"
    evidence_path = handoff_dir / f"{evidence['matrix_code'].lower()}_metadata.json"
    raw_path.write_bytes(raw)
    evidence["raw_path"] = raw_path.as_posix()
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "source_id": SOURCE_ID,
                "matrix_code": evidence["matrix_code"],
                "continuation_matrix_code": evidence.get("continuation_matrix_code"),
                "raw_sha256": evidence["raw_sha256"],
                "statistical_value_authorized": False,
                "evidence_path": evidence_path.as_posix(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
