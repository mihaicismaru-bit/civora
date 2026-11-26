#!/usr/bin/env python3
"""Regression contract for crawlable PARTENER.EU public information architecture."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import re
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

# Confirmed call budget is a valid financing summary when grant size is unknown.
budget_probe = {
    "id": "budget-probe", "title": "Budget probe", "programme": "TEST",
    "publicationState": "PUBLISHABLE", "status": "OPEN",
    "quickFacts": [
        {"label": "Grant", "value": "Neconfirmat", "confidence": "UNKNOWN"},
        {"label": "Buget", "value": {"amount": 5_250_000, "currency": "RON", "basis": "FEN_AVAILABLE_CALL_ALLOCATION"}, "confidence": "CONFIRMED"},
    ],
}
assert module.display_value(budget_probe["quickFacts"][1]["value"]) == "5.250.000 RON"
probe_card = module.card(budget_probe, {"budget-probe": "budget-probe"})
assert "Buget apel:</b> 5.250.000 RON" in probe_card
assert "Finanțare:</b> Neconfirmat" not in probe_card
probe_home = module.compact_home_dossier(budget_probe, {"budget-probe": "budget-probe"})
assert any(row.get("label") == "Buget" for row in probe_home.get("quickFacts") or [])

# A static preview must not silently lose verified beneficiary categories.
# DR-12 includes young farmers <=40, sM 6.1 beneficiaries and a distinct
# <=45 category in the official AFIR launch notice (1 October 2026).
# The first two alone incorrectly hide the third group from listing/search.
audience_probe = {
    **budget_probe,
    "id": "three-audiences-probe",
    "audience": [
        "Fermieri până la 40 de ani",
        "Beneficiari submăsura 6.1",
        "Fermieri până la 45 de ani, în condițiile ghidului",
    ],
}
audience_card = module.card(audience_probe, {"three-audiences-probe": "three-audiences-probe"})
assert all(item in audience_card for item in audience_probe["audience"]), "Beneficiary class hidden from public preview"
audience_home = module.compact_home_dossier(
    audience_probe, {"three-audiences-probe": "three-audiences-probe"}
)
assert audience_home["audience"] == audience_probe["audience"], "Beneficiary class hidden from home/search projection"


# Exact regression for the cross-surface truth defect: an OPEN dossier whose
# confirmed deadline is already behind the render clock must never be shown as
# DESCHIS. It is not inferred CLOSED; it is rendered REVIEW until refreshed.
expired_open_probe = {
    "id": "expired-open-probe",
    "title": "Expired OPEN probe",
    "programme": "TEST",
    "publicationState": "PUBLISHABLE",
    "status": "OPEN",
    "statusLabel": "DESCHIS",
    "standfirst": "Sunt confirmate: open; termen 14 august 2026.",
    "decisionLabel": "ACȚIONEAZĂ",
    "decisionAction": "Începe screeningul și planul de depunere.",
    "quickFacts": [
        {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "14 august 2026", "confidence": "CONFIRMED"},
    ],
    "sections": [
        {"title": "Rezumat executiv", "items": ["Stare apel: DESCHIS.", "Închidere: 14 august 2026."]},
        {"title": "Ce trebuie făcut acum", "items": ["Începe screeningul și planul de depunere."]},
    ],
}
probe_clock = module.parse_date("2026-09-23T15:20:00Z")
assert probe_clock is not None
assert module.requires_open_refresh(expired_open_probe, probe_clock) is True
expired_render = module.fail_closed_render_dossier(expired_open_probe, probe_clock)
assert expired_render["status"] == "REVIEW"
assert expired_render["statusLabel"] == "ÎN VERIFICARE"
assert expired_render["decisionLabel"] == "VERIFICĂ STAREA"
assert expired_render["standfirst"] == module.FAIL_CLOSED_OPEN_STANDFIRST
status_fact = module.fact(expired_render, "Status")
assert status_fact and status_fact["value"] == "În verificare"
assert status_fact["confidence"] == "FAIL_CLOSED"
expired_card = module.card(expired_render, {"expired-open-probe": "expired-open-probe"})
assert "status-review" in expired_card
assert "ÎN VERIFICARE" in expired_card
assert "DESCHIS" not in expired_card
assert "Sunt confirmate: open" not in expired_card
assert module.FAIL_CLOSED_OPEN_STANDFIRST in expired_card

# Consultation freshness is fail-closed just like OPEN freshness.
consultation_clock = module.parse_date("2026-09-26T12:00:00Z")
assert consultation_clock is not None
def consultation_probe(deadline, confidence="CONFIRMED"):
    return {
        "id": "consultation-probe",
        "title": "Consultation probe",
        "programme": "TEST",
        "publicationState": "PUBLISHABLE",
        "status": "PUBLIC_CONSULTATION",
        "statusLabel": "ÎN CONSULTARE",
        "quickFacts": [
            {"label": "Status", "value": "PUBLIC_CONSULTATION", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": deadline, "confidence": confidence},
        ],
        "sections": [],
    }

expired_consultation = consultation_probe("8 septembrie 2026")
unknown_consultation = consultation_probe("Neconfirmat", "UNKNOWN")
current_consultation = consultation_probe("29 septembrie 2026")
assert module.current_consultation(expired_consultation, consultation_clock) is False
assert module.current_consultation(unknown_consultation, consultation_clock) is False
assert module.current_consultation(current_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(expired_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(unknown_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(current_consultation, consultation_clock) is False
assert module.fail_closed_render_dossier(expired_consultation, consultation_clock)["status"] == "REVIEW"
assert module.fail_closed_render_dossier(unknown_consultation, consultation_clock)["status"] == "REVIEW"
assert module.fail_closed_render_dossier(current_consultation, consultation_clock)["status"] == "PUBLIC_CONSULTATION"

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

# The public render must evaluate against present time, never the historic
# decision-products generatedAt. Capture the same clock for all assertions.
test_clock = module.dt.datetime.now(module.dt.timezone.utc)
with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    manifest = module.build(PRODUCTS, out, as_of=test_clock)

    required = [
        "robots.txt",
        "sitemap.xml",
        "static-public-manifest.json",
        "home-public-data.js",
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
    assert manifest["policy"]["expiredOrUnverifiedOpenRenderedAsReview"] is True
    assert manifest["homeSnapshotBytes"] < 120_000, manifest["homeSnapshotBytes"]
    assert manifest["homeSnapshotDossiers"] <= 14
    assert manifest["homeSnapshotNews"] <= 8

    home_raw = (out / "home-public-data.js").read_text(encoding="utf-8")
    prefix = "window.PARTENER_HOME_DATA="
    assert home_raw.startswith(prefix) and home_raw.rstrip().endswith(";")
    home = json.loads(home_raw[len(prefix):].strip().removesuffix(";"))
    assert home["policy"]["readOnlyProjection"] is True
    assert home["policy"]["materialFactsInvented"] is False
    assert home["policy"]["expiredOrUnverifiedOpenRenderedAsReview"] is True
    assert home["policy"]["fullDossiersLazyLoaded"] is True
    assert len(home.get("dossiers") or []) == manifest["homeSnapshotDossiers"]
    assert len(home.get("news") or []) == manifest["homeSnapshotNews"]
    for row in home.get("dossiers") or []:
        assert row.get("publicationState") == "PUBLISHABLE"
        assert str(row.get("canonicalPath") or "").startswith("/dosare/")
        for forbidden in ("sections", "sources", "timeline", "sourceLinks", "documents"):
            assert forbidden not in row, (row.get("id"), forbidden)
    assert '"sections":' not in home_raw
    assert '"sources":' not in home_raw
    assert '"timeline":' not in home_raw

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
    clock = test_clock
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

    # The dossier index and detail pages must use the same fail-closed lifecycle
    # gate. This regression caught the 2026-09-23 drift where the OPEN hub was
    # correct but AFIR/PIDS expired dossiers still rendered DESCHIS and ACȚIONEAZĂ.
    expired_open = [
        row
        for row in publishable
        if module.requires_open_refresh(row, clock)
    ]
    assert manifest["failClosedOpenRefresh"] == len(expired_open)
    for row in expired_open:
        dossier_id = str(row.get("id") or "")
        pattern = re.compile(
            rf'<article class="staticCard" data-dossier-id="{re.escape(dossier_id)}">(.*?)</article>',
            re.S,
        )
        match = pattern.search(dossier_index)
        assert match, f"expired OPEN dossier missing from dossier index: {dossier_id}"
        article = match.group(1)
        assert "status-review" in article, dossier_id
        assert "ÎN VERIFICARE" in article, dossier_id
        assert ">DESCHIS<" not in article, dossier_id
        assert "Sunt confirmate: open" not in article, dossier_id
        href_match = re.search(r'<h2><a href="([^"]+)">', article)
        assert href_match, dossier_id
        detail_path = out / href_match.group(1).strip("/") / "index.html"
        detail = detail_path.read_text(encoding="utf-8")
        assert '<span class="status status-review">ÎN VERIFICARE</span>' in detail, dossier_id
        assert '<small>Status</small><b>În verificare</b><span>FAIL_CLOSED</span>' in detail, dossier_id
        assert module.FAIL_CLOSED_OPEN_STANDFIRST in detail, dossier_id
        assert module.FAIL_CLOSED_OPEN_ACTION in detail, dossier_id
        assert ">DESCHIS<" not in detail, dossier_id
        assert "Stare apel: DESCHIS." not in detail, dossier_id
        assert "ACȚIONEAZĂ" not in detail, dossier_id

    for row in publishable:
        status = str(row.get("status") or "")
        marker = f'data-dossier-id="{row.get("id")}"'
        if status == "PUBLIC_CONSULTATION":
            if module.current_consultation(row, clock):
                assert marker in consultation_index
            else:
                assert marker not in consultation_index
            assert marker not in open_index
        if status in module.PREPARE_STATUSES:
            assert marker in prepare_index
            assert marker not in open_index


# P0 #1404 replay: a stale source-generatedAt must not keep a 6 November
# Clustere inovative dossier OPEN on 18 November in the crawler-visible site.
# The second dossier is deliberately synthetic: it proves that this is a
# time-scoped hold, not a blanket suppression of every future valid deadline.
cluster_probe = {
    "id": "pr-centru-clusters-122",
    "code": "PRC/1056/PRC_P1/OP1/RSO1.1/PRC_A4",
    "title": "Clustere inovative",
    "programme": "Programul Regiunea Centru",
    "publicationState": "PUBLISHABLE",
    "status": "OPEN",
    "statusLabel": "DESCHIS",
    "standfirst": "Sunt confirmate: open; termen 6 noiembrie 2026.",
    "decisionLabel": "ACȚIONEAZĂ",
    "decisionAction": "Începe screeningul și planul de depunere.",
    "quickFacts": [
        {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "2026-11-06T12:00:00+02:00", "confidence": "CONFIRMED"},
    ],
    "sections": [
        {"title": "Rezumat executiv", "items": ["Stare apel: OPEN."]},
        {"title": "Decizia rapidă", "items": ["Începe screeningul și planul de depunere."]},
        {"title": "Ce trebuie făcut acum", "items": ["Planifică depunerea pornind de la termenul confirmat: 2026-11-06T12:00:00+02:00."]},
    ],
    "sources": [{"tier": "T1", "label": "ADR Centru", "url": "https://www.regiocentru.ro/actiuni/clustere-inovative-1-2-2/"}],
}
future_probe = {
    "id": "synthetic-future-test-only",
    "title": "Synthetic clock control",
    "programme": "TEST ONLY",
    "publicationState": "PUBLISHABLE",
    "status": "OPEN",
    "quickFacts": [
        {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "2026-12-01T16:00:00+02:00", "confidence": "CONFIRMED"},
    ],
}
stale_source_timestamp = "2026-08-26T04:00:00Z"
replay_payload = {"generatedAt": stale_source_timestamp, "dossiers": [cluster_probe, future_probe], "news": []}
before_expiry = module.parse_date("2026-11-06T09:59:59Z")
after_expiry = module.parse_date("2026-11-18T11:25:00Z")
assert before_expiry and after_expiry
assert module.current_open(cluster_probe, before_expiry) is True
assert module.current_open(cluster_probe, after_expiry) is False

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    fixture = root / "decision_products.json"
    fixture.write_text(json.dumps(replay_payload, ensure_ascii=False), encoding="utf-8")
    before_root = root / "before"
    after_root = root / "after"
    before_manifest = module.build(fixture, before_root, as_of=before_expiry)
    after_manifest = module.build(fixture, after_root, as_of=after_expiry)
    assert before_manifest["currentOpen"] == 2
    assert after_manifest["currentOpen"] == 1
    assert before_manifest["generatedAt"] == after_manifest["generatedAt"] == stale_source_timestamp
    before_list = (before_root / "finantari/deschise/index.html").read_text(encoding="utf-8")
    after_list = (after_root / "finantari/deschise/index.html").read_text(encoding="utf-8")
    assert 'data-dossier-id="pr-centru-clusters-122"' in before_list
    assert 'data-dossier-id="pr-centru-clusters-122"' not in after_list
    assert 'data-dossier-id="synthetic-future-test-only"' in after_list
    after_dossiers = (after_root / "dosare/index.html").read_text(encoding="utf-8")
    match = re.search(r'<article class="staticCard" data-dossier-id="pr-centru-clusters-122">(.*?)</article>', after_dossiers, re.S)
    assert match and "status-review" in match.group(1)
    cluster_pages = [
        p.read_text(encoding="utf-8")
        for p in (after_root / "dosare").glob("*/index.html")
        if "<h1>Clustere inovative</h1>" in p.read_text(encoding="utf-8")
    ]
    assert len(cluster_pages) == 1
    detail = cluster_pages[0]
    assert '<span class="status status-review">ÎN VERIFICARE</span>' in detail
    assert module.FAIL_CLOSED_OPEN_ACTION in detail
    assert "Sunt confirmate: open" not in detail
    # A review badge is insufficient if SEO-visible dossier sections still instruct
    # submission under the already-expired source snapshot. Preserve the historical
    # cutoff as evidence, but remove actionable text from every REVIEW section.
    assert "Stare apel: OPEN." not in detail
    assert "Stare apel: necesită reverificare la sursa oficială." in detail
    assert "Începe screeningul și planul de depunere." not in detail
    assert "Planifică depunerea pornind" not in detail
    assert "2026-11-06T12:00:00+02:00" in detail
    home_js = (after_root / "home-public-data.js").read_text(encoding="utf-8")
    home = json.loads(home_js.removeprefix("window.PARTENER_HOME_DATA=").strip().removesuffix(";"))
    assert home["summary"]["openCount"] == 1
    assert all(row["id"] != "pr-centru-clusters-122" or row["status"] != "OPEN" for row in home["dossiers"])

    # The derived Ask/home projection uses exactly the same wall-clock
    # discipline; write to temp paths only, never to canonical LKG.
    sync_path = ROOT / "partener-eu" / "ingest" / "sync_decision_products_projection.py"
    sync_spec = importlib.util.spec_from_file_location("partener_sync_projection_test", sync_path)
    sync_mod = importlib.util.module_from_spec(sync_spec)
    assert sync_spec and sync_spec.loader
    sync_spec.loader.exec_module(sync_mod)
    old_products, old_out = sync_mod.PRODUCTS, sync_mod.OUT_JS
    try:
        sync_mod.PRODUCTS = fixture
        sync_mod.OUT_JS = root / "decision-products.js"
        assert sync_mod.main(as_of=after_expiry) == 0
    finally:
        sync_mod.PRODUCTS, sync_mod.OUT_JS = old_products, old_out
    synced = json.loads(fixture.read_text(encoding="utf-8"))
    assert synced["generatedAt"] == stale_source_timestamp
    assert synced["summary"]["openCount"] == 1
    assert synced["home"]["openDossierIds"] == ["synthetic-future-test-only"]
    assert next(row for row in synced["dossiers"] if row["id"] == cluster_probe["id"])["status"] == "OPEN", "Historical source status is preserved; current-facing projection is held only"

# Cross-language/clock truth: no fictitious end-of-day or UTC default may
# stretch an exact 12:00 Bucharest cutoff into the afternoon.
assert module.parse_date("6 noiembrie 2026, ora 12:00") == module.parse_date("2026-11-06T10:00:00Z")
assert module.parse_date("1 iulie 2026, ora 12:00") == module.parse_date("2026-07-01T09:00:00Z")
assert module.parse_date("25 octombrie 2026, ora 03:30") is None
assert module.parse_date("29 martie 2026, ora 03:30") is None
assert module.parse_date("2026-11-11T00:00:00") is None
assert module.parse_date("31 februarie 2026, ora 12:00") is None
assert module.current_open({**cluster_probe, "quickFacts": [
    {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
    {"label": "Termen", "value": "6 noiembrie 2026, ora 12:00", "confidence": "CONFIRMED"},
]}, before_expiry)
assert not module.current_open({**cluster_probe, "quickFacts": [
    {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
    {"label": "Termen", "value": "6 noiembrie 2026", "confidence": "CONFIRMED"},
]}, before_expiry)
assert not module.current_open({**cluster_probe, "closesAt": "2026-11-30T16:00:00+02:00"}, before_expiry)
assert not sync_mod.current_open({**cluster_probe, "closesAt": "2026-11-30T16:00:00+02:00"}, before_expiry)
assert sync_mod.parse_date("6 noiembrie 2026, ora 12:00") == module.parse_date("2026-11-06T10:00:00Z")

# Regression: the derived projection previously accepted a dot clock as
# exact, then interpreted it as EOD; it also discarded nonzero seconds.
clock_after_dot = module.parse_date("2026-11-27T11:00:00Z")
clock_before_seconds = module.parse_date("2026-11-27T10:00:15Z")
assert clock_after_dot and clock_before_seconds
for raw, expected in (
    ("27 noiembrie 2026, ora 12.00", "2026-11-27T10:00:00Z"),
    ("27 noiembrie 2026, ora 12:00:30", "2026-11-27T10:00:30Z"),
    ("27 noiembrie 2026, ora 12.00:45", "2026-11-27T10:00:45Z"),
):
    assert sync_mod.parse_date(raw) == module.parse_date(raw) == module.parse_date(expected)
for parser in (module, sync_mod):
    assert parser.parse_date("27 noiembrie 2026, ora 12.00:99") is None
    probe = {
        "id": "synthetic-exact-clock-parity-only",
        "status": "OPEN", "publicationState": "PUBLISHABLE",
        "quickFacts": [
            {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": "27 noiembrie 2026, ora 12.00", "confidence": "CONFIRMED"},
        ],
    }
    assert not parser.current_open(probe, clock_after_dot)
    probe["quickFacts"][1]["value"] = "27 noiembrie 2026, ora 12:00:30"
    assert parser.current_open(probe, clock_before_seconds)
    probe["closesAt"] = "27 noiembrie 2026, ora 12:00:45"
    assert not parser.current_open(probe, clock_before_seconds)

assert not sync_mod.current_open({**cluster_probe, "quickFacts": [
    {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
    {"label": "Termen", "value": "6 noiembrie 2026", "confidence": "CONFIRMED"},
]}, before_expiry)

print("PASS public static IA / sitemap / dossier regression + P0 wall-clock replay")

# P0 #1407 reproducible AFIR Modernisation Fund cutoff regression (TEST ONLY).
# The two official energy sessions share a 20 Nov 2026 23:59 Bucharest end
# as published by AFIR. Source OPEN is historical; once the cutoff passes,
# neither the crawlable list, dossier, nor Ask/home projection can treat it as
# presently open absent a newly acquired/reconciled official extension.
# This is not evidence of exhaustion, closure, or extension.
energy_pre_cutoff = module.parse_date("2026-11-20T21:58:59Z")
energy_exact_cutoff = module.parse_date("2026-11-20T21:59:00Z")
energy_post_cutoff = module.parse_date("2026-11-20T21:59:01Z")
assert all(clock is not None for clock in (energy_pre_cutoff, energy_exact_cutoff, energy_post_cutoff))
assert module.parse_date("20 noiembrie 2026, ora 23:59") == module.parse_date("2026-11-20T21:59:00Z")
energy_probes = []
for energy_id, energy_title in (
    ("afir-fm-public-autoconsum-2026", "Autoconsum entități publice (fixture)"),
    ("afir-fm-public-storage-2026", "Stocare entități publice (fixture)"),
):
    energy_probes.append({
        "id": energy_id,
        "title": energy_title,
        "programme": "Fondul pentru Modernizare / AFIR",
        "publicationState": "PUBLISHABLE",
        "status": "OPEN",
        "statusLabel": "DESCHIS",
        "standfirst": "Sunt confirmate: open; termen 20 noiembrie 2026, 23:59.",
        "decisionLabel": "ACȚIONEAZĂ",
        "decisionAction": "Pregătește depunerea.",
        "quickFacts": [
            {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": "20 noiembrie 2026, 23:59", "confidence": "CONFIRMED"},
        ],
        "sections": [
            {"title": "Rezumat executiv", "items": ["Stare apel: OPEN."]},
            {"title": "Ce trebuie făcut acum", "items": ["Pregătește depunerea."]},
        ],
        "sources": [{"tier": "T1", "label": "AFIR", "url": "https://www.afir.ro/info-la-zi/comunicat-derulare-sesiune-autoconsum-si-stocare-energie-electrica-beneficiari-publici/"}],
    })
    assert module.current_open(energy_probes[-1], energy_pre_cutoff)
    assert not module.current_open(energy_probes[-1], energy_exact_cutoff)
    assert not module.current_open(energy_probes[-1], energy_post_cutoff)
    assert sync_mod.current_open(energy_probes[-1], energy_pre_cutoff)
    assert not sync_mod.current_open(energy_probes[-1], energy_exact_cutoff)
    assert not sync_mod.current_open(energy_probes[-1], energy_post_cutoff)
    # Even before cutoff, conflicting status or competing extension date
    # must not be accepted as a fresh, reconciled OPEN proof.
    contradictory_status = dict(energy_probes[-1], quickFacts=[
        {"label": "Status", "value": "REVIEW", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "20 noiembrie 2026, 23:59", "confidence": "CONFIRMED"},
    ])
    conflicting_extension = dict(energy_probes[-1], closesAt="2026-12-31T23:59:00+02:00")
    assert not module.current_open(contradictory_status, energy_pre_cutoff)
    assert not sync_mod.current_open(contradictory_status, energy_pre_cutoff)
    assert not module.current_open(conflicting_extension, energy_pre_cutoff)
    assert not sync_mod.current_open(conflicting_extension, energy_pre_cutoff)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    fixture = root / "energy-fixture.json"
    fixture.write_text(json.dumps({
        "generatedAt": stale_source_timestamp,
        "dossiers": energy_probes + [future_probe],
        "news": [],
    }, ensure_ascii=False), encoding="utf-8")
    earlier = root / "energy-before"
    exactly = root / "energy-exact-cutoff"
    later = root / "energy-after"
    before_manifest = module.build(fixture, earlier, as_of=energy_pre_cutoff)
    exact_manifest = module.build(fixture, exactly, as_of=energy_exact_cutoff)
    after_manifest = module.build(fixture, later, as_of=energy_post_cutoff)
    assert before_manifest["currentOpen"] == 3
    assert exact_manifest["currentOpen"] == 1
    assert exact_manifest["failClosedOpenRefresh"] == 2
    assert after_manifest["currentOpen"] == 1
    assert after_manifest["failClosedOpenRefresh"] == 2
    before_list = (earlier / "finantari/deschise/index.html").read_text(encoding="utf-8")
    exact_list = (exactly / "finantari/deschise/index.html").read_text(encoding="utf-8")
    after_list = (later / "finantari/deschise/index.html").read_text(encoding="utf-8")
    after_dossiers = (later / "dosare/index.html").read_text(encoding="utf-8")
    for probe in energy_probes:
        marker = f'data-dossier-id="{probe["id"]}"'
        assert marker in before_list
        assert marker not in exact_list
        assert marker not in after_list
        article_match = re.search(rf'<article class="staticCard" {re.escape(marker)}>(.*?)</article>', after_dossiers, re.S)
        assert article_match and "status-review" in article_match.group(1), probe["id"]
        href_match = re.search(r'<h2><a href="([^"]+)">', article_match.group(1))
        assert href_match, probe["id"]
        detail = (later / href_match.group(1).strip("/") / "index.html").read_text(encoding="utf-8")
        assert '<span class="status status-review">ÎN VERIFICARE</span>' in detail
        assert module.FAIL_CLOSED_OPEN_ACTION in detail
        assert "Stare apel: OPEN." not in detail
        assert "Pregătește depunerea." not in detail
        assert "20 noiembrie 2026, 23:59" in detail
    assert 'data-dossier-id="synthetic-future-test-only"' in after_list
    old_products, old_out = sync_mod.PRODUCTS, sync_mod.OUT_JS
    try:
        sync_mod.PRODUCTS = fixture
        sync_mod.OUT_JS = root / "energy-projection.js"
        assert sync_mod.main(as_of=energy_post_cutoff) == 0
    finally:
        sync_mod.PRODUCTS, sync_mod.OUT_JS = old_products, old_out
    verified = json.loads(fixture.read_text(encoding="utf-8"))
    assert verified["summary"]["openCount"] == 1
    assert verified["home"]["openDossierIds"] == ["synthetic-future-test-only"]
    assert all(row["status"] == "OPEN" for row in verified["dossiers"]), "Historical source observations must remain unchanged"

# The Pages readback must reject matching-manifest pages with stale OPEN cards.
# Execute the actual deployment proof's self-test, not a synthetic copy.
readback_test = subprocess.run(
    [sys.executable, str(ROOT / "partener-eu" / "ops" / "prove_public_deploy.py"), "--self-test"],
    capture_output=True, text=True, check=False,
)
assert readback_test.returncode == 0, (readback_test.stdout, readback_test.stderr)
assert "PASS public deploy readback proof self-test" in readback_test.stdout
print("PASS AFIR 20 Nov cutoff dual-dossier list/detail/home/Ask fail-closed replay")


# P0 #1402: the generic DR-12 dossier is NOT a component-specific accepting
# endpoint. AFIR confirmed "alte sectoare" exhausted on 11 Nov; zootehnic
# remains a distinct independently monitored component. Even an exact future
# global deadline is insufficient to present umbrella DR-12 as OPEN.
# This regression is a render-only hold, not an official CLOSED statement.
dr12_aggregate_probe = {
    **future_probe,
    "id": "afir-dr12-2026",
    "title": "DR-12 agregat fara identitate componenta",
    "status": "OPEN",
    "statusLabel": "DESCHIS",
    "standfirst": "Sesiunea DR-12 este deschisă pentru depunere.",
    "decisionLabel": "ACȚIONEAZĂ",
    "decisionAction": "Depunerea este deschisă.",
    "quickFacts": [
        {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "2 decembrie 2026, 16:00", "confidence": "CONFIRMED"},
    ],
    "sections": [
        {"title": "Rezumat executiv", "items": ["Stare apel: OPEN."]},
        {"title": "Ce trebuie făcut acum", "items": ["Depunerea este deschisă."]},
    ],
}
dr12_clock = module.parse_date("2026-11-21T00:00:00Z")
assert dr12_clock is not None
assert not module.current_open(dr12_aggregate_probe, dr12_clock)
assert not sync_mod.current_open(dr12_aggregate_probe, dr12_clock)
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    fixture = root / "dr12-aggregate-only.json"
    fixture.write_text(json.dumps({
        "generatedAt": "2026-11-01T00:00:00Z",
        "dossiers": [dr12_aggregate_probe, future_probe],
        "news": [],
    }, ensure_ascii=False), encoding="utf-8")
    out = root / "site"
    result = module.build(fixture, out, as_of=dr12_clock)
    assert result["currentOpen"] == 1
    assert result["failClosedOpenRefresh"] == 1
    open_html = (out / "finantari/deschise/index.html").read_text(encoding="utf-8")
    assert 'data-dossier-id="afir-dr12-2026"' not in open_html
    dossier_html = (out / "dosare/index.html").read_text(encoding="utf-8")
    dr12_card = re.search(
        r'<article class="staticCard" data-dossier-id="afir-dr12-2026">(.*?)</article>',
        dossier_html, re.S,
    )
    assert dr12_card and "status-review" in dr12_card.group(1)
    href = re.search(r'<h2><a href="([^"]+)">', dr12_card.group(1))
    assert href
    detail = (out / href.group(1).strip("/") / "index.html").read_text(encoding="utf-8")
    assert '<span class="status status-review">ÎN VERIFICARE</span>' in detail
    assert "Stare apel: OPEN." not in detail
    assert "Depunerea este deschisă." not in detail
    assert module.FAIL_CLOSED_OPEN_ACTION in detail
    old_products, old_out = sync_mod.PRODUCTS, sync_mod.OUT_JS
    try:
        sync_mod.PRODUCTS = fixture
        sync_mod.OUT_JS = root / "derived-projection.js"
        assert sync_mod.main(as_of=dr12_clock) == 0
    finally:
        sync_mod.PRODUCTS, sync_mod.OUT_JS = old_products, old_out
    source_preserved = json.loads(fixture.read_text(encoding="utf-8"))
    assert source_preserved["summary"]["openCount"] == 1
    assert source_preserved["home"]["openDossierIds"] == ["synthetic-future-test-only"]
    assert next(d for d in source_preserved["dossiers"] if d["id"] == "afir-dr12-2026")["status"] == "OPEN"
print("PASS DR-12 generic umbrella render/derived projection quarantine; canonical history unchanged")
