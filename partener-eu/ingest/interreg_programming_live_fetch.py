#!/usr/bin/env python3
"""Fail-closed live acquisition for official Interreg programming intelligence.

Reads only Interreg programming/future-programming sources from the canonical source
registry, captures exact official HTML bytes, hashes them, extracts visible text, and
delegates classification to INTERREG_PROGRAMMING_INTELLIGENCE_V1.

This acquisition path is non-authorizing by construction. It never creates OPEN_CALL,
never mutates the canonical opportunity corpus, and never authorizes material call
facts or publication.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import urllib.request
from typing import Any

from interreg_programming_intelligence import normalize_programming_observation

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "source_registry.json"
SCHEMA = "PARTENER_EU_INTERREG_PROGRAMMING_LIVE_EVIDENCE_V1"
USER_AGENT = "PARTENER.EU-Interreg-Programming/1.0"
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 25
PROGRAMMING_EXTRACT_KEYS = {"future_programming_consultations", "future_programming_updates"}


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            clean = re.sub(r"\s+", " ", data).strip()
            if clean:
                self.parts.append(clean)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _visible_text(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    decoded = raw.decode(charset, errors="replace")
    parser = _VisibleText()
    parser.feed(decoded)
    return html.unescape(" ".join(parser.parts))


def _load_registry(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("sources"), list):
        raise ValueError("source registry missing sources[]")
    return data


def _programming_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for source in registry.get("sources", []):
        families = {str(x) for x in source.get("source_families", [])}
        extract = {str(x) for x in source.get("extract", [])}
        if "INTERREG" not in families:
            continue
        if "PROGRAMMING_PIPELINE" not in families and not (extract & PROGRAMMING_EXTRACT_KEYS):
            continue
        selected.append(source)
    if not selected:
        raise ValueError("no Interreg programming sources registered")
    return sorted(selected, key=lambda item: str(item.get("id") or ""))


def _fetch(url: str) -> tuple[bytes, str, int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context) as response:
        final_url = response.geturl()
        status = int(response.getcode() or 0)
        content_type = str(response.headers.get("Content-Type") or "")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"response exceeds {MAX_BYTES} bytes")
    if status != 200:
        raise ValueError(f"unexpected HTTP status {status}")
    if "html" not in content_type.lower():
        raise ValueError(f"unexpected content type {content_type!r}")
    return raw, final_url, status, content_type


def build_live_evidence(registry_path: Path = REGISTRY_PATH, *, run_id: str | None = None) -> dict[str, Any]:
    registry = _load_registry(registry_path)
    sources = _programming_sources(registry)
    observed_at = _utc_now()
    run = run_id or f"INTERREG-PROGRAMMING-{observed_at.replace(':', '').replace('-', '')}"
    rows: list[dict[str, Any]] = []
    errors = 0

    for source in sources:
        source_id = str(source.get("id") or "")
        url = str(source.get("url") or "")
        programme = str((source.get("programmes") or [""])[0] or "")
        row: dict[str, Any] = {
            "source_id": source_id,
            "registered_url": url,
            "programme": programme,
            "fetched_at": observed_at,
            "run_id": run,
            "publication_effect": "NONE",
            "publish_authorized": False,
            "material_fact_use": False,
        }
        try:
            raw, final_url, status, content_type = _fetch(url)
            text = _visible_text(raw, content_type)
            if len(text) < 120:
                raise ValueError("low-information HTML body")
            raw_hash = _sha256(raw)
            normalized = normalize_programming_observation(
                {
                    "programme": programme,
                    "title": source.get("owner"),
                    "text": text,
                    "authority_url": final_url,
                },
                fetched_at=observed_at,
                raw_hash=raw_hash,
                run_id=run,
            )
            row.update(
                {
                    "fetch_status": "PASS",
                    "http_status": status,
                    "content_type": content_type,
                    "final_url": final_url,
                    "bytes": len(raw),
                    "raw_hash": raw_hash,
                    "normalized": normalized,
                }
            )
        except Exception as exc:
            errors += 1
            row.update(
                {
                    "fetch_status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        rows.append(row)

    states: dict[str, int] = {}
    for row in rows:
        normalized = row.get("normalized") or {}
        state = str(normalized.get("observation_state") or "FETCH_FAILED")
        states[state] = states.get(state, 0) + 1

    return {
        "schema": SCHEMA,
        "created_at": observed_at,
        "run_id": run,
        "source_count": len(rows),
        "fetch_pass": len(rows) - errors,
        "fetch_fail": errors,
        "observation_states": states,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "rows": rows,
    }


def validate_envelope(data: dict[str, Any]) -> None:
    if data.get("schema") != SCHEMA:
        raise ValueError("unexpected live-evidence schema")
    if data.get("publication_effect") != "NONE":
        raise ValueError("live programming evidence must have publication_effect=NONE")
    if data.get("canonical_corpus_mutation") is not False:
        raise ValueError("live programming evidence cannot mutate canonical corpus")
    if data.get("publish_authorized") is not False:
        raise ValueError("live programming evidence cannot authorize publish")
    for row in data.get("rows", []):
        if row.get("publish_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError(f"unsafe source row {row.get('source_id')}")
        normalized = row.get("normalized")
        if not normalized:
            continue
        if normalized.get("not_a_call") is not True:
            raise ValueError(f"programming row became call: {row.get('source_id')}")
        if normalized.get("open_call_authorized") is not False:
            raise ValueError(f"programming row authorized OPEN: {row.get('source_id')}")
        if normalized.get("observation_state") == "OPEN_CALL":
            raise ValueError(f"programming row classified OPEN_CALL: {row.get('source_id')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()

    evidence = build_live_evidence(args.registry, run_id=args.run_id)
    validate_envelope(evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "source_count": evidence["source_count"],
                "fetch_pass": evidence["fetch_pass"],
                "fetch_fail": evidence["fetch_fail"],
                "observation_states": evidence["observation_states"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
