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
from urllib.parse import urlsplit
from typing import Any

from interreg_programming_intelligence import OFFICIAL_HOSTS, normalize_programming_observation

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "source_registry.json"
SCHEMA = "PARTENER_EU_INTERREG_PROGRAMMING_LIVE_EVIDENCE_V1"
# Closed provenance schema: forged convenience fields cannot grant publication
# authority just because a downstream reader trusts an evidence manifest.
ENVELOPE_KEYS = frozenset({
    "schema", "created_at", "run_id", "source_count", "fetch_pass",
    "fetch_fail", "observation_states", "publication_effect",
    "canonical_corpus_mutation", "publish_authorized", "rows",
})
ROW_COMMON_KEYS = frozenset({
    "source_id", "source_owner", "registered_url", "programme",
    "fetched_at", "run_id", "publication_effect", "publish_authorized",
    "material_fact_use", "fetch_status",
})
ROW_PASS_KEYS = ROW_COMMON_KEYS | {
    "raw_evidence_file", "http_status", "content_type", "final_url",
    "bytes", "raw_hash", "normalized",
}
ROW_FAIL_KEYS = ROW_COMMON_KEYS | {"error_type", "error"}
WORKSHOPS_SOURCE_ID = "SRC-INTERREG-ROHU-2028-2034-WORKSHOPS-NOV2026"
WORKSHOPS_IDENTITY_TERMS = ("2028-2034", "17 noiembrie 2026", "20 noiembrie 2026", "28 octombrie 2026")
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


def _load_strict_json(raw: str) -> Any:
    """Reject duplicate keys before JSON decoding silently keeps the last."""
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate Interreg JSON key: {key}")
            obj[key] = value
        return obj

    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"non-finite Interreg JSON number: {token}")

    return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_nonfinite)


def _load_registry(path: Path) -> dict[str, Any]:
    data = _load_strict_json(path.read_text(encoding="utf-8"))
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



def _assert_official_source_origin(requested_url: str, final_url: str) -> None:
    """Fail closed if an official Interreg source redirects to another authority.

    A www/non-www canonical redirect is acceptable; a redirect to a different
    official Interreg programme is NOT equivalent provenance for this source.
    """
    requested = urlsplit(requested_url)
    final = urlsplit(final_url)
    for part in (requested, final):
        host = (part.hostname or "").lower()
        if (
            part.scheme != "https"
            or host not in OFFICIAL_HOSTS
            or part.username is not None
            or part.password is not None
            or part.port not in (None, 443)
        ):
            raise ValueError("untrusted Interreg source/redirect URL")
    requested_host = (requested.hostname or "").lower().removeprefix("www.")
    final_host = (final.hostname or "").lower().removeprefix("www.")
    if requested_host != final_host:
        raise ValueError("Interreg redirect crossed registered official source origin")



def _assert_registered_article_identity(source_id: str, registered_url: str, final_url: str, visible_text: str) -> None:
    """Prevent a 200 HTML fallback/homepage from impersonating the ROHU workshop article.

    Event and registration dates establish source identity only, never a call
    deadline or eligibility. This check applies during acquisition AND replay.
    """
    if source_id != WORKSHOPS_SOURCE_ID:
        return
    registered = urlsplit(registered_url)
    resolved = urlsplit(final_url)
    if registered.path.rstrip("/") != resolved.path.rstrip("/") or resolved.query:
        raise ValueError("ROHU workshop exact official article endpoint changed")
    comparable = re.sub(r"\s+", " ", visible_text.casefold()).translate(
        str.maketrans({"–": "-", "—": "-", "−": "-"})
    )
    if "atelier" not in comparable or any(term not in comparable for term in WORKSHOPS_IDENTITY_TERMS):
        raise ValueError("ROHU workshop official article identity/schedule unverified")


