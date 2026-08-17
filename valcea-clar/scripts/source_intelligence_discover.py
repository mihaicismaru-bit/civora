#!/usr/bin/env python3
"""Bounded, zero-paid source discovery/probation probe for VÂLCEA CLAR.

Starts from explicit source-intelligence seeds, discovers standard metadata and
relevant links, and persists candidates only as DISCOVERED_UNRATED. This module
has zero publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "source_intelligence_seed_registry.json"
STATE = ROOT / "editorial" / "source_intelligence_discovery_state.json"
USER_AGENT = "ValceaClar-SourceIntelligence/2.0 (+https://valceaclar.ro/)"
KEY_TERMS = (
    "stiri", "știri", "news", "noutati", "noutăți", "comunicate", "comunicat",
    "anunturi", "anunțuri", "hotarari", "hotărâri", "consili", "sedinte", "ședințe",
    "achiz", "licit", "urbanism", "autoriz", "proiect", "invest", "evenimente",
    "events", "jobs", "posturi", "concurs", "blog", "presa", "press", "document",
    "transparenta", "transparență", "menu", "meniu", "rss", "atom", "feed", "sitemap",
)


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.anchor_href: str | None = None
        self.anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.anchor_href = str(attrs["href"])
            self.anchor_text = []
        if tag == "link" and attrs.get("href"):
            self.links.append((str(attrs["href"]), "link:" + str(attrs.get("rel") or "")))

    def handle_data(self, data):
        if self.anchor_href is not None:
            self.anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor_href is not None:
            self.links.append((self.anchor_href, " ".join(self.anchor_text)))
            self.anchor_href = None
            self.anchor_text = []


def expand(raw: list, defaults: dict) -> dict:
    sid, publisher, url, tier, family, sensitive = raw
    route = (
        "T3_DISCOVERY_ONLY_TO_HIGHER_AUTHORITY" if tier == "T3" else
        "T2_SIGNAL_TO_T1_T1B_CONFIRMATION" if tier == "T2" else
        "PRIMARY_SOURCE_SIGNAL_REQUIRES_STORY_GATE"
    )
    return {
        "id": sid, "publisher": publisher, "url": url, "tier": tier, "family": family,
        "sensitive": sensitive, "verification_route": route, **defaults,
    }


def norm(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def fetch(url: str, timeout: int = 18) -> tuple[str, bytes, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.2"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        final = response.geturl()
        ctype = (response.headers.get("Content-Type") or "").lower()
        body = response.read(1_500_000)
    return final, body, ctype


def make_candidate(seed: dict, url: str, reason: str) -> dict:
    return {
        "candidate_id": hashlib.sha256((seed["id"] + "\0" + url).encode()).hexdigest()[:24],
        "seed_id": seed["id"],
        "url": url,
        "discovered_by": reason,
        "tier_ceiling": seed["tier"],
        "lifecycle": "DISCOVERED_UNRATED",
        "public_projection": False,
        "auto_publication": False,
        "verification_route": seed["verification_route"],
    }


def discover(seed: dict) -> dict:
    row = {
        "seed_id": seed["id"], "publisher": seed["publisher"], "seed_url": seed["url"],
        "checked_at_epoch": int(time.time()), "status": "DEGRADED", "http_error": None,
        "final_url": None, "content_sha256": None, "candidates": [],
    }
    try:
        final, body, ctype = fetch(seed["url"])
        row["final_url"] = final
        row["content_sha256"] = hashlib.sha256(body).hexdigest()
        row["status"] = "PASS"
        parsed = urllib.parse.urlsplit(final)
        seed_host = parsed.netloc.lower().removeprefix("www.")
        origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        candidates: dict[str, dict] = {}
        for rel, reason in (
            ("robots.txt", "standard:robots"),
            ("sitemap.xml", "standard:sitemap"),
            ("feed/", "standard:feed"),
            ("rss/", "standard:rss"),
        ):
            url = norm(urllib.parse.urljoin(origin, rel))
            candidates[url] = make_candidate(seed, url, reason)

        html_like = "html" in ctype or body.lstrip().lower().startswith(b"<!doctype") or b"<html" in body[:1000].lower()
        if html_like:
            parser = LinkParser()
            parser.feed(body.decode("utf-8", errors="replace"))
            for href, label in parser.links:
                try:
                    url = norm(urllib.parse.urljoin(final, href))
                except Exception:
                    continue
                p = urllib.parse.urlsplit(url)
                if p.scheme not in {"http", "https"} or not p.netloc:
                    continue
                host = p.netloc.lower().removeprefix("www.")
                hay = (p.path + " " + p.query + " " + label).lower()
                same_domain = host == seed_host or host.endswith("." + seed_host)
                relevant_internal = same_domain and any(term in hay for term in KEY_TERMS)
                directory_external = seed["family"] == "DISCOVERY_DIRECTORY" and host != seed_host
                if relevant_internal or directory_external:
                    reason = "html:relevant_internal" if same_domain else "directory:external_link"
                    candidates[url] = make_candidate(seed, url, reason)
        row["candidates"] = list(candidates.values())[:120]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        row["http_error"] = str(exc)[:400]
    return row


def self_test() -> int:
    defaults = {"signal_only": True, "public_projection": False, "auto_publication": False}
    seed = expand(["test", "Test", "https://example.com/", "T3", "DISCOVERY_DIRECTORY", False], defaults)
    candidate = make_candidate(seed, "https://example.com/news", "test")
    assert candidate["public_projection"] is False
    assert candidate["auto_publication"] is False
    assert candidate["lifecycle"] == "DISCOVERED_UNRATED"
    print("VÂLCEA CLAR source discovery self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    defaults = data.get("defaults") or {}
    seeds = [expand(raw, defaults) for raw in data.get("seed_sources", [])]
    if not seeds:
        raise SystemExit("No source seeds")
    limit = max(1, min(args.limit, 30))
    offset = args.offset % len(seeds)
    selected = [seeds[(offset + i) % len(seeds)] for i in range(min(limit, len(seeds)))]
    observations = [discover(seed) for seed in selected]

    previous = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    by_seed = {row["seed_id"]: row for row in previous.get("observations", [])}
    for row in observations:
        by_seed[row["seed_id"]] = row
    candidates: dict[str, dict] = {}
    for row in by_seed.values():
        for candidate in row.get("candidates", []):
            candidates[candidate["candidate_id"]] = candidate

    output = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR Source Intelligence discovery state",
        "publication_authority": "NONE",
        "seed_count": len(seeds),
        "observations": sorted(by_seed.values(), key=lambda item: item["seed_id"]),
        "candidate_count": len(candidates),
        "candidates": sorted(candidates.values(), key=lambda item: (item["seed_id"], item["url"])),
    }
    STATE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "probed": len(observations), "known_candidates": len(candidates),
        "publication_authority": "NONE", "state": str(STATE),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
