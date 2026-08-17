#!/usr/bin/env python3
"""Clean stale story routes without weakening the canonical story manifest."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
STATE = SITE / "public_ux_state.json"
STORY_ROOT = RUNTIME / "stiri"
MANIFEST = STORY_ROOT / "manifest.json"
BASE = "https://valceaclar.ro"

LEGACY_NON_NEWS_REDIRECTS = {
    "/stiri/ansambluri-rezidentiale-ramnicu-valcea/": "/stiri/",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def redirect_html(target: str) -> str:
    return f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow"><link rel="canonical" href="{BASE}{target}"><meta http-equiv="refresh" content="0; url={target}"><title>Material mutat — VÂLCEA CLAR</title></head><body><p>Acest material nu mai este clasificat ca știre. <a href="{target}">Vezi știrile VÂLCEA CLAR</a>.</p></body></html>'''


def build() -> dict:
    state = load(STATE)
    manifest = load(MANIFEST)
    safe_ids = {str(value) for value in state.get("story_ids") or []}
    manifest_ids = {str(row.get("id")) for row in manifest.get("stories") or [] if row.get("id")}
    if not safe_ids or safe_ids != manifest_ids:
        raise SystemExit("Public UX cleanup requires the integrity manifest to match the safe story set")

    STORY_ROOT.mkdir(parents=True, exist_ok=True)
    for child in STORY_ROOT.iterdir():
        if child.is_dir() and child.name not in safe_ids and f"/stiri/{child.name}/" not in LEGACY_NON_NEWS_REDIRECTS:
            shutil.rmtree(child)

    redirects = []
    for source, target in LEGACY_NON_NEWS_REDIRECTS.items():
        page = RUNTIME / source.strip("/") / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(redirect_html(target), encoding="utf-8")
        redirects.append({"path": source, "target": target, "robots": "noindex,follow"})

    state["legacy_non_news_redirects"] = redirects
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","safe_story_routes":len(manifest_ids),"legacy_redirects":len(redirects)}, ensure_ascii=False))
    return state


def check() -> None:
    state = load(STATE)
    manifest = load(MANIFEST)
    ids = {str(row.get("id")) for row in manifest.get("stories") or []}
    if ids != {str(value) for value in state.get("story_ids") or []}:
        raise SystemExit("Public UX story manifest drift")
    for row in manifest.get("stories") or []:
        if not (RUNTIME / str(row["path"]).strip("/") / "index.html").is_file():
            raise SystemExit(f"Missing safe story route: {row['path']}")
        if not row.get("published_at") or not row.get("related_story_ids"):
            raise SystemExit(f"Story integrity metadata missing: {row['id']}")
    for row in state.get("legacy_non_news_redirects") or []:
        text = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if 'noindex,follow' not in text or str(row["target"]) not in text:
            raise SystemExit(f"Legacy redirect invalid: {row['path']}")
    print("VÂLCEA CLAR public UX cleanup validation: PASS")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        check()
    else:
        build()
