#!/usr/bin/env python3
"""Strict publication boundary for MIPE ingestion.

Search/index services may discover canonical official URLs, but only bytes fetched
straight from the canonical official host may create or refresh a published
MIPE fact. Third-party readers, translation wrappers and relays are never
accepted as factual retrieval transports.

The PDDS priority tree is discovered only by crawling the explicit official
seed at https://mfe.gov.ro/pdds/despre-program-programare/ and following links
that remain under https://mfe.gov.ro/pdds/.
"""
from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET

import mipe_resilient_ingest as base

PDDS_PRIORITY_SEED = "https://mfe.gov.ro/pdds/despre-program-programare/"


def direct_only_fetch_document(target: str):
    canonical = base.canonicalize(target)
    if not canonical:
        return None, {
            "target": target,
            "ok": False,
            "transport": "direct-canonical",
            "error": "non_official_target",
            "policy": "direct-official-bytes-required-for-publication",
        }

    response = base.fetch(canonical, timeout=8, attempts=1)
    if not response.get("ok"):
        return None, {
            "target": canonical,
            "ok": False,
            "transport": "direct-canonical",
            "error": response.get("error", "direct_fetch_failed"),
            "policy": "search-discovery-only-on-direct-source-failure",
        }

    final_url = base.canonicalize(response.get("url") or canonical)
    if not final_url:
        return None, {
            "target": canonical,
            "ok": False,
            "transport": "direct-canonical",
            "error": "direct_redirect_left_official_allowlist",
            "policy": "direct-official-bytes-required-for-publication",
        }

    # PDDS is a deliberately bounded crawl. The priority seed may never redirect
    # the crawler outside the official /pdds/ tree.
    if canonical == PDDS_PRIORITY_SEED:
        parsed_final = urllib.parse.urlparse(final_url)
        if parsed_final.hostname != "mfe.gov.ro" or not parsed_final.path.startswith("/pdds/"):
            return None, {
                "target": canonical,
                "ok": False,
                "transport": "direct-canonical",
                "error": "pdds_seed_redirect_outside_scope",
                "policy": "pdds-seed-crawl-must-remain-under-mfe-gov-ro-pdds",
            }

    content_type = str(response.get("content_type") or "").lower()
    health = {
        "target": canonical,
        "ok": True,
        "transport": "direct-canonical",
        "verification": "CANONICAL_OFFICIAL_FETCH",
        "finalUrl": final_url,
    }
    try:
        if "json" in content_type:
            return {
                "json": json.loads(response["data"].decode("utf-8", errors="replace")),
                "canonical": final_url,
            }, health
        if "xml" in content_type or response["data"].lstrip().startswith(b"<?xml"):
            return {"xml": response["data"], "canonical": final_url}, health
        parsed = base.parse_html(response["data"])
        parsed["canonical"] = final_url
        return parsed, health
    except Exception as exc:  # persisted as parser/source health evidence
        return None, {
            "target": canonical,
            "ok": False,
            "transport": "direct-canonical",
            "error": f"direct_parse:{type(exc).__name__}:{exc}",
            "policy": "last-known-good-preserved-on-parser-failure",
        }


def preserve_only_directly_verified(item: dict) -> bool:
    return (
        item.get("verification") == "CANONICAL_OFFICIAL_FETCH"
        and str(item.get("retrievalTransport") or "").startswith("direct")
    )


def bing_rss_discovery():
    """Discovery-only fallback when the primary index adapter is unavailable.

    Bing RSS bytes and snippets are never publishable evidence. They may only
    contribute canonical URLs on the existing official allowlist. PDDS URLs are
    deliberately excluded here because the PDDS tree must originate from the
    explicit priority-seed crawl.
    """
    candidates = []
    health = []
    for query in base.DISCOVERY_QUERIES:
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({
            "q": query,
            "format": "rss",
            "count": 20,
        })
        result = base.fetch(
            search_url,
            timeout=12,
            attempts=1,
            accept="application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5",
        )
        row = {
            "query": query,
            "ok": bool(result.get("ok")),
            "transport": "bing-rss-discovery-only",
            "error": result.get("error"),
            "publicationPolicy": "discovery-only; canonical direct fetch required",
            "pddsDiscoveryPolicy": "PDDS candidates must originate from the explicit priority seed crawl",
            "discoveredOfficialUrlCount": 0,
            "excludedPddsSearchCandidates": 0,
        }
        if not result.get("ok"):
            health.append(row)
            continue
        try:
            root = ET.fromstring(result["data"])
            seen = set()
            for item in root.findall(".//item"):
                raw_url = base.clean_text(item.findtext("link"))
                canonical = base.canonicalize(raw_url)
                if not canonical or canonical in seen:
                    continue
                parsed = urllib.parse.urlparse(canonical)
                if parsed.hostname == "mfe.gov.ro" and parsed.path.startswith("/pdds/"):
                    row["excludedPddsSearchCandidates"] += 1
                    continue
                seen.add(canonical)
                candidates.append({
                    "url": canonical,
                    "title_hint": base.clean_text(item.findtext("title")),
                    "excerpt_hint": base.clean_text(item.findtext("description")),
                    "discovery": "bing-rss-official-url",
                })
            row["discoveredOfficialUrlCount"] = len(seen)
        except Exception as exc:
            row["ok"] = False
            row["error"] = f"rss_parse:{type(exc).__name__}:{exc}"
        health.append(row)
    return candidates, health


_original_search_discovery = base.search_discovery


def search_discovery_without_pdds():
    candidates, health = _original_search_discovery()
    # Jina Search can reject unauthenticated requests. Fall back to a separate
    # public web index so discovery remains useful while preserving the exact
    # same canonical-direct publication boundary.
    if not any(row.get("ok") for row in health):
        fallback_candidates, fallback_health = bing_rss_discovery()
        candidates.extend(fallback_candidates)
        health.extend(fallback_health)

    filtered = []
    excluded_pdds = 0
    for candidate in candidates:
        url = base.canonicalize(candidate.get("url", ""))
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "mfe.gov.ro" and parsed.path.startswith("/pdds/"):
            excluded_pdds += 1
            continue
        filtered.append(candidate)
    for row in health:
        row["publicationPolicy"] = "discovery-only; canonical direct fetch required"
        row["pddsDiscoveryPolicy"] = "PDDS candidates must originate from the explicit priority seed crawl"
        row["excludedPddsSearchCandidates"] = int(row.get("excludedPddsSearchCandidates") or 0) + excluded_pdds
    return filtered, health


_original_make_item = base.make_item


def make_direct_item(candidate: dict, cache: dict):
    item, health = _original_make_item(candidate, cache)
    if item:
        transport = str(health.get("transport") or "")
        if not transport.startswith("direct"):
            return None, {
                **health,
                "ok": False,
                "error": "non_direct_publication_transport_rejected",
                "policy": "direct-official-bytes-required-for-publication",
            }
        item["verification"] = "CANONICAL_OFFICIAL_FETCH"
        item["tier"] = "T1"
        item["retrievalTransport"] = transport
    return item, health


# Patch the resilient discovery engine at the factual-publication boundary.
base.fetch_document = direct_only_fetch_document
base.previous_item_useful = preserve_only_directly_verified
base.search_discovery = search_discovery_without_pdds
base.make_item = make_direct_item

if __name__ == "__main__":
    raise SystemExit(base.main())
