#!/usr/bin/env python3
"""Monitor VÂLCEA CLAR sources without auto-publishing material facts.

The probe records reachability, semantic hashes and discoverable public signals.
A changed source can only open a resolution task; it never updates venue facts.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "sources.json"
STATE = ROOT / "state" / "source_health.json"
TASK_DIR = ROOT / "ops" / "resolution_tasks"
UA = "Mozilla/5.0 CIVORA-VALCEA-CLAR/0.2 (+source-monitoring)"
MAX_BYTES = 5_000_000
MATERIAL_SUPPORTS = {
    "address",
    "phone",
    "email",
    "opening_hours",
    "delivery_hours",
    "operator",
    "cui",
    "registration_number",
    "brand_owner",
    "opening_date",
    "investment",
    "menu_item",
    "menu_items",
    "price",
    "products",
    "restaurant_existence",
}
SOCIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def semantic_bytes(raw: bytes, content_type: str) -> bytes:
    if "html" not in (content_type or "").lower():
        return raw
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    # Ignore common volatile fragments while retaining substantive editorial data.
    text = re.sub(
        r"\b(?:[0-2]?\d:[0-5]\d(?::[0-5]\d)?|\d+\s+(?:seconds?|minutes?|hours?)\s+ago)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text.encode("utf-8")


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.I | re.S)
    return html.unescape(match.group(1)).strip() if match else None


def extract_signals(raw: bytes, content_type: str, final_url: str) -> dict:
    if "html" not in (content_type or "").lower():
        return {
            "title": None,
            "canonical_url": None,
            "jsonld_blocks": 0,
            "social_links": [],
            "menu_links": [],
            "robots_noindex": False,
        }

    text = raw.decode("utf-8", errors="ignore")
    title = _first(r"<title\b[^>]*>(.*?)</title>", text)
    canonical = _first(
        r"<link\b(?=[^>]*\brel\s*=\s*['\"]canonical['\"])(?=[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"])[^>]*>",
        text,
    )
    if canonical:
        canonical = urljoin(final_url, canonical)

    hrefs = re.findall(r"\bhref\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.I)
    social_links: set[str] = set()
    menu_links: set[str] = set()
    for href in hrefs:
        absolute = urljoin(final_url, html.unescape(href).strip())
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if any(host == social or host.endswith("." + social) for social in SOCIAL_HOSTS):
            social_links.add(absolute)
        searchable = f"{parsed.path} {parsed.query}".lower()
        if re.search(r"(?:^|[/_\-])(meniu|menu)(?:[/_\-.]|$)", searchable):
            menu_links.add(absolute)

    robots = _first(r"<meta\b(?=[^>]*\bname\s*=\s*['\"]robots['\"])(?=[^>]*\bcontent\s*=\s*['\"]([^'\"]+)['\"])[^>]*>", text)
    return {
        "title": title,
        "canonical_url": canonical,
        "jsonld_blocks": len(re.findall(r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"]", text, flags=re.I)),
        "social_links": sorted(social_links)[:20],
        "menu_links": sorted(menu_links)[:20],
        "robots_noindex": bool(robots and "noindex" in robots.lower()),
    }


def fetch_once(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json,application/pdf,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
            "Connection": "close",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=22, context=context) as response:
        raw = response.read(MAX_BYTES)
        content_type = response.headers.get("content-type") or ""
        final_url = response.geturl()
        semantic = semantic_bytes(raw, content_type)
        return {
            "ok": 200 <= response.status < 400,
            "http_status": response.status,
            "final_url": final_url,
            "content_type": content_type,
            "bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "semantic_sha256": hashlib.sha256(semantic).hexdigest(),
            "semantic_bytes": len(semantic),
            "signals": extract_signals(raw, content_type, final_url),
        }


def fetch(url: str, attempts: int = 2) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = fetch_once(url)
            result["attempts"] = attempt
            return result
        except Exception as exc:  # network failures are persisted, not hidden
            last_error = exc
            if attempt < attempts:
                time.sleep(1.25 * attempt)
    assert last_error is not None
    raise last_error


def is_material(source: dict) -> bool:
    return bool(MATERIAL_SUPPORTS.intersection(source.get("supports", [])))


def write_resolution_task(source: dict, old_hash: str, new_hash: str, observed_at: str) -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    path = TASK_DIR / f"{source['id']}.json"
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    task = {
        "schema_version": "1.0",
        "type": "VENUE_SOURCE_CHANGE_REVIEW",
        "source_id": source["id"],
        "source_url": source["url"],
        "source_kind": source["kind"],
        "status": "OPEN",
        "first_observed_at": existing.get("first_observed_at") or observed_at,
        "last_observed_at": observed_at,
        "previous_semantic_sha256": old_hash,
        "current_semantic_sha256": new_hash,
        "potentially_impacted_fields": source.get("supports", []),
        "material_fact_autoupdate_allowed": False,
        "required_resolution": (
            "Reverify the changed address, hours, menu, prices, operator or other supported facts "
            "against the source before rebuilding the public projection."
        ),
    }
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_probe() -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    previous: dict[str, dict] = {}
    if STATE.exists():
        try:
            old = json.loads(STATE.read_text(encoding="utf-8"))
            previous = {row["id"]: row for row in old.get("sources", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            previous = {}

    observed_at = utc_now()
    output = {
        "schema_version": "1.0",
        "observed_at": observed_at,
        "policy": "monitor-and-open-review-task-never-autopublish-material-facts",
        "sources": [],
    }

    for source in registry.get("sources", []):
        if source.get("status") not in {"active", "candidate_only"}:
            continue
        old = previous.get(source["id"], {})
        row = {
            "id": source["id"],
            "kind": source["kind"],
            "registry_status": source["status"],
            "url": source["url"],
            "supports": source.get("supports", []),
            "material_fact_use": is_material(source),
        }
        try:
            row.update(fetch(source["url"]))
            old_hash = old.get("semantic_sha256")
            new_hash = row.get("semantic_sha256")
            changed = bool(old_hash and new_hash and old_hash != new_hash)
            needs_review = bool(changed and row["material_fact_use"] and source.get("status") == "active")
            row.update(
                {
                    "semantic_hash_changed": changed,
                    "resolution_task_required": needs_review,
                    "publish_material_fact_update": False if changed else None,
                    "consecutive_failures": 0,
                    "health": "PASS" if row.get("ok") else "FAIL",
                    "quarantined": False,
                }
            )
            if needs_review:
                write_resolution_task(source, old_hash, new_hash, observed_at)
        except Exception as exc:
            failures = int(old.get("consecutive_failures") or 0) + 1
            row.update(
                {
                    "ok": False,
                    "health": "DEGRADED" if failures < 3 else "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                    "semantic_hash_changed": False,
                    "resolution_task_required": False,
                    "publish_material_fact_update": False,
                    "consecutive_failures": failures,
                    "last_known_semantic_sha256": old.get("semantic_sha256") or old.get("last_known_semantic_sha256"),
                    "quarantined": failures >= 3,
                }
            )
        output["sources"].append(row)
        time.sleep(0.35)

    rows = output["sources"]
    output["summary"] = {
        "total": len(rows),
        "pass": sum(1 for row in rows if row.get("health") == "PASS"),
        "degraded": sum(1 for row in rows if row.get("health") == "DEGRADED"),
        "fail": sum(1 for row in rows if row.get("health") == "FAIL"),
        "changed": sum(1 for row in rows if row.get("semantic_hash_changed")),
        "quarantined": sum(1 for row in rows if row.get("quarantined")),
        "resolution_tasks_required": sum(1 for row in rows if row.get("resolution_task_required")),
        "sources_with_social_links": sum(1 for row in rows if row.get("signals", {}).get("social_links")),
        "sources_with_menu_links": sum(1 for row in rows if row.get("signals", {}).get("menu_links")),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def self_test() -> None:
    sample = b'''<!doctype html><html><head><title>Local &amp; Meniu</title>
      <link rel="canonical" href="/restaurant/">
      <meta name="robots" content="index,follow">
      <script type="application/ld+json">{"@type":"Restaurant"}</script></head>
      <body><a href="/meniu/">Meniu</a><a href="https://instagram.com/local.test">Instagram</a>
      <p>Deschis azi la 12:30</p></body></html>'''
    signals = extract_signals(sample, "text/html; charset=utf-8", "https://example.test/home")
    assert signals["title"] == "Local & Meniu"
    assert signals["canonical_url"] == "https://example.test/restaurant/"
    assert signals["jsonld_blocks"] == 1
    assert signals["menu_links"] == ["https://example.test/meniu/"]
    assert signals["social_links"] == ["https://instagram.com/local.test"]
    first = semantic_bytes(sample, "text/html")
    second = semantic_bytes(sample.replace(b"12:30", b"13:45"), "text/html")
    assert first == second, "volatile time fragments must not change the semantic hash"
    print("Source radar self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    output = run_probe()
    print(json.dumps(output["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
