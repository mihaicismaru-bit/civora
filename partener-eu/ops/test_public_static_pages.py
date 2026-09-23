#!/usr/bin/env python3
"""Regression contract for crawlable PARTENER.EU public information architecture."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ops" / "build_public_static_pages.py"
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"

spec = importlib.util.spec_from_file_location("build_public_static_pages", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
publishable = [
    row
    for row in (payload.get("dossiers") or [])
    if row.get("publicationState") == "PUBLISHABLE"
]
provisional_ids = {
    str(row.get("id") or "")
    for row in (payload.get("dossiers") or [])
    if row.get("publicationState") != "PUBLISHABLE"
}

with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    manifest = module.build(PRODUCTS, out)

    required = [
        "robots.txt",
        "sitemap.xml",
        "static-public-manifest.json",
        "finantari/index.html",
        "finantari/deschise/index.html",
        "finantari/in-pregatire/index.html",
        "consultari/index.html",
        "dosare/index.html",
        "schimbari/index.html",
    ]
    for relative in required:
        path = out / relative
        assert path.exists(), f"missing generated public IA file: {relative}"
        assert path.stat().st_size > 0, f"empty generated public IA file: {relative}"

    robots = (out / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://partener.eu/sitemap.xml" in robots

    tree = ET.parse(out / "sitemap.xml")
    root = tree.getroot()
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [
        node.text
        for node in root.findall("s:url/s:loc", namespace)
        if node.text
    ]
    assert urls, "sitemap has no URLs"
    assert len(urls) == len(set(urls)), "sitemap contains duplicate URLs"
    assert len(urls) <= 50_000, "sitemap exceeds single-file URL limit"
    for url in urls:
        assert url.startswith("https://partener.eu/"), url
        assert "?" not in url and "#" not in url, f"query/fragment leaked into sitemap: {url}"

    for required_url in (
        "https://partener.eu/",
        "https://partener.eu/finantari/",
        "https://partener.eu/finantari/deschise/",
        "https://partener.eu/finantari/in-pregatire/",
        "https://partener.eu/consultari/",
        "https://partener.eu/dosare/",
        "https://partener.eu/schimbari/",
    ):
        assert required_url in urls, f"missing sitemap hub: {required_url}"

    dossier_files = list((out / "dosare").glob("*/index.html"))
    assert len(dossier_files) == len(publishable), (
        len(dossier_files),
        len(publishable),
    )
    assert manifest["publishableDossiers"] == len(publishable)
    assert manifest["sitemapUrls"] == len(urls)
    assert manifest["policy"]["materialFactsInvented"] is False
    assert manifest["policy"]["provisionalFailClosedIndexed"] is False
    assert manifest["policy"]["queryPagesInSitemap"] is False
    assert manifest["policy"]["openRequiresConfirmedCurrentDeadline"] is True

    dossier_index = (out / "dosare/index.html").read_text(encoding="utf-8")
    funding_index = (out / "finantari/index.html").read_text(encoding="utf-8")
    open_index = (out / "finantari/deschise/index.html").read_text(encoding="utf-8")
    prepare_index = (out / "finantari/in-pregatire/index.html").read_text(encoding="utf-8")
    consultation_index = (out / "consultari/index.html").read_text(encoding="utf-8")

    for content in (dossier_index, funding_index, open_index, prepare_index, consultation_index):
        assert '<a class="skipLink" href="#continut">' in content
        assert '<nav aria-label="Navigație principală">' in content
        assert '<main id="continut"' in content
        assert '<link rel="canonical"' in content
        assert '<meta name="robots" content="index,follow,max-image-preview:large">' in content
        assert 'href="/finantari/"' in content
        assert 'href="/dosare/"' in content
        assert 'href="/schimbari/"' in content

    # The catalogue must support a natural-language entry point without creating
    # indexable search-result URLs.
    assert 'name="q"' in funding_index
    assert 'action="/"' in funding_index
    for profile in ("Firmă / IMM", "ONG", "Primărie", "Agricultură", "Educație"):
        assert profile in funding_index

    # Every generated dossier page has one canonical URL, visible breadcrumb,
    # structured breadcrumb and a source/provenance section.
    for path in dossier_files:
        content = path.read_text(encoding="utf-8")
        assert '<nav class="breadcrumbs" aria-label="Breadcrumb">' in content
        assert '"@type":"BreadcrumbList"' in content
        assert "<h1>" in content
        assert "Surse și proveniență" in content
        assert "Completitudinea nu este probabilitate de aprobare." in content
        assert content.count('<link rel="canonical"') == 1

    # Fail-closed objects never become indexable dossier pages.
    for source_id in provisional_ids:
        if not source_id:
            continue
        assert f'data-dossier-id="{source_id}"' not in dossier_index

    # OPEN static hub must contain only rows that pass the same current-open gate
    # used by the canonical decision projection.
    clock = module.parse_date(payload.get("generatedAt"))
    if clock is None:
        raise AssertionError("decision products generatedAt is not parseable")
    expected_open = {
        str(row.get("id") or "")
        for row in publishable
        if module.current_open(row, clock)
    }
    actual_open = {
        str(row.get("id") or "")
        for row in publishable
        if f'data-dossier-id="{row.get("id")}"' in open_index
    }
    assert actual_open == expected_open, {
        "actual": sorted(actual_open),
        "expected": sorted(expected_open),
    }

    for row in publishable:
        status = str(row.get("status") or "")
        marker = f'data-dossier-id="{row.get("id")}"'
        if status == "PUBLIC_CONSULTATION":
            assert marker in consultation_index
            assert marker not in open_index
        if status in module.PREPARE_STATUSES:
            assert marker in prepare_index
            assert marker not in open_index

print("PASS public static IA / sitemap / dossier regression")
