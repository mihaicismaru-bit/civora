#!/usr/bin/env python3
"""Build a small, corroborated cache of official MIPE pages.

The cache is an availability layer, not a new factual source. Each record keeps
the official canonical URL, the exact Jina Reader source URL, independent Google
Translate HTML evidence, both SHA-256 hashes, and the Reader body used by the
normal extraction engine. A record is emitted only when both transports succeed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "partener-eu" / "ingest" / "state" / "mipe_dual_cache.json"
UA = "PARTENER.EU-CIVORA-MIPE-DualCache/1.0 (+https://partener.eu)"
MAX_BYTES = 3_000_000
SEEDS = [
    "https://mfe.gov.ro/",
    "https://mfe.gov.ro/ghiduri_peos/",
    "https://mfe.gov.ro/ghiduri_pids/",
    "https://mfe.gov.ro/pdds/despre-program-programare/",
    "https://mfe.gov.ro/pnrr/",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch(url: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,text/plain,text/markdown,*/*;q=0.6",
        "Accept-Language": "ro,en;q=0.7",
        "Cache-Control": "no-cache",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
            data = response.read(MAX_BYTES)
            return {"ok": True, "status": getattr(response, "status", 200), "data": data, "url": response.geturl(), "contentType": response.headers.get("Content-Type", "")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "url": url}


def relay_urls(canonical: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(canonical)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query += [("_x_tr_sl", "ro"), ("_x_tr_tl", "en"), ("_x_tr_hl", "en")]
    translate = urllib.parse.urlunparse(("https", "mfe-gov-ro.translate.goog", parsed.path or "/", "", urllib.parse.urlencode(query), ""))
    return "https://r.jina.ai/" + canonical, translate


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def reader_metadata(text: str) -> tuple[str, str]:
    title = re.search(r"(?mi)^Title:\s*(.+)$", text)
    source = re.search(r"(?mi)^URL Source:\s*(.+)$", text)
    return clean(title.group(1) if title else ""), clean(source.group(1) if source else "")


def official_links(text: str) -> list[str]:
    links = set()
    for raw in re.findall(r"https?://[^\s<>()\]\"']+", text):
        url = raw.rstrip(".,;:")
        try:
            parsed = urllib.parse.urlparse(url)
            if (parsed.hostname or "").lower() in {"mfe.gov.ro", "www.mfe.gov.ro"}:
                links.add(urllib.parse.urlunparse(("https", "mfe.gov.ro", parsed.path or "/", "", parsed.query, "")))
        except Exception:
            pass
    return sorted(links)[:500]


def build_one(canonical: str) -> dict[str, Any]:
    reader_url, translate_url = relay_urls(canonical)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader_future = pool.submit(fetch, reader_url)
        translate_future = pool.submit(fetch, translate_url)
        reader = reader_future.result()
        translated = translate_future.result()

    result: dict[str, Any] = {
        "canonicalUrl": canonical,
        "readerUrl": reader_url,
        "translateUrl": translate_url,
        "ok": False,
        "readerError": reader.get("error"),
        "translateError": translated.get("error"),
    }
    if not reader.get("ok") or not translated.get("ok"):
        return result

    reader_text = reader["data"].decode("utf-8", errors="replace")
    translate_text = translated["data"].decode("utf-8", errors="replace")
    title, source = reader_metadata(reader_text)
    normalized_source = source.replace("http://", "https://").rstrip("/") + "/"
    normalized_target = canonical.rstrip("/") + "/"
    source_exact = normalized_source == normalized_target
    lower_translate = translate_text.lower()
    signatures = {
        "sourceExact": source_exact,
        "mipeHost": "mfe.gov.ro" in lower_translate,
        "ministry": "ministerul investi" in lower_translate or "ministry of investment" in lower_translate,
        "wordpress": "wp-content" in lower_translate,
        "titlePresent": bool(title),
    }
    if not source_exact or sum(bool(v) for k, v in signatures.items() if k != "sourceExact") < 3:
        result.update({"error": "corroboration_failed", "signatures": signatures, "title": title, "readerSource": source})
        return result

    result.update({
        "ok": True,
        "verification": "CANONICAL_DUAL_RELAY_CORROBORATED",
        "title": title,
        "readerSource": source,
        "readerContentType": reader.get("contentType"),
        "translateContentType": translated.get("contentType"),
        "readerSha256": hashlib.sha256(reader["data"]).hexdigest(),
        "translateSha256": hashlib.sha256(translated["data"]).hexdigest(),
        "readerBytes": len(reader["data"]),
        "translateBytes": len(translated["data"]),
        "signatures": signatures,
        "officialLinks": official_links(reader_text),
        "readerText": reader_text,
        "fetchedAt": now(),
    })
    return result


def main() -> int:
    with ThreadPoolExecutor(max_workers=len(SEEDS)) as pool:
        records = list(pool.map(build_one, SEEDS))
    payload = {
        "schema": "CIVORA_MIPE_DUAL_CACHE_V1",
        "observedAt": now(),
        "status": "OK" if all(row.get("ok") for row in records) else ("PARTIAL" if any(row.get("ok") for row in records) else "UNAVAILABLE"),
        "verifiedCount": sum(1 for row in records if row.get("ok")),
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("status", "observedAt", "verifiedCount")}, ensure_ascii=False, indent=2))
    for row in records:
        print(json.dumps({"url": row["canonicalUrl"], "ok": row.get("ok"), "title": row.get("title"), "readerBytes": row.get("readerBytes"), "translateBytes": row.get("translateBytes"), "error": row.get("error")}, ensure_ascii=False))
    return 0 if payload["verifiedCount"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
