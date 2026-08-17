#!/usr/bin/env python3
"""Entry point that augments MIPE Windows crawl v3 with targeted dossier seeds."""
from __future__ import annotations

import json
from pathlib import Path

import mipe_windows_crawl_v3 as crawler

ROOT = Path(__file__).resolve().parents[2]
SEEDS_PATH = ROOT / "partener-eu/ingest/state/mipe_enrichment_seeds.json"

try:
    payload = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
except Exception:
    payload = {"seeds": []}

existing = set(crawler.SEEDS)
extra = []
for row in payload.get("seeds") or []:
    url = str(row.get("url") or "").strip()
    if not url or url in existing:
        continue
    if not (url.startswith("https://mfe.gov.ro/") or url.startswith("https://www.mfe.gov.ro/")):
        continue
    existing.add(url)
    extra.append(url)

# Targeted unseen guide/call pages are placed before broad programme roots.
crawler.SEEDS[:] = [crawler.ROOT_URL, *extra, *[x for x in crawler.SEEDS if x != crawler.ROOT_URL]]
print(json.dumps({"baseSeeds": len(crawler.SEEDS) - len(extra), "targetedSeeds": len(extra), "totalSeeds": len(crawler.SEEDS)}, ensure_ascii=False, indent=2))
raise SystemExit(crawler.main())
