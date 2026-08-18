#!/usr/bin/env python3
"""Render `/stiri/` from the same canonical live-feed used by the homepage.

The page shell (branding, navigation, CSS, footer) is recovered from the committed
same-revision static product, while the `<main>` body is rebuilt deterministically
from `site/runtime/live-feed.json`. This keeps the archive route current without
creating a second editorial source of truth.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNTIME = ROOT / "site" / "runtime"
FEED = RUNTIME / "live-feed.json"
TARGET = RUNTIME / "stiri" / "index.html"
COMMITTED_ROUTE = "valcea-clar/site/runtime/stiri/index.html"

BUCKETS = [
    ("bani-publici", "Bani publici", {"ADMINISTRAȚIE", "BANI PUBLICI", "ECONOMIE"}),
    ("servicii", "Servicii", {"MOBILITATE", "SERVICII", "SĂNĂTATE", "EDUCAȚIE", "UTILITĂȚI"}),
    ("cultura-evenimente", "Cultură & Evenimente", {"CULTURĂ", "EVENIMENTE"}),
    ("sport", "Sport", {"SPORT"}),
]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def committed_shell() -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{COMMITTED_ROUTE}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if proc.returncode != 0 or "<main" not in proc.stdout or "</main>" not in proc.stdout:
        raise RuntimeError("Cannot recover committed /stiri/ shell from current revision")
    return proc.stdout


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def story_date(story: dict[str, Any]) -> str:
    published = str(story.get("published_at") or story.get("date_published") or "")
    if published:
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            pass
    return ""


def story_row(story: dict[str, Any]) -> str:
    section = esc(story.get("section") or "ȘTIRI")
    date = esc(story_date(story))
    path = esc(story.get("path") or "#")
    headline = esc(story.get("headline") or "")
    dek = esc(story.get("dek") or "")
    return (
        '<article class="list-row">'
        f'<div><div class="kicker">{section}</div><div class="story-date">{date}</div></div>'
        f'<div><h2><a href="{path}">{headline}</a></h2><p>{dek}</p></div>'
        '</article>'
    )


def story_card(story: dict[str, Any], bucket: str) -> str:
    section = esc(story.get("section") or "ȘTIRI")
    path = esc(story.get("path") or "#")
    headline = esc(story.get("headline") or "")
    dek = esc(story.get("dek") or "")
    date = esc(story_date(story))
    return (
        f'<article class="card" data-bucket="{esc(bucket)}">'
        f'<div class="kicker">{section}</div>'
        f'<h3><a href="{path}">{headline}</a></h3>'
        f'<p>{dek}</p><div class="story-date">{date}</div></article>'
    )


def normalized_stories(feed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in feed.get("stories", []) if isinstance(row, dict)]
    rows = [row for row in rows if row.get("path") and row.get("headline")]
    rows.sort(key=lambda row: (-int(row.get("priority") or 0), str(row.get("id") or "")))
    return rows


def updated_label(feed: dict[str, Any]) -> str:
    raw = str(feed.get("generated_at") or "")
    if not raw:
        return "Actualizare editorială continuă"
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return f"Feed canonic actualizat: {value.strftime('%d.%m.%Y %H:%M')} UTC"
    except ValueError:
        return "Actualizare editorială continuă"


def build_main(feed: dict[str, Any]) -> str:
    stories = normalized_stories(feed)
    rows = "".join(story_row(story) for story in stories)
    if not rows:
        rows = '<p class="empty">Nu există în acest moment materiale jurnalistice publicabile în feed-ul canonic.</p>'

    sections: list[str] = []
    for bucket_id, title, accepted in BUCKETS:
        bucket_stories = [story for story in stories if str(story.get("section") or "").upper() in accepted]
        cards = "".join(story_card(story, bucket_id) for story in bucket_stories[:6])
        if not cards:
            cards = '<p class="empty">Nu există materiale curente în această secțiune.</p>'
        sections.append(
            f'<section class="section" id="{bucket_id}">'
            f'<div class="section-head"><h2>{esc(title)}</h2><a href="/stiri/#{bucket_id}">Vezi secțiunea</a></div>'
            f'<div class="cards">{cards}</div></section>'
        )

    return (
        '<main>'
        '<div class="kicker">ȘTIRI</div>'
        '<h1 class="index-title">Știrile Vâlcii, puse în ordine.</h1>'
        '<p class="index-dek">Aici apar materialele jurnalistice publicabile din feed-ul canonic VÂLCEA CLAR. '
        'Dosarele de documentare și monitoarele interne nu sunt folosite pentru a umple categorii.</p>'
        f'<div class="live-strip"><strong>LIVE</strong><span>{esc(updated_label(feed))}</span></div>'
        f'<section id="ultimele" class="all-list">{rows}</section>'
        + "".join(sections)
        + '</main>'
    )


def render(shell: str, feed: dict[str, Any]) -> str:
    body = build_main(feed)
    updated, count = re.subn(r"<main\b[^>]*>.*?</main>", body, shell, count=1, flags=re.DOTALL | re.IGNORECASE)
    if count != 1:
        raise RuntimeError("Committed /stiri/ shell does not contain exactly one main element")
    if 'data-nav-contract="valcea-clar-primary-v2"' not in updated:
        raise RuntimeError("Refusing /stiri/ render without canonical navigation contract")
    return updated


def build(*, feed_path: Path = FEED, target: Path = TARGET) -> dict[str, Any]:
    feed = load_json(feed_path)
    stories = normalized_stories(feed)
    output = render(committed_shell(), feed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")
    rendered_ids = [str(row.get("id") or "") for row in stories]
    for story in stories:
        path = str(story.get("path") or "")
        if path and path not in output:
            raise RuntimeError(f"Rendered /stiri/ is missing canonical story path {path}")
    return {
        "status": "PASS",
        "route": "/stiri/",
        "story_count": len(stories),
        "story_ids": rendered_ids,
        "nav_contract": "valcea-clar-primary-v2",
        "source": "site/runtime/live-feed.json",
    }


def self_test() -> int:
    shell = '<html><body data-nav-contract="valcea-clar-primary-v2"><header>x</header><main>old</main><footer>y</footer></body></html>'
    feed = {
        "generated_at": "2026-08-18T13:10:21Z",
        "stories": [{
            "id": "s1", "section": "SPORT", "priority": 88,
            "headline": "Meci verificat", "dek": "Program oficial.",
            "path": "/stiri/s1/", "published_at": "2026-08-18T16:10:21+03:00",
        }],
    }
    result = render(shell, feed)
    assert "/stiri/s1/" in result
    assert "Meci verificat" in result
    assert "<header>x</header>" in result and "<footer>y</footer>" in result
    assert 'id="sport"' in result
    print("VÂLCEA CLAR dynamic /stiri/ renderer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
