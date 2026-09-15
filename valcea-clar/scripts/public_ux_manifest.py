#!/usr/bin/env python3
"""Keep the canonical public story set durable and clean only proven non-news routes.

The Public UX projector is a derived presentation writer. It may reshape the
reader surface, but it must not erase a story that was already published merely
because that story fell out of the current live/recap window. Git history is a
durable evidence source for this narrow recovery case: when the projector itself
previously deleted a fully formed NewsArticle route, recover that exact committed
page unless a current explicit publication hold suppresses it.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
STATE = SITE / "public_ux_state.json"
HOLDS = ROOT / "editorial" / "publication_holds.json"
STORY_ROOT = RUNTIME / "stiri"
MANIFEST = STORY_ROOT / "manifest.json"
BASE = "https://valceaclar.ro"
PROJECTOR_AUTHOR = "valcea-clar-story-meta[bot]"
PROJECTOR_SUBJECT = "Refresh VÂLCEA CLAR canonical public presentation"

LEGACY_NON_NEWS_REDIRECTS = {
    "/stiri/ansambluri-rezidentiale-ramnicu-valcea/": "/stiri/",
}


def load(path: Path, default=None) -> dict:
    if not path.is_file():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def redirect_html(target: str) -> str:
    return f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow"><link rel="canonical" href="{BASE}{target}"><meta http-equiv="refresh" content="0; url={target}"><title>Material mutat — VÂLCEA CLAR</title></head><body><p>Acest material nu mai este clasificat ca știre. <a href="{target}">Vezi știrile VÂLCEA CLAR</a>.</p></body></html>'''


def held_ids() -> set[str]:
    doc = load(HOLDS, {"holds": []})
    return {
        str(row.get("story_id"))
        for row in doc.get("holds") or []
        if isinstance(row, dict)
        and row.get("story_id")
        and row.get("public_projection") is False
    }


def text_only(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def article_contract(story_id: str, raw: str, related_candidates: list[str]) -> dict | None:
    """Accept only an exact previously published NewsArticle page."""
    route = f"/stiri/{story_id}/"
    canonical = BASE + route
    if f'<link rel="canonical" href="{canonical}">' not in raw:
        return None
    if '<section class="article-sources">' not in raw:
        return None

    documents = []
    for match in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, flags=re.S):
        try:
            value = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("@type") == "NewsArticle":
            documents.append(value)
    if not documents:
        return None
    document = documents[0]
    if str(document.get("url") or "") != canonical:
        return None
    headline = str(document.get("headline") or "").strip()
    published_at = str(document.get("datePublished") or "").strip()
    if not headline or not published_at:
        return None

    visible_h1 = re.search(r"<h1>(.*?)</h1>", raw, flags=re.S)
    if not visible_h1 or text_only(visible_h1.group(1)) != headline:
        return None
    body = re.search(r'<div class="article-body">(.*?)</div>', raw, flags=re.S)
    if not body or not re.findall(r"<p>.*?</p>", body.group(1), flags=re.S):
        return None
    sources = re.search(r'<section class="article-sources">(.*?)</section>', raw, flags=re.S)
    if not sources or not re.findall(r'<a href="https?://', sources.group(1)):
        return None

    related = [sid for sid in related_candidates if sid != story_id][:3]
    if not related:
        return None
    return {
        "id": story_id,
        "path": route,
        "canonical": canonical,
        "published_at": published_at,
        "archive_status": "published_projection_recovered",
        "active_now": False,
        "related_story_ids": related,
        "structured_data_type": "NewsArticle",
        "social_metadata_type": "article",
        "public_ux_authorized": True,
        "projection_recovery": {
            "basis": "previously_published_route_deleted_by_derived_projector",
            "truth_source": "git_history_exact_page",
        },
    }


def projector_deleted_pages(existing_ids: set[str]) -> list[dict]:
    """Recover only pages whose last destructive writer was this derived projector.

    This intentionally does not revive arbitrary deleted routes. Explicit holds,
    legacy non-news redirects and pages without an exact NewsArticle contract stay
    out of the public set.
    """
    proc = subprocess.run(
        [
            "git", "log", "--diff-filter=D", "--name-status",
            "--format=@@%H%x09%an%x09%s", "--",
            "valcea-clar/site/runtime/stiri",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        return []

    held = held_ids()
    current_meta: tuple[str, str, str] | None = None
    deletions: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            parts = line[2:].split("\t", 2)
            current_meta = tuple(parts) if len(parts) == 3 else None
            continue
        if not current_meta or not line.startswith("D\t"):
            continue
        path = line.split("\t", 1)[1].strip()
        match = re.fullmatch(r"valcea-clar/site/runtime/stiri/([^/]+)/index\.html", path)
        if not match:
            continue
        story_id = match.group(1)
        route = f"/stiri/{story_id}/"
        commit, author, subject = current_meta
        if story_id in seen or story_id in existing_ids or story_id in held:
            continue
        if route in LEGACY_NON_NEWS_REDIRECTS:
            continue
        # The newest deletion for a missing route is authoritative. Only derived
        # presentation pruning is recoverable here; other deletion reasons remain deleted.
        seen.add(story_id)
        if author == PROJECTOR_AUTHOR and subject == PROJECTOR_SUBJECT:
            deletions.append((story_id, path, commit))

    related_candidates = sorted(existing_ids)
    recovered: list[dict] = []
    for story_id, path, deletion_commit in deletions:
        show = subprocess.run(
            ["git", "show", f"{deletion_commit}^:{path}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if show.returncode != 0 or not show.stdout:
            continue
        row = article_contract(story_id, show.stdout, related_candidates)
        if row is None:
            continue
        target = RUNTIME / row["path"].strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(show.stdout, encoding="utf-8")
        row["projection_recovery"]["deletion_commit"] = deletion_commit
        recovered.append(row)
    return recovered


def augment_with_durable_history(state: dict, manifest: dict) -> list[dict]:
    rows = [row for row in manifest.get("stories") or [] if isinstance(row, dict) and row.get("id")]
    ids = {str(row["id"]) for row in rows}
    recovered = projector_deleted_pages(ids)
    if not recovered:
        return []

    rows.extend(recovered)
    manifest["stories"] = rows
    manifest["projection_history_recovery"] = {
        "enabled": True,
        "policy": "recover_only_exact_newsarticle_pages_deleted_by_derived_projector_without_current_hold",
        "recovered_story_ids": [str(row["id"]) for row in recovered],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    story_ids = [str(value) for value in state.get("story_ids") or []]
    routes = [str(value) for value in state.get("routes") or []]
    for row in recovered:
        if row["id"] not in story_ids:
            story_ids.append(str(row["id"]))
        if row["path"] not in routes:
            routes.append(str(row["path"]))
    state["story_ids"] = story_ids
    state["routes"] = routes
    state["safe_story_count"] = len(story_ids)
    state.setdefault("policy", {})["published_story_route_durability"] = "git_history_truth_bound_recovery"
    state["projection_history_recovery"] = {
        "recovered_story_ids": [str(row["id"]) for row in recovered],
        "count": len(recovered),
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return recovered


def build() -> dict:
    state = load(STATE)
    manifest = load(MANIFEST)
    recovered = augment_with_durable_history(state, manifest)
    if recovered:
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
    print(json.dumps({
        "status": "PASS",
        "safe_story_routes": len(manifest_ids),
        "legacy_redirects": len(redirects),
        "projection_history_recovered": [str(row["id"]) for row in recovered],
    }, ensure_ascii=False))
    return state


def check() -> None:
    state = load(STATE)
    manifest = load(MANIFEST)
    ids = {str(row.get("id")) for row in manifest.get("stories") or [] if row.get("id")}
    if ids != {str(value) for value in state.get("story_ids") or []}:
        raise SystemExit("Public UX story manifest drift")
    for row in manifest.get("stories") or []:
        page = RUNTIME / str(row["path"]).strip("/") / "index.html"
        if not page.is_file():
            raise SystemExit(f"Missing safe story route: {row['path']}")
        text = page.read_text(encoding="utf-8")
        if not row.get("published_at") or not row.get("related_story_ids"):
            raise SystemExit(f"Story integrity metadata missing: {row['id']}")
        if row.get("projection_recovery"):
            if '<script type="application/ld+json">' not in text or '"@type":"NewsArticle"' not in text:
                raise SystemExit(f"Recovered route lost NewsArticle contract: {row['id']}")
            if f'<link rel="canonical" href="{row["canonical"]}">' not in text:
                raise SystemExit(f"Recovered route canonical mismatch: {row['id']}")
    for row in state.get("legacy_non_news_redirects") or []:
        text = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if 'noindex,follow' not in text or str(row["target"]) not in text:
            raise SystemExit(f"Legacy redirect invalid: {row['path']}")
    print("VÂLCEA CLAR public UX cleanup + durable published-route validation: PASS")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        check()
    else:
        build()
