#!/usr/bin/env python3
"""Regression contract for crawlable PARTENER.EU public information architecture."""
from __future__ import annotations

import importlib.util
import json
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

# Cross-surface semantic reconciliation: an authoritative CONFIRMED status
# that disagrees with the stale OPEN field must not survive static rendering.
# Nor may a later top-level cutoff overrule the confirmed Termen fact.
semantic_clock = module.parse_date("2026-11-10T00:25:00Z")
assert semantic_clock is not None
future_open = json.loads(json.dumps(expired_open_probe))
for row in future_open["quickFacts"]:
    if row["label"] == "Termen":
        row["value"] = "2026-11-20T23:59:00+02:00"
assert module.current_open(future_open, semantic_clock)
confirmed_closed = json.loads(json.dumps(future_open))
for row in confirmed_closed["quickFacts"]:
    if row["label"] == "Status":
        row["value"] = "CLOSED"
assert not module.current_open(confirmed_closed, semantic_clock)
assert module.fail_closed_render_dossier(confirmed_closed, semantic_clock)["status"] == "REVIEW"
confirmed_review = json.loads(json.dumps(future_open))
for row in confirmed_review["quickFacts"]:
    if row["label"] == "Status":
        row["value"] = "REVIEW"
assert not module.current_open(confirmed_review, semantic_clock)
confirmed_ro_open = json.loads(json.dumps(future_open))
for row in confirmed_ro_open["quickFacts"]:
    if row["label"] == "Status":
        row["value"] = "DESCHIS"
assert module.current_open(confirmed_ro_open, semantic_clock)
conflicting_deadline = json.loads(json.dumps(future_open))
conflicting_deadline["deadline"] = "2026-12-02T23:59:00+02:00"
assert not module.current_open(conflicting_deadline, semantic_clock)
assert module.fail_closed_render_dossier(conflicting_deadline, semantic_clock)["status"] == "REVIEW"
invalid_deadline = json.loads(json.dumps(future_open))
invalid_deadline["closesAt"] = "ora imposibilă"
assert not module.current_open(invalid_deadline, semantic_clock)
matching_deadline = json.loads(json.dumps(future_open))
matching_deadline["deadline"] = "2026-11-20T23:59:00+02:00"
assert module.current_open(matching_deadline, semantic_clock)

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
# A future confirmed Termen does not override a conflicting confirmed Status
# or a conflicting top-level deadline: all such observations render REVIEW.
for contradicting_status in ("OPEN", "CLOSED", "REVIEW", "EXPECTED"):
    probe = json.loads(json.dumps(current_consultation))
    probe["quickFacts"][0]["value"] = contradicting_status
    assert module.current_consultation(probe, consultation_clock) is False, contradicting_status
    assert module.requires_consultation_refresh(probe, consultation_clock) is True
    assert module.fail_closed_render_dossier(probe, consultation_clock)["status"] == "REVIEW"

for inconsistent_field, inconsistent_value in (
    ("deadline", "2026-09-30T23:59:59+03:00"),
    ("closesAt", "neconfirmat"),
    ("closeAt", "2026-09-27T23:59:59+03:00"),
):
    probe = json.loads(json.dumps(current_consultation))
    probe[inconsistent_field] = inconsistent_value
    assert module.current_consultation(probe, consultation_clock) is False, inconsistent_field
    assert module.fail_closed_render_dossier(probe, consultation_clock)["status"] == "REVIEW"

