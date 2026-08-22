#!/usr/bin/env python3
"""Fail closed when the reader-facing VÂLCEA CLAR presentation lags the live feed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
sys.path.insert(0, str(ROOT / "scripts"))
import public_ux_reset as ux  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def live_count_marker(count: int) -> str:
    return f"{count} materiale în fluxul curent"


def validate() -> dict:
    feed = load(RUNTIME / "live-feed.json")
    archive = load(SITE / "story_archive.json")
    state = load(SITE / "public_ux_state.json")
    stories, live_ids = ux.union_stories(feed, archive)
    reader_ids = {str(row.get("id")) for row in stories if row.get("id")}
    expected_live = {sid for sid in live_ids if sid in reader_ids}
    actual_story_ids = set(state.get("story_ids") or [])

    if state.get("live_story_count") != len(expected_live):
        raise SystemExit(
            f"Public UX live count drift: state={state.get('live_story_count')} expected={len(expected_live)}"
        )
    if not expected_live.issubset(actual_story_ids):
        missing = sorted(expected_live - actual_story_ids)
        raise SystemExit(f"Public UX missing live stories: {missing}")
    if feed.get("stories") and not expected_live:
        raise SystemExit("Public live feed has stories but Public UX resolved zero live reader stories")

    home = (RUNTIME / "index.html").read_text(encoding="utf-8")
    if expected_live:
        marker = live_count_marker(len(expected_live))
        if marker not in home:
            raise SystemExit(f"Public UX homepage live-count marker missing: {marker}")

    manifest = load(RUNTIME / "stiri" / "manifest.json")
    for row in manifest.get("stories") or []:
        if not isinstance(row, dict) or not row.get("id") or not row.get("path"):
            continue
        image = row.get("image") if isinstance(row.get("image"), dict) else None
        if not image:
            continue
        sid = str(row["id"])
        public_url = str(image.get("public_url") or "")
        page = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if not public_url or f'<meta property="og:image" content="{public_url}">' not in page:
            raise SystemExit(f"Verified story image regressed from Public UX: {sid}")

    result = {
        "status": "PASS",
        "safe_story_count": len(stories),
        "live_story_count": len(expected_live),
        "feed_story_count": len(feed.get("stories") or []),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def self_test() -> int:
    assert live_count_marker(0) == "0 materiale în fluxul curent"
    assert live_count_marker(30) == "30 materiale în fluxul curent"
    assert live_count_marker(0) != live_count_marker(30)
    assert live_count_marker(30).startswith("30 ")
    print("VÂLCEA CLAR Public UX freshness gate self-test: PASS")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    validate()
