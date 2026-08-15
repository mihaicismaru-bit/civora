#!/usr/bin/env python3
"""Apply idempotent runtime bounds, legacy normalization and feed cache-busting."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "import urllib.request\nimport xml.etree.ElementTree as ET\nfrom html.parser import HTMLParser",
        "import urllib.request\nimport xml.etree.ElementTree as ET\nfrom concurrent.futures import ThreadPoolExecutor\nfrom html.parser import HTMLParser",
        "bounded concurrency import",
    ),
    (
        'REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_source_registry.json"',
        'REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_source_registry.json"\nINDEX_PATH = ROOT / "partener-eu" / "web" / "index.html"',
        "index cache-bust path",
    ),
    ("MAX_CANDIDATES = 90", "MAX_CANDIDATES = 32", "candidate bound"),
    ("MAX_SEARCH_RESULTS = 35", "MAX_SEARCH_RESULTS = 24", "search result bound"),
    ("direct = fetch(canonical, timeout=18, attempts=1)", "direct = fetch(canonical, timeout=6, attempts=1)", "direct timeout"),
    ('proxy = fetch(reader_url(canonical), timeout=35, attempts=2, accept="text/plain,text/markdown,*/*")', 'proxy = fetch(reader_url(canonical), timeout=18, attempts=1, accept="text/plain,text/markdown,*/*")', "reader timeout"),
    ('result = fetch(search_url(query), timeout=35, attempts=1, accept="text/plain,text/markdown,*/*")', 'result = fetch(search_url(query), timeout=18, attempts=1, accept="text/plain,text/markdown,*/*")', "search timeout"),
    (
        '    previous_by_url = {item.get("url"): item for item in previous_state.get("items", []) if item.get("url")}\n',
        '''    previous_by_url: dict[str, dict[str, Any]] = {}\n    for old_item in previous_state.get("items", []):\n        old_url = old_item.get("url")\n        if not old_url:\n            continue\n        normalized = dict(old_item)\n        # Items created by pre-v2 ingestion are preserved, but they must still\n        # satisfy the current provenance contract. The marker is explicit and\n        # never pretends that an old item was fetched in the current run.\n        normalized.setdefault("retrievalTransport", "legacy-preserved")\n        normalized.setdefault("tier", "T1_LEGACY_PRESERVED")\n        normalized.setdefault("observedAt", previous_state.get("lastRun", {}).get("observedAt", ""))\n        normalized.setdefault("documents", [])\n        previous_by_url[old_url] = normalized\n''',
        "legacy feed provenance normalization",
    ),
    (
        '''    cache: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}\n    current: list[dict[str, Any]] = []\n    page_health: list[dict[str, Any]] = []\n    for candidate in queue:\n        item, health = make_item(candidate, cache)\n        page_health.append(health)\n        if item:\n            current.append(item)\n''',
        '''    current: list[dict[str, Any]] = []\n    page_health: list[dict[str, Any]] = []\n\n    def fetch_candidate(candidate: dict[str, str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:\n        # Candidate URLs are deduplicated before this point; a private cache per\n        # worker avoids shared mutable state while bounding wall-clock latency.\n        return make_item(candidate, {})\n\n    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mipe-fetch") as pool:\n        for item, health in pool.map(fetch_candidate, queue):\n            page_health.append(health)\n            if item:\n                current.append(item)\n''',
        "parallel candidate fetch",
    ),
    (
        '''    WEB_PATH.parent.mkdir(parents=True, exist_ok=True)\n    WEB_PATH.write_text(js, encoding="utf-8")\n''',
        '''    WEB_PATH.parent.mkdir(parents=True, exist_ok=True)\n    WEB_PATH.write_text(js, encoding="utf-8")\n\n    # GitHub Pages may cache static JavaScript by URL. Advance only the MIPE\n    # feed and adapter query versions after a completed ingest so every browser\n    # receives the newly persisted feed without invalidating unrelated assets.\n    if INDEX_PATH.exists():\n        index = INDEX_PATH.read_text(encoding="utf-8")\n        version = re.sub(r"[^0-9]", "", run["observedAt"])[:14]\n        updated = re.sub(r'(mipe-news\\.js\\?v=)[^"\\']+', rf'\\g<1>{version}', index)\n        updated = re.sub(r'(mipe-news-adapter\\.js\\?v=)[^"\\']+', rf'\\g<1>{version}', updated)\n        if updated != index:\n            INDEX_PATH.write_text(updated, encoding="utf-8")\n''',
        "MIPE asset cache bust",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"MIPE runtime {label}: already applied")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"MIPE runtime {label}: applied")
    else:
        raise SystemExit(f"Expected MIPE runtime pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