matching_consultation = json.loads(json.dumps(current_consultation))
matching_consultation["deadline"] = "2026-09-29T23:59:59+03:00"
assert module.current_consultation(matching_consultation, consultation_clock) is True
romanian_consultation = json.loads(json.dumps(matching_consultation))
romanian_consultation["quickFacts"][0]["value"] = "ÎN CONSULTARE"
assert module.current_consultation(romanian_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(expired_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(unknown_consultation, consultation_clock) is True
assert module.requires_consultation_refresh(current_consultation, consultation_clock) is False
assert module.fail_closed_render_dossier(expired_consultation, consultation_clock)["status"] == "REVIEW"
assert module.fail_closed_render_dossier(unknown_consultation, consultation_clock)["status"] == "REVIEW"
assert module.fail_closed_render_dossier(current_consultation, consultation_clock)["status"] == "PUBLIC_CONSULTATION"

# Missing timezone offsets cannot authorize material OPEN/CONSULTATION.
# Datetime.fromisoformat accepts zoneless ISO by default; treating an
# unknown local cutoff as UTC would overstate freshness around midnight.
assert module.parse_date("2026-11-11T00:00:00") is None
assert module.parse_date("2026-11-11 00:00:00") is None
assert module.parse_date("2026-11-11T00:00:00+02:00") == module.parse_date("2026-11-10T22:00:00Z")
# Exact Romanian local-time regression: static pages must use the official
# local hour, not a made-up end-of-day (fold() used to erase colons).
assert module.parse_date("6 noiembrie 2026, ora 12:00") == module.parse_date("2026-11-06T10:00:00Z")
assert module.parse_date("6 noiembrie 2026, la ora 12.00") == module.parse_date("2026-11-06T10:00:00Z")
assert module.parse_date("1 iulie 2026, ora 12:00") == module.parse_date("2026-07-01T09:00:00Z")
assert module.parse_date("30 octombrie 2026, ora 16:00") == module.parse_date("2026-10-30T14:00:00Z")
assert module.parse_date("6 noiembrie 2026, ora necunoscută") is None
assert module.parse_date("29 martie 2026, ora 03:30") is None  # nonexistent local hour
assert module.parse_date("25 octombrie 2026, ora 03:30") is None  # ambiguous local hour
assert module.parse_date("31 februarie 2026, ora 12:00") is None

def timed_open_probe(deadline):
    return {
        "id": "ro-local-hour-probe",
        "title": "Local-hour cutoff",
        "programme": "TEST",
        "publicationState": "PUBLISHABLE",
        "status": "OPEN",
        "quickFacts": [
            {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": deadline, "confidence": "CONFIRMED"},
        ],
    }

# The same source timing must be explicit in ISO. A zoneless timestamp
# cannot silently default to UTC and keep an OPEN call actionable.
zoneless_cutoff = timed_open_probe("2026-11-11T00:00:00")
aware_cutoff = timed_open_probe("2026-11-11T00:00:00+02:00")
assert not module.current_open(zoneless_cutoff, module.parse_date("2026-11-10T21:59:59Z"))
assert module.current_open(aware_cutoff, module.parse_date("2026-11-10T21:59:59Z"))
assert not module.current_open(aware_cutoff, module.parse_date("2026-11-10T22:00:01Z"))
ro_cutoff = timed_open_probe("6 noiembrie 2026, ora 12:00")
assert module.current_open(ro_cutoff, module.parse_date("2026-11-06T09:59:59Z")) is True
assert module.current_open(ro_cutoff, module.parse_date("2026-11-06T10:00:01Z")) is False
assert module.fail_closed_render_dossier(
    ro_cutoff, module.parse_date("2026-11-06T10:00:01Z")
)["status"] == "REVIEW"
# The same clock rule must hold for consultation surfaces, not just OPEN calls.
ro_consultation = consultation_probe("6 noiembrie 2026, ora 12:00")
assert module.current_consultation(
    ro_consultation, module.parse_date("2026-11-06T09:59:59Z")
) is True
assert module.current_consultation(
    ro_consultation, module.parse_date("2026-11-06T10:00:01Z")
) is False

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
    # Capture one aware wall clock for both generation and test assertions.
    # The product's generatedAt is provenance, not the current time.
    render_clock = module.dt.datetime.now(module.dt.timezone.utc)
    manifest = module.build(PRODUCTS, out, evaluated_at=render_clock)

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
    clock = render_clock
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

# Verify the exact production failure mode with a deterministic replay:
# older canonical generatedAt, an OPEN call whose official cutoff was Nov 6,
# and a Nov 10 render. The new page must quarantine it without inventing CLOSED.
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    replay_input = json.loads(json.dumps(payload))
    replay_input["generatedAt"] = "2026-11-03T20:33:50Z"
    stale_call = json.loads(json.dumps(expired_open_probe))
    stale_call["id"] = "static-expiry-clock-regression"
    stale_call["title"] = "Stale source timestamp should not extend OPEN"
    for item in stale_call["quickFacts"]:
        if item["label"] == "Termen":
            item["value"] = "2026-11-06T12:00:00+02:00"
    replay_input["dossiers"].append(stale_call)
    input_file = base / "stale-decisions.json"
    input_file.write_text(json.dumps(replay_input, ensure_ascii=False), encoding="utf-8")
    nov5 = module.parse_date("2026-11-05T10:00:00Z")
    nov10 = module.parse_date("2026-11-10T00:25:00Z")
    assert nov5 is not None and nov10 is not None
    before = base / "before"
    after = base / "after"
    before_manifest = module.build(input_file, before, evaluated_at=nov5)
    after_manifest = module.build(input_file, after, evaluated_at=nov10)
    old_open = (before / "finantari/deschise/index.html").read_text(encoding="utf-8")
    new_open = (after / "finantari/deschise/index.html").read_text(encoding="utf-8")
    marker = 'data-dossier-id="static-expiry-clock-regression"'
    assert marker in old_open, "pre-cutoff official OPEN must remain discoverable"
    assert marker not in new_open, "stale generatedAt cannot extend expired OPEN"
    assert after_manifest["currentOpen"] < before_manifest["currentOpen"]
    assert after_manifest["failClosedOpenRefresh"] > before_manifest["failClosedOpenRefresh"]
    dossier_page = (after / "dosare/index.html").read_text(encoding="utf-8")
    assert marker in dossier_page, "expired dossier must remain queryable for history"
    assert "ÎN VERIFICARE" in dossier_page, "expiry alone may only assert REVIEW"
    assert after_manifest["generatedAt"] == replay_input["generatedAt"], (
        "source-generated timestamp must remain unchanged as provenance"
    )

print("PASS public static IA / sitemap / dossier regression")
