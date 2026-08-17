#!/usr/bin/env python3
"""Add reader-facing section and legacy-cleanup routes to the Sites export."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "chatgpt-sites"
MANIFEST = DIST / "manifest.json"
STATE = ROOT / "site" / "public_ux_state.json"
BASE = "https://valceaclar.ro"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    manifest = load(MANIFEST)
    state = load(STATE)
    routes = [
        row for row in manifest.get("routes") or []
        if str(row.get("path") or "") not in {"/stiri/", "/despre/"}
        and str(row.get("path") or "") not in {str(x.get("path")) for x in state.get("legacy_non_news_redirects") or []}
    ]
    insert = [
        {
            "path": "/stiri/",
            "source": "stiri/index.html",
            "title": "Știri — VÂLCEA CLAR",
            "update_mode": "replace_page",
            "publication_unit": "news_index",
            "canonical_url": BASE + "/stiri/",
        },
        {
            "path": "/despre/",
            "source": "despre/index.html",
            "title": "Despre VÂLCEA CLAR",
            "update_mode": "replace_page",
            "publication_unit": "about_page",
            "canonical_url": BASE + "/despre/",
        },
    ]
    for row in state.get("legacy_non_news_redirects") or []:
        source = str(row["path"]).strip("/") + "/index.html"
        insert.append({
            "path": row["path"],
            "source": source,
            "title": "Material mutat — VÂLCEA CLAR",
            "update_mode": "replace_page",
            "publication_unit": "legacy_non_news_redirect",
            "canonical_url": BASE + str(row["target"]),
            "robots": "noindex,follow",
        })
    for row in insert:
        if not (DIST / str(row["source"])).is_file():
            raise SystemExit(f"Public UX export source missing: {row['source']}")
    routes[1:1] = insert
    manifest["routes"] = routes
    manifest.setdefault("counts", {})["routes"] = len(routes)
    manifest["counts"]["reader_section_routes"] = 2
    manifest["counts"]["legacy_non_news_redirects"] = len(state.get("legacy_non_news_redirects") or [])
    manifest.setdefault("target", {})["public_ux_contract"] = state.get("contract_id")
    manifest["target"]["navigation_contract"] = state.get("navigation_contract")
    manifest["public_ux"] = {
        "news_index": "/stiri/",
        "about": "/despre/",
        "same_navigation_everywhere": True,
        "cross_category_fill": False,
        "monitoring_is_news": False,
        "legacy_non_news_redirects": state.get("legacy_non_news_redirects") or [],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","routes":len(routes),"reader_sections":2,"redirects":len(state.get("legacy_non_news_redirects") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
