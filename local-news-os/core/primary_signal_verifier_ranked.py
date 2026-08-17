#!/usr/bin/env python3
"""Rank primary-source article candidates before strict signal verification.

The base verifier intentionally remains generic and conservative. This adapter
improves recall by preferring links that structurally belong to the configured
primary listing (for example a police news archive) over navigation/static pages.
It changes candidate ordering only; it does not lower the strict semantic/date
corroboration gate or grant publication authority.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as base  # noqa: E402
import signal_radar as radar  # noqa: E402

ORIGINAL_TARGET_REGISTRY = base.target_registry
ORIGINAL_CANDIDATE_LINKS = base.candidate_links

NEWS_PATH_MARKERS = (
    "/stiri/", "/stiri-si-media/stiri/", "/comunicate/", "/comunicate-de-presa/",
    "/noutati/", "/noutăți/", "/news/", "/evenimente/", "/blog/",
)
NAVIGATION_PENALTIES = (
    "/contact", "/despre", "/organizare", "/organigrama", "/conducere", "/cariera",
    "/i-p-j-", "/politia-de-proximitate", "/structura", "/servicii", "/informatii-publice",
    "/legislatie", "/declaratii", "/protectia-datelor", "/petitii",
)


def _load_registry(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def ranked_target_registry(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    docs = [
        ("news_source_id", _load_registry(radar.repo_file(str(config.get("news_registry_path") or "")))),
        ("manual_watch_source_id", _load_registry(radar.repo_file(str(config.get("manual_watch_registry_path") or "")))),
    ]
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for ref_type, doc in docs:
        for row in doc.get("sources") or []:
            if not isinstance(row, dict) or not row.get("id") or not row.get("url"):
                continue
            result[(ref_type, str(row["id"]))] = {
                "ref_type": ref_type,
                "id": str(row["id"]),
                "name": str(row.get("publisher") or row["id"]),
                "url": str(row["url"]),
                "tier": str(row.get("tier") or "T1"),
                "status": row.get("status"),
                "enabled": row.get("enabled", True),
                "path_hints": [str(value).casefold() for value in row.get("path_hints") or [] if str(value).strip()],
            }
    return result


def structural_score(target: dict[str, Any], listing_url: str, candidate_url: str, label: str) -> tuple[int, str, str]:
    target_parsed = urllib.parse.urlsplit(str(target["url"]))
    listing_parsed = urllib.parse.urlsplit(listing_url)
    candidate = urllib.parse.urlsplit(candidate_url)
    path = candidate.path.casefold()
    label_norm = radar.norm_text(label)
    score = 0

    # Strongest signal: the item is a descendant of the configured listing path.
    listing_path = listing_parsed.path.rstrip("/").casefold()
    target_path = target_parsed.path.rstrip("/").casefold()
    for base_path in (listing_path, target_path):
        if base_path and base_path != "/" and path.startswith(base_path + "/"):
            score += 140
            break

    # Configured path hints are source-owned structural evidence, not semantics.
    for hint in target.get("path_hints") or []:
        hint_norm = str(hint).casefold().strip()
        if hint_norm and (hint_norm in path or radar.norm_text(hint_norm) in label_norm):
            score += 45
            break

    if any(marker in path for marker in NEWS_PATH_MARKERS):
        score += 55
    if re.search(r"/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/|$)", path):
        score += 35
    if re.search(r"(?:^|[-_/])20\d{2}(?:[-_/]|$)", path):
        score += 10
    if 35 <= len(radar.clean(label)) <= 220:
        score += 15
    if any(marker in path for marker in NAVIGATION_PENALTIES):
        score -= 180
    if candidate_url.rstrip("/") == listing_url.rstrip("/"):
        score -= 250

    # Stable tie breakers keep execution deterministic.
    return score, path, candidate_url


def ranked_candidate_links(target: dict[str, Any], max_links: int) -> tuple[list[tuple[str, str]], str | None]:
    try:
        listing, final = radar.fetch(str(target["url"]), max_bytes=2_000_000, timeout=14)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"[:400]

    parser = radar.AnchorParser()
    parser.feed(listing)
    candidates: dict[str, tuple[str, str]] = {}
    # Collect broadly first; ranking, not DOM order, decides what gets fetched.
    for href, label in parser.links[:1200]:
        candidate = radar.article_like(final, href, label)
        if candidate:
            candidates.setdefault(candidate[0], candidate)
        if len(candidates) >= 240:
            break

    ranked = sorted(
        candidates.values(),
        key=lambda row: structural_score(target, final, row[0], row[1]),
        reverse=True,
    )
    selected = ranked[:max_links]
    # Root is research fallback only and placed last; strict v2 will reject it
    # automatically when it lacks article-level publication metadata/title match.
    selected.append((final, target["name"]))
    return selected, None


def install_ranking() -> None:
    base.target_registry = ranked_target_registry
    base.candidate_links = ranked_candidate_links


def validate(instance_id: str) -> dict[str, Any]:
    import signal_radar as signal
    config, _ = signal.load_config(instance_id)
    install_ranking()
    registry = base.target_registry(config)
    hinted = sum(1 for row in registry.values() if row.get("path_hints"))
    return {
        "status": "PASS",
        "instance_id": instance_id,
        "registered_targets": len(registry),
        "targets_with_path_hints": hinted,
        "ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "publication_authority": "NONE",
    }


def self_test() -> int:
    target = {
        "url": "https://example.invalid/ro/stiri-si-media/stiri",
        "path_hints": ["stiri-si-media/stiri"],
    }
    official_story = structural_score(
        target,
        target["url"],
        "https://example.invalid/ro/stiri-si-media/stiri/eveniment-rutier-important",
        "Eveniment rutier important în localitate",
    )[0]
    nav_page = structural_score(
        target,
        target["url"],
        "https://example.invalid/ro/i-p-j-test/politia-de-proximitate",
        "Poliția de proximitate",
    )[0]
    other_news = structural_score(
        target,
        target["url"],
        "https://example.invalid/ro/stiri-si-media/stiri/alt-comunicat-important",
        "Alt comunicat important al instituției",
    )[0]
    assert official_story > nav_page + 200, (official_story, nav_page)
    assert other_news > nav_page, (other_news, nav_page)
    print("LOCAL NEWS OS primary candidate ranking self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("--instance is required")
    if args.validate_only:
        print(json.dumps(validate(args.instance), ensure_ascii=False))
        return 0
    parser.error("ranking adapter is installed by the strict ranked verifier")


if __name__ == "__main__":
    raise SystemExit(main())