class _RegisteredOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Reject every untrusted redirect hop *before* following it.

    Checking just response.geturl() can miss an off-authority intermediate hop
    which ultimately returns to the registered hostname. The acquisition path
    must not contact that intermediate host, even for non-publishing evidence.
    """

    def __init__(self, registered_url: str) -> None:
        super().__init__()
        self.registered_url = registered_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_official_source_origin(self.registered_url, req.full_url)
        _assert_official_source_origin(self.registered_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str) -> tuple[bytes, str, int, str]:
    # Disallow untrusted initial endpoints as well as redirect hops.
    _assert_official_source_origin(url, url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        },
    )
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _RegisteredOriginRedirect(url),
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        status = int(response.getcode() or 0)
        content_type = str(response.headers.get("Content-Type") or "")
        # An HTTP 200 does not prove complete, uncompressed HTML evidence.
        # Refuse encoded bodies and truncated originals before hashing.
        content_encoding = str(response.headers.get("Content-Encoding") or "identity").strip().lower()
        if content_encoding != "identity":
            raise ValueError("unsupported encoded Interreg HTML body")
        declared_length = response.headers.get("Content-Length")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"response exceeds {MAX_BYTES} bytes")
    if declared_length is not None:
        declared = str(declared_length).strip()
        if not declared.isdecimal() or int(declared) != len(raw):
            raise ValueError("Interreg raw response differs from declared Content-Length")
    if status != 200:
        raise ValueError(f"unexpected HTTP status {status}")
    if "html" not in content_type.lower():
        raise ValueError(f"unexpected content type {content_type!r}")
    return raw, final_url, status, content_type


def build_live_evidence(registry_path: Path = REGISTRY_PATH, *, run_id: str | None = None, raw_dir: Path | None = None) -> dict[str, Any]:
    registry = _load_registry(registry_path)
    sources = _programming_sources(registry)
    if raw_dir is not None:
        if raw_dir.exists():
            raise ValueError('Interreg immutable raw evidence directory already exists')
        raw_dir.mkdir(parents=True, exist_ok=False)
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
            "source_owner": source.get("owner"),
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
            _assert_official_source_origin(url, final_url)
            text = _visible_text(raw, content_type)
            if len(text) < 120:
                raise ValueError("low-information HTML body")
            _assert_registered_article_identity(source_id, url, final_url, text)
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
            if raw_dir is not None:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', source_id):
                    raise ValueError('unsafe Interreg source_id for immutable original')
                raw_name = f'{source_id}.raw.html'
                with (raw_dir / raw_name).open('xb') as handle:
                    handle.write(raw)
                row['raw_evidence_file'] = raw_name
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
    if not isinstance(data, dict) or set(data) != ENVELOPE_KEYS:
        raise ValueError("unexpected Interreg evidence envelope keys")
    if not isinstance(data.get("rows"), list):
        raise ValueError("Interreg evidence rows must be a list")
    if data.get("schema") != SCHEMA:
        raise ValueError("unexpected live-evidence schema")
    if data.get("publication_effect") != "NONE":
        raise ValueError("live programming evidence must have publication_effect=NONE")
    if data.get("canonical_corpus_mutation") is not False:
        raise ValueError("live programming evidence cannot mutate canonical corpus")
    if data.get("publish_authorized") is not False:
        raise ValueError("live programming evidence cannot authorize publish")
    for row in data["rows"]:
        if not isinstance(row, dict):
            raise ValueError("invalid Interreg source row")
        allowed = ROW_PASS_KEYS if row.get("fetch_status") == "PASS" else ROW_FAIL_KEYS
        if set(row) != allowed:
            raise ValueError(f"unexpected Interreg source row keys: {row.get('source_id')}")
        if row.get("publication_effect") != "NONE":
            raise ValueError(f"Interreg source row attempted publication: {row.get('source_id')}")
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



def replay_live_evidence(
    evidence: dict[str, Any],
    raw_dir: Path,
    registry_path: Path = REGISTRY_PATH,
) -> int:
    """Re-parse original bytes under the exact registered authority; no publication."""
    validate_envelope(evidence)
    rows = evidence.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid Interreg evidence rows")
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ValueError("immutable Interreg raw evidence directory missing or symlinked")
    registered = {
        str(source.get("id")): source
        for source in _programming_sources(_load_registry(registry_path))
    }
    expected_files: set[str] = set()
    seen_ids: set[str] = set()
    observed_states: dict[str, int] = {}
    pass_count = 0
    if not str(evidence.get("run_id") or "").strip():
        raise ValueError("Interreg raw evidence missing run_id")
    for row in rows:
        source_id = str(row.get("source_id") or "")
        if source_id in seen_ids or source_id not in registered:
            raise ValueError("duplicate or unregistered Interreg evidence source")
        seen_ids.add(source_id)
        source = registered[source_id]
        if (
            row.get("registered_url") != source.get("url")
            or row.get("programme") != str((source.get("programmes") or [""])[0] or "")
            or row.get("source_owner") != source.get("owner")
            or row.get("fetched_at") != evidence.get("created_at")
            or row.get("run_id") != evidence.get("run_id")
        ):
            raise ValueError("Interreg source registry/run provenance mismatch")
        if row.get("fetch_status") == "FAIL":
            if (row.get("normalized") or row.get("raw_evidence_file")
                    or any(key in row for key in ("raw_hash", "bytes", "http_status", "content_type", "final_url"))):
                raise ValueError("failed Interreg source cannot have promoted original")
            if not row.get("error_type") or not row.get("error"):
                raise ValueError("failed Interreg source missing explicit error receipt")
            observed_states["FETCH_FAILED"] = observed_states.get("FETCH_FAILED", 0) + 1
            continue
        if row.get("fetch_status") != "PASS":
            raise ValueError("invalid Interreg raw acquisition status")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_id):
            raise ValueError("unsafe Interreg source_id")
        raw_name = f"{source_id}.raw.html"
        if row.get("raw_evidence_file") != raw_name:
            raise ValueError("untrusted Interreg raw evidence path")
        original = raw_dir / raw_name
        if not original.is_file() or original.is_symlink():
            raise ValueError("missing original Interreg bytes")
        _assert_official_source_origin(str(source.get('url') or ''), str(row.get('final_url') or ''))
        raw = original.read_bytes()
        if (
            not raw or len(raw) > MAX_BYTES
            or row.get("bytes") != len(raw)
            or row.get("raw_hash") != _sha256(raw)
            or row.get("http_status") != 200
            or "html" not in str(row.get("content_type") or "").lower()
        ):
            raise ValueError("Interreg raw bytes, type, status or SHA mismatch")
        replay_text = _visible_text(raw, row["content_type"])
        _assert_registered_article_identity(source_id, str(source.get("url") or ""), str(row.get("final_url") or ""), replay_text)
        normalized = normalize_programming_observation(
            {
                "programme": row["programme"],
                "title": row["source_owner"],
                "text": replay_text,
                "authority_url": row.get("final_url"),
            },
            fetched_at=row["fetched_at"],
            raw_hash=row["raw_hash"],
            run_id=row["run_id"],
        )
        if normalized != row.get("normalized"):
            raise ValueError("Interreg raw-to-semantic replay disagreement")
        pass_count += 1
        state = normalized["observation_state"]
        observed_states[state] = observed_states.get(state, 0) + 1
        expected_files.add(raw_name)
    if {p.name for p in raw_dir.iterdir()} != expected_files:
        raise ValueError("unknown, partial or orphaned Interreg raw evidence file")
    if len(seen_ids) != len(registered):
        raise ValueError("incomplete Interreg programming source set")
    if (type(evidence.get("source_count")) is not int
            or type(evidence.get("fetch_pass")) is not int
            or type(evidence.get("fetch_fail")) is not int
            or evidence["source_count"] != len(rows)
            or evidence["fetch_pass"] != pass_count
            or evidence["fetch_fail"] != len(rows) - pass_count
            or evidence.get("observation_states") != observed_states):
        raise ValueError("Interreg replay summary differs from verified source rows")
    return len(expected_files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--replay-dir", type=Path)
    args = parser.parse_args()

    if args.replay_dir is not None:
        evidence = _load_strict_json(args.out.read_text(encoding="utf-8"))
        count = replay_live_evidence(evidence, args.replay_dir, args.registry)
        print(json.dumps({"verified": True, "raw_source_count": count, "run_id": evidence["run_id"], "publish_authorized": False}))
        return 0

    raw_dir = args.raw_dir or Path(str(args.out) + ".originals")
    if args.out.exists():
        raise ValueError("Interreg immutable evidence manifest already exists")
    evidence = build_live_evidence(args.registry, run_id=args.run_id, raw_dir=raw_dir)
    validate_envelope(evidence)
    replay_live_evidence(evidence, raw_dir, args.registry)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
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
