#!/usr/bin/env python3
"""Build static, crawlable PARTENER.EU public discovery pages.

Canonical source: partener-eu/ingest/state/decision_products.json.

This renderer never invents material facts:
- only PUBLISHABLE dossiers become indexable detail pages;
- OPEN pages require a confirmed current deadline;
- stale/expired OPEN evidence is rendered fail-closed as REVIEW until refreshed;
- provisional fail-closed objects never enter the sitemap;
- search/filter query states are intentionally excluded from the sitemap.

Generated pages are deployment artifacts, not a second source of truth.
"""
from __future__ import annotations

import copy
import argparse
import datetime as dt
import html
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
DEFAULT_WEB = ROOT / "partener-eu" / "web"
BASE_URL = "https://partener.eu"
RO_TZ = dt.timezone(dt.timedelta(hours=3))
GENERATED_DIRS = ("finantari", "consultari", "dosare", "schimbari")

STATUS_LABELS = {
    "OPEN": "DESCHIS",
    "EXPECTED": "ÎN PREGĂTIRE",
    "ANNOUNCED": "ANUNȚAT",
    "UPCOMING": "ÎN PREGĂTIRE",
    "PREPARE_NOW": "PREGĂTEȘTE",
    "PUBLIC_CONSULTATION": "ÎN CONSULTARE",
    "REVIEW": "ÎN VERIFICARE",
    "CLOSED": "ÎNCHIS",
    "DISCOVERED": "IDENTIFICAT",
}
PREPARE_STATUSES = {"EXPECTED", "ANNOUNCED", "UPCOMING", "PREPARE_NOW"}
FAIL_CLOSED_OPEN_STANDFIRST = (
    "Starea apelului necesită reverificare la sursa oficială. "
    "Termenul publicat în dosar nu mai autorizează prezentarea apelului ca deschis."
)
FAIL_CLOSED_OPEN_ACTION = (
    "Reverifică starea curentă și orice termen nou în sursa oficială înainte de a pregăti sau depune o cerere."
)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def fold(value: Any) -> str:
    text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    )
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(value: Any) -> str:
    text = fold(value).replace(" ", "-").strip("-")
    text = re.sub(r"-+", "-", text)
    return text[:120] or "dosar"


def fact(dossier: dict[str, Any], label: str) -> dict[str, Any] | None:
    wanted = fold(label)
    for row in dossier.get("quickFacts") or []:
        if fold(row.get("label")) == wanted:
            return row
    return None


def display_value(value: Any) -> str:
    if value is None:
        return "Neconfirmat"
    if isinstance(value, bool):
        return "Da" if value else "Nu"
    if isinstance(value, (int, float)):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, dict):
        amount = value.get("amount")
        if amount is not None:
            currency = str(value.get("currency") or "").strip().upper()
            rendered = display_value(amount)
            return rendered + (f" {currency}" if currency else "")
        preferred = (
            ("maximum_total_project_value_eur", "max. ", " EUR"),
            ("maximum_eur", "max. ", " EUR"),
            ("max_eur", "max. ", " EUR"),
            ("minimum_eur", "min. ", " EUR"),
            ("min_eur", "min. ", " EUR"),
        )
        for key, prefix, suffix in preferred:
            if value.get(key) is not None:
                return prefix + display_value(value[key]) + suffix
        return "Neconfirmat"
    if isinstance(value, list):
        rows = [display_value(item) for item in value if item not in (None, "")]
        return " · ".join(rows[:4]) if rows else "Neconfirmat"
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.startswith("{") or text.startswith("["):
        return "Neconfirmat"
    return text


def parse_date(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = fold(raw)
    if any(token in lowered for token in ("neconfirmat", "necunoscut", "unknown")):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        pass

    months = {
        "ianuarie": 1,
        "februarie": 2,
        "martie": 3,
        "aprilie": 4,
        "mai": 5,
        "iunie": 6,
        "iulie": 7,
        "august": 8,
        "septembrie": 9,
        "octombrie": 10,
        "noiembrie": 11,
        "decembrie": 12,
    }
    match = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(months) + r")\s+(20\d{2})(?:\D+(\d{1,2}):(\d{2}))?",
        lowered,
    )
    if not match:
        return None
    return dt.datetime(
        int(match.group(3)),
        months[match.group(2)],
        int(match.group(1)),
        int(match.group(4) or 23),
        int(match.group(5) or 59),
        tzinfo=RO_TZ,
    ).astimezone(dt.timezone.utc)


def current_open(dossier: dict[str, Any], clock: dt.datetime) -> bool:
    if dossier.get("status") != "OPEN" or dossier.get("publicationState") != "PUBLISHABLE":
        return False
    status = fact(dossier, "Status")
    deadline = fact(dossier, "Termen")
    if not status or str(status.get("confidence") or "").upper() != "CONFIRMED":
        return False
    if not deadline or str(deadline.get("confidence") or "").upper() != "CONFIRMED":
        return False
    closes = parse_date(deadline.get("value"))
    return closes is not None and closes >= clock


def requires_open_refresh(dossier: dict[str, Any], clock: dt.datetime) -> bool:
    """Return True when an OPEN dossier cannot be rendered publicly as OPEN now."""
    return (
        dossier.get("publicationState") == "PUBLISHABLE"
        and dossier.get("status") == "OPEN"
        and not current_open(dossier, clock)
    )


def fail_closed_render_dossier(
    dossier: dict[str, Any], clock: dt.datetime
) -> dict[str, Any]:
    """Return a render-only copy that suppresses stale OPEN claims.

    The canonical dossier remains untouched. We do not infer CLOSED from an expired
    deadline: the public static layer moves the lifecycle state to REVIEW and asks
    for a fresh authoritative observation.
    """
    if not requires_open_refresh(dossier, clock):
        return dossier

    rendered = copy.deepcopy(dossier)
    rendered["status"] = "REVIEW"
    rendered["statusLabel"] = STATUS_LABELS["REVIEW"]
    rendered["standfirst"] = FAIL_CLOSED_OPEN_STANDFIRST
    rendered["decisionLabel"] = "VERIFICĂ STAREA"
    rendered["decision"] = "VERIFY"
    rendered["decisionAction"] = FAIL_CLOSED_OPEN_ACTION
    rendered["renderFailClosedReason"] = "OPEN_DEADLINE_EXPIRED_OR_UNVERIFIED_REQUIRES_REFRESH"

    quick_facts = []
    saw_status = False
    for row in rendered.get("quickFacts") or []:
        item = copy.deepcopy(row)
        if fold(item.get("label")) == "status":
            saw_status = True
            item["value"] = "În verificare"
            item["confidence"] = "FAIL_CLOSED"
        quick_facts.append(item)
    if not saw_status:
        quick_facts.insert(
            0,
            {"label": "Status", "value": "În verificare", "confidence": "FAIL_CLOSED"},
        )
    rendered["quickFacts"] = quick_facts

    guarded_sections: list[dict[str, Any]] = []
    for section in rendered.get("sections") or []:
        item = copy.deepcopy(section)
        heading = fold(item.get("title"))
        rows = [str(value).strip() for value in (item.get("items") or []) if str(value).strip()]
        if heading in {"decizia rapida", "ce trebuie facut acum"}:
            rows = [FAIL_CLOSED_OPEN_ACTION]
        elif heading == "rezumat executiv":
            replaced = False
            safe_rows: list[str] = []
            for value in rows:
                if fold(value).startswith("stare apel open"):
                    safe_rows.append("Stare apel: necesită reverificare la sursa oficială.")
                    replaced = True
                else:
                    safe_rows.append(value)
            if not replaced:
                safe_rows.insert(0, "Stare apel: necesită reverificare la sursa oficială.")
            rows = safe_rows
        item["items"] = rows
        guarded_sections.append(item)
    rendered["sections"] = guarded_sections
    return rendered


def safe_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def stable_slug(dossier: dict[str, Any], used: set[str]) -> str:
    base = slugify(dossier.get("slug") or dossier.get("id") or dossier.get("title"))
    value = base
    suffix = 2
    while value in used:
        value = f"{base}-{suffix}"
        suffix += 1
    used.add(value)
    return value


def canonical(path: str) -> str:
    return BASE_URL + path


def json_ld(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def common_nav(current: str = "") -> str:
    items = [
        ("/finantari/", "Finanțări", "finantari"),
        ("/finantari/deschise/", "Deschise acum", "deschise"),
        ("/finantari/in-pregatire/", "În pregătire", "pregatire"),
        ("/consultari/", "Consultări", "consultari"),
        ("/dosare/", "Dosare", "dosare"),
        ("/schimbari/", "Ce s-a schimbat", "schimbari"),
    ]
    links = []
    for href, label, key in items:
        aria = ' aria-current="page"' if current == key else ""
        links.append(f'<a href="{href}"{aria}>{esc(label)}</a>')
    return "".join(links)


def breadcrumbs(items: list[tuple[str, str]]) -> tuple[str, dict[str, Any]]:
    visible: list[str] = []
    structured: list[dict[str, Any]] = []
    for position, (label, href) in enumerate(items, start=1):
        visible.append(f'<a href="{href}">{esc(label)}</a>')
        structured.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": label,
                "item": canonical(href),
            }
        )
    return (
        '<nav class="breadcrumbs" aria-label="Breadcrumb">'
        + "<span> / </span>".join(visible)
        + "</nav>",
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": structured,
        },
    )


def page_shell(
    *,
    title: str,
    description: str,
    path: str,
    body: str,
    current_nav: str = "",
    extra_json_ld: list[dict[str, Any]] | None = None,
) -> str:
    structured = [
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "url": canonical(path),
            "description": description,
            "isPartOf": {
                "@type": "WebSite",
                "name": "PARTENER.EU",
                "url": BASE_URL + "/",
            },
        }
    ]
    structured.extend(extra_json_ld or [])
    scripts = "\n".join(
        f'<script type="application/ld+json">{json_ld(item)}</script>'
        for item in structured
    )
    return f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)} · PARTENER.EU</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <link rel="canonical" href="{esc(canonical(path))}">
  <link rel="preconnect" href="https://fonts.googleapis.com">\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:opsz,wght@8..60,400..800&family=Source+Serif+4:opsz,wght@8..60,600..700&display=swap">\n  <link rel="stylesheet" href="/public-static-v1.css?v=20260923-ux1">\n  <link rel="stylesheet" href="/brand-civic-intelligence-v1.css?v=20260924-brand1">\n  <link rel="icon" type="image/svg+xml" href="/brand-mark-v1.svg?v=20260924-brand1">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="PARTENER.EU">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical(path))}">
  {scripts}
</head>
<body>
<a class="skipLink" href="#continut">Sari la conținut</a>
<header class="staticTopbar">
  <div class="staticNav">
    <a class="staticBrand" href="/" aria-label="PARTENER.EU — Acasă"><img src="/brand-mark-v1.svg?v=20260924-brand1" alt="" aria-hidden="true" width="30" height="30">PARTENER<span>.EU</span></a>
    <nav aria-label="Navigație principală">{common_nav(current_nav)}</nav>
    <a class="staticAsk" href="/?view=ask">Întreabă PARTENER.EU</a>
  </div>
</header>
<main id="continut" class="staticMain">
{body}
</main>
<footer class="staticFooter">
  <div><b>PARTENER.EU</b> · Finanțări explicate pentru decizie, cu sursa oficială.</div>
  <div><a href="/finantari/">Catalog</a> · <a href="/dosare/">Dosare</a> · <a href="/schimbari/">Schimbări</a></div>
</footer>
</body>
</html>
"""


def dossier_href(dossier: dict[str, Any], slug_by_id: dict[str, str]) -> str:
    key = str(dossier.get("id") or "")
    slug = slug_by_id.get(key) or slugify(
        dossier.get("slug") or key or dossier.get("title")
    )
    return f"/dosare/{slug}/"


def status_label(dossier: dict[str, Any]) -> str:
    status = str(dossier.get("status") or "")
    return str(
        dossier.get("statusLabel")
        or STATUS_LABELS.get(status, status or "ÎN VERIFICARE")
    )


def card(dossier: dict[str, Any], slug_by_id: dict[str, str]) -> str:
    deadline = fact(dossier, "Termen")
    finance_candidates = [
        fact(dossier, "Grant"),
        fact(dossier, "Finanțare"),
        fact(dossier, "Valoare proiect"),
        fact(dossier, "Buget"),
    ]
    grant = next(
        (row for row in finance_candidates if row and str(row.get("confidence") or "").upper() == "CONFIRMED"),
        None,
    )
    if grant is None:
        grant = next(
            (row for row in finance_candidates if row and display_value(row.get("value")) != "Neconfirmat"),
            None,
        )
    finance_label = "Buget apel" if grant and fold(grant.get("label")) == "buget" else "Finanțare"
    audience = [str(item) for item in (dossier.get("audience") or []) if item][:2]
    facts_html: list[str] = []
    if grant:
        facts_html.append(
            f"<span><b>{esc(finance_label)}:</b> {esc(display_value(grant.get('value')))}</span>"
        )
    if deadline:
        facts_html.append(
            f"<span><b>Termen:</b> {esc(display_value(deadline.get('value')))}</span>"
        )
    audience_html = (
        f"<p>{esc(' · '.join(audience))}</p>" if audience else ""
    )
    href = dossier_href(dossier, slug_by_id)
    status = str(dossier.get("status") or "").lower()
    return f"""<article class="staticCard" data-dossier-id="{esc(dossier.get('id'))}">
  <div class="staticCardTop"><span class="status status-{esc(status)}">{esc(status_label(dossier))}</span><span>{esc(dossier.get('programme') or '')}</span></div>
  <h2><a href="{href}">{esc(dossier.get('title') or 'Oportunitate de finanțare')}</a></h2>
  <p class="standfirst">{esc(dossier.get('standfirst') or dossier.get('decisionAction') or '')}</p>
  <div class="cardFacts">{''.join(facts_html)}</div>
  {audience_html}
  <a class="cardAction" href="{href}">Deschide dosarul →</a>
</article>"""


def quick_count(label: str, value: int, href: str) -> str:
    return (
        f'<a class="metric" href="{href}"><b>{value}</b>'
        f"<span>{esc(label)}</span></a>"
    )


def search_form() -> str:
    return """<form class="staticSearch" action="/" method="get" role="search">
  <label for="q">Descrie ce vrei să finanțezi</label>
  <div><input id="q" name="q" type="search" placeholder="ex. utilaje pentru o firmă din Vâlcea"><button type="submit">Găsește finanțări</button></div>
</form>"""


def write_page(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def meaningful_lastmod(value: Any) -> str | None:
    parsed = parse_date(value)
    return parsed.date().isoformat() if parsed else None


def latest_lastmod(rows: list[dict[str, Any]], key: str) -> str | None:
    values = [meaningful_lastmod(row.get(key)) for row in rows]
    values = [value for value in values if value]
    return max(values) if values else None


HOME_FACT_LABELS = {
    "status",
    "termen",
    "grant",
    "finantare",
    "valoare proiect",
    "buget",
}


def compact_home_dossier(
    dossier: dict[str, Any],
    slug_by_id: dict[str, str],
) -> dict[str, Any]:
    quick = [
        row
        for row in (dossier.get("quickFacts") or [])
        if fold(row.get("label")) in HOME_FACT_LABELS
    ]
    return {
        "id": dossier.get("id"),
        "title": dossier.get("title"),
        "programme": dossier.get("programme"),
        "region": dossier.get("region"),
        "status": dossier.get("status"),
        "statusLabel": dossier.get("statusLabel"),
        "publicationState": dossier.get("publicationState"),
        "standfirst": dossier.get("standfirst"),
        "decisionAction": dossier.get("decisionAction"),
        "audience": list(dossier.get("audience") or [])[:2],
        "quickFacts": quick,
        "quality": {
            "completeness": int(
                (dossier.get("quality") or {}).get("completeness") or 0
            )
        },
        "canonicalPath": dossier_href(dossier, slug_by_id),
    }


def compact_home_news(
    item: dict[str, Any],
    publishable_by_id: dict[str, dict[str, Any]],
    slug_by_id: dict[str, str],
) -> dict[str, Any]:
    dossier_id = str(item.get("dossierId") or "")
    dossier = publishable_by_id.get(dossier_id)
    return {
        "id": item.get("id"),
        "date": item.get("date"),
        "kind": item.get("kind"),
        "programme": item.get("programme"),
        "headline": item.get("headline"),
        "standfirst": item.get("standfirst"),
        "meaning": item.get("meaning"),
        "utilityScore": item.get("utilityScore"),
        "dossierId": item.get("dossierId"),
        "canonicalPath": (
            dossier_href(dossier, slug_by_id) if dossier else "/schimbari/"
        ),
    }


def build(
    products_path: Path = DEFAULT_PRODUCTS,
    web_root: Path = DEFAULT_WEB,
) -> dict[str, Any]:
    payload = json.loads(products_path.read_text(encoding="utf-8"))
    dossiers = payload.get("dossiers") or []
    news = payload.get("news") or []
    generated = parse_date(payload.get("generatedAt")) or dt.datetime.now(dt.timezone.utc)

    for dirname in GENERATED_DIRS:
        shutil.rmtree(web_root / dirname, ignore_errors=True)

    source_publishable = [
        row for row in dossiers if row.get("publicationState") == "PUBLISHABLE"
    ]
    fail_closed_open_refresh_count = sum(
        1 for row in source_publishable if requires_open_refresh(row, generated)
    )
    publishable = [
        fail_closed_render_dossier(row, generated) for row in source_publishable
    ]
    used: set[str] = set()
    slug_by_id: dict[str, str] = {}
    for dossier in publishable:
        key = str(dossier.get("id") or "")
        slug_by_id[key] = stable_slug(dossier, used)

    open_rows = [
        row for row in publishable if current_open(row, generated)
    ]
    prepare_rows = [
        row
        for row in publishable
        if str(row.get("status") or "") in PREPARE_STATUSES
    ]
    consultation_rows = [
        row
        for row in publishable
        if row.get("status") == "PUBLIC_CONSULTATION"
    ]
    closed_rows = [row for row in publishable if row.get("status") == "CLOSED"]

    rank = {
        "OPEN": 0,
        "PUBLIC_CONSULTATION": 1,
        "EXPECTED": 2,
        "ANNOUNCED": 2,
        "UPCOMING": 2,
        "PREPARE_NOW": 2,
        "REVIEW": 4,
        "CLOSED": 9,
    }
    publishable.sort(
        key=lambda row: (
            rank.get(str(row.get("status") or ""), 5),
            -int((row.get("quality") or {}).get("completeness") or 0),
            str(row.get("title") or ""),
        )
    )
    max_dt = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    open_rows.sort(
        key=lambda row: (
            parse_date((fact(row, "Termen") or {}).get("value")) or max_dt,
            str(row.get("title") or ""),
        )
    )
    prepare_rows.sort(
        key=lambda row: (
            -int((row.get("quality") or {}).get("completeness") or 0),
            str(row.get("title") or ""),
        )
    )
    consultation_rows.sort(
        key=lambda row: (
            -int((row.get("quality") or {}).get("completeness") or 0),
            str(row.get("title") or ""),
        )
    )

    publishable_by_id = {
        str(row.get("id") or ""): row for row in publishable
    }
    snapshot_rows: list[dict[str, Any]] = []
    snapshot_seen: set[str] = set()
    for row in [*open_rows[:6], *prepare_rows[:4], *consultation_rows[:4]]:
        key = str(row.get("id") or "")
        if not key or key in snapshot_seen:
            continue
        snapshot_seen.add(key)
        snapshot_rows.append(compact_home_dossier(row, slug_by_id))

    visible_home_news: list[dict[str, Any]] = []
    for item in news:
        event_date = parse_date(item.get("date"))
        if event_date and event_date > generated + dt.timedelta(minutes=5):
            continue
        if int(item.get("utilityScore") or 0) < 60:
            continue
        visible_home_news.append(item)
    visible_home_news.sort(
        key=lambda row: (
            -int(row.get("utilityScore") or 0),
            str(row.get("date") or ""),
        )
    )
    home_payload = {
        "schemaVersion": 1,
        "generatedAt": payload.get("generatedAt"),
        "summary": {
            "dossierCount": len(publishable),
            "openCount": len(open_rows),
            "prepareCount": len(prepare_rows),
            "consultationCount": len(consultation_rows),
            "newsCount": len(news),
        },
        "dossiers": snapshot_rows,
        "news": [
            compact_home_news(item, publishable_by_id, slug_by_id)
            for item in visible_home_news[:8]
        ],
        "policy": {
            "readOnlyProjection": True,
            "materialFactsInvented": False,
            "openRequiresConfirmedCurrentDeadline": True,
            "expiredOrUnverifiedOpenRenderedAsReview": True,
            "fullDossiersLazyLoaded": True,
        },
    }
    home_js = (
        "window.PARTENER_HOME_DATA="
        + json.dumps(home_payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    home_path = write_page(web_root, "home-public-data.js", home_js)
    home_snapshot_bytes = home_path.stat().st_size

    catalogue_body = f"""
<section class="staticHero">
  <div class="eyebrow">Catalog verificabil de finanțări</div>
  <h1>Găsește finanțarea potrivită fără să pornești de la acronime.</h1>
  <p>Începe cu investiția și profilul tău. PARTENER.EU separă apelurile deschise de pregătire și consultare și păstrează sursa oficială în fiecare dosar.</p>
  {search_form()}
  <div class="profileHints"><span>Potrivit pentru:</span><b>Firmă / IMM</b><b>ONG</b><b>Primărie</b><b>Agricultură</b><b>Educație</b></div>
</section>
<section class="metrics">
  {quick_count("deschise acum", len(open_rows), "/finantari/deschise/")}
  {quick_count("în pregătire", len(prepare_rows), "/finantari/in-pregatire/")}
  {quick_count("în consultare", len(consultation_rows), "/consultari/")}
  {quick_count("dosare publice", len(publishable), "/dosare/")}
</section>
<section class="staticSection">
  <div class="sectionHead"><div><span>Deschise acum</span><h2>Finanțări cu stare și termen confirmate</h2></div><a href="/finantari/deschise/">Vezi toate →</a></div>
  <div class="staticGrid">{''.join(card(row, slug_by_id) for row in open_rows[:6]) or '<div class="empty">Nu există apeluri OPEN care trec gate-ul curent.</div>'}</div>
</section>
<section class="staticSection">
  <div class="sectionHead"><div><span>Planificare</span><h2>În pregătire și în consultare</h2></div><a href="/finantari/in-pregatire/">Vezi ce urmează →</a></div>
  <div class="staticGrid">{''.join(card(row, slug_by_id) for row in (prepare_rows + consultation_rows)[:6]) or '<div class="empty">Nu există oportunități suficient de clare pentru această secțiune.</div>'}</div>
</section>
"""
    write_page(
        web_root,
        "finantari/index.html",
        page_shell(
            title="Finanțări europene — catalog complet",
            description=(
                "Catalog PARTENER.EU cu finanțări deschise, în pregătire și "
                "în consultare, legate de dosare și surse oficiale."
            ),
            path="/finantari/",
            body=catalogue_body,
            current_nav="finantari",
        ),
    )

    def hub(
        *,
        title: str,
        description: str,
        path: str,
        rows: list[dict[str, Any]],
        current_nav: str,
        eyebrow: str,
    ) -> str:
        body = f"""
<section class="staticHero compact">
  <div class="eyebrow">{esc(eyebrow)}</div>
  <h1>{esc(title)}</h1>
  <p>{esc(description)}</p>
  {search_form()}
</section>
<section class="staticSection">
  <div class="resultSummary"><b>{len(rows)}</b> rezultate în proiecția publică verificată.</div>
  <div class="staticGrid">{''.join(card(row, slug_by_id) for row in rows) or '<div class="empty">Nu există rezultate care trec gate-ul curent.</div>'}</div>
</section>"""
        return page_shell(
            title=title,
            description=description,
            path=path,
            body=body,
            current_nav=current_nav,
        )

    write_page(
        web_root,
        "finantari/deschise/index.html",
        hub(
            title="Finanțări deschise acum",
            description=(
                "Doar apeluri PUBLISHABLE cu stare OPEN și termen curent "
                "confirmate din sursa oficială."
            ),
            path="/finantari/deschise/",
            rows=open_rows,
            current_nav="deschise",
            eyebrow="Poți acționa acum",
        ),
    )
    write_page(
        web_root,
        "finantari/in-pregatire/index.html",
        hub(
            title="Finanțări în pregătire",
            description=(
                "Oportunități anunțate sau așteptate care merită pregătite, "
                "fără a fi prezentate ca apeluri deschise."
            ),
            path="/finantari/in-pregatire/",
            rows=prepare_rows,
            current_nav="pregatire",
            eyebrow="Pregătește din timp",
        ),
    )
    write_page(
        web_root,
        "consultari/index.html",
        hub(
            title="Ghiduri și apeluri în consultare",
            description=(
                "Consultările sunt separate explicit de sesiunile de depunere. "
                "Condițiile se pot modifica până la forma finală."
            ),
            path="/consultari/",
            rows=consultation_rows,
            current_nav="consultari",
            eyebrow="Condiții încă în lucru",
        ),
    )

    dossiers_body = f"""
<section class="staticHero compact">
  <div class="eyebrow">Dosare verificabile</div>
  <h1>Dosare de finanțare</h1>
  <p>Fiecare dosar reunește statutul, termenul, eligibilitatea, finanțarea, documentele, riscurile, necunoscutele și sursele disponibile.</p>
  {search_form()}
</section>
<section class="staticSection">
  <div class="resultSummary"><b>{len(publishable)}</b> dosare PUBLISHABLE. Închise: {len(closed_rows)}. În reverificare după expirarea/lipsa dovezii OPEN: {fail_closed_open_refresh_count}.</div>
  <div class="staticGrid">{''.join(card(row, slug_by_id) for row in publishable) or '<div class="empty">Nu există dosare publicabile.</div>'}</div>
</section>
"""
    write_page(
        web_root,
        "dosare/index.html",
        page_shell(
            title="Dosare de finanțare",
            description=(
                "Dosare PARTENER.EU cu fapte confirmate, necunoscute explicite "
                "și surse oficiale."
            ),
            path="/dosare/",
            body=dossiers_body,
            current_nav="dosare",
        ),
    )

    for dossier in publishable:
        href = dossier_href(dossier, slug_by_id)
        crumb_html, crumb_ld = breadcrumbs(
            [
                ("Finanțări", "/finantari/"),
                ("Dosare", "/dosare/"),
                (str(dossier.get("title") or "Dosar"), href),
            ]
        )

        quick_facts = []
        for row in dossier.get("quickFacts") or []:
            quick_facts.append(
                '<div class="detailFact">'
                f"<small>{esc(row.get('label') or '')}</small>"
                f"<b>{esc(display_value(row.get('value')))}</b>"
                f"<span>{esc(row.get('confidence') or '')}</span>"
                "</div>"
            )

        sections = []
        for section in dossier.get("sections") or []:
            heading = str(section.get("title") or "").strip()
            items = [
                str(item).strip()
                for item in (section.get("items") or [])
                if str(item).strip()
            ]
            if not heading or not items:
                continue
            sections.append(
                f'<section class="detailSection"><h2>{esc(heading)}</h2><ul>'
                + "".join(f"<li>{esc(item)}</li>" for item in items)
                + "</ul></section>"
            )

        sources = []
        for raw in dossier.get("sources") or []:
            source = {"url": raw} if isinstance(raw, str) else (raw or {})
            url = safe_url(source.get("url"))
            if not url:
                continue
            official = str(source.get("tier") or "").upper().startswith("T1")
            label = source.get("label") or (
                "Sursă oficială" if official else "Evidență publică"
            )
            meta = " · ".join(
                item
                for item in [
                    str(source.get("tier") or ""),
                    str(source.get("observedAt") or ""),
                ]
                if item
            )
            sources.append(
                f'<a class="sourceRow" href="{esc(url)}" target="_blank" rel="noreferrer">'
                f"<span><b>{esc(label)}</b><small>{esc(meta)}</small></span>"
                "<strong>Deschide sursa ↗</strong></a>"
            )

        quality = dossier.get("quality") or {}
        description = str(
            dossier.get("standfirst")
            or dossier.get("decisionAction")
            or f"Dosar de finanțare {dossier.get('title') or ''}"
        )[:300]
        detail_body = f"""
{crumb_html}
<article>
<header class="detailHero">
  <div class="detailMeta"><span class="status status-{esc(str(dossier.get('status') or '').lower())}">{esc(status_label(dossier))}</span><span>{esc(dossier.get('programme') or '')}</span><span>{esc(dossier.get('region') or '')}</span></div>
  <h1>{esc(dossier.get('title') or 'Dosar de finanțare')}</h1>
  <p>{esc(dossier.get('standfirst') or dossier.get('decisionAction') or '')}</p>
  <div class="detailFacts">{''.join(quick_facts)}</div>
</header>
<div class="detailLayout">
  <div>{''.join(sections) or '<div class="empty">Detaliile sunt încă în structurare.</div>'}</div>
  <aside>
    <div class="decisionBox"><small>Ce trebuie făcut acum</small><strong>{esc(dossier.get('decisionLabel') or dossier.get('decision') or 'VERIFICĂ')}</strong><p>{esc(dossier.get('decisionAction') or 'Verifică dosarul și sursa oficială înainte de a acționa.')}</p></div>
    <div class="qualityBox"><b>Calitatea dosarului</b><span>Completitudine: {esc(quality.get('completeness') or 0)}%</span><span>{esc(quality.get('dossierLevel') or '')}</span><small>Completitudinea nu este probabilitate de aprobare.</small></div>
    <div class="sourcesBox"><h2>Surse și proveniență</h2>{''.join(sources) or '<p>Sursa nu este încă atașată public.</p>'}</div>
  </aside>
</div>
</article>
"""
        write_page(
            web_root,
            href.strip("/") + "/index.html",
            page_shell(
                title=str(dossier.get("title") or "Dosar de finanțare"),
                description=description,
                path=href,
                body=detail_body,
                current_nav="dosare",
                extra_json_ld=[crumb_ld],
            ),
        )

    news_rows: list[str] = []
    visible_news: list[dict[str, Any]] = []
    for item in news:
        event_date = parse_date(item.get("date"))
        if event_date and event_date > generated + dt.timedelta(minutes=5):
            continue
        visible_news.append(item)
        headline = str(item.get("headline") or "Actualizare")
        meaning = str(item.get("meaning") or item.get("standfirst") or "")

        dossier_link = ""
        dossier_id = str(item.get("dossierId") or "")
        target = publishable_by_id.get(dossier_id)
        if target:
            dossier_link = (
                f'<a href="{dossier_href(target, slug_by_id)}">'
                "Dosarul asociat →</a>"
            )

        source = item.get("source") or {}
        if isinstance(source, str):
            source = {"url": source}
        source_url = (
            safe_url(source.get("url"))
            if isinstance(source, dict)
            else None
        )
        source_link = (
            f'<a href="{esc(source_url)}" target="_blank" rel="noreferrer">Sursa ↗</a>'
            if source_url
            else ""
        )
        news_rows.append(
            '<article class="changeRow">'
            f"<div><span>{esc(item.get('kind') or 'ACTUALIZARE')}</span>"
            f"<time>{esc(item.get('date') or '')}</time></div>"
            f"<h2>{esc(headline)}</h2>"
            f"<p>{esc(meaning)}</p>"
            f"<div>{dossier_link}{source_link}</div>"
            "</article>"
        )

    changes_body = f"""
<section class="staticHero compact">
  <div class="eyebrow">Doar schimbări cu utilitate</div>
  <h1>Ce s-a schimbat</h1>
  <p>Actualizări legate de apeluri și dosare. O modificare de pagină nu devine automat schimbare materială.</p>
</section>
<section class="changesList">{''.join(news_rows[:150]) or '<div class="empty">Nu există schimbări publicabile în proiecția curentă.</div>'}</section>
"""
    write_page(
        web_root,
        "schimbari/index.html",
        page_shell(
            title="Ce s-a schimbat în finanțări",
            description=(
                "Actualizări PARTENER.EU cu utilitate decizională, legate de "
                "apeluri, dosare și surse."
            ),
            path="/schimbari/",
            body=changes_body,
            current_nav="schimbari",
        ),
    )

    write_page(
        web_root,
        "robots.txt",
        "User-agent: *\nAllow: /\n\nSitemap: https://partener.eu/sitemap.xml\n",
    )

    urls: list[tuple[str, str | None]] = [
        ("/", None),
        ("/finantari/", latest_lastmod(publishable, "updatedAt")),
        ("/finantari/deschise/", latest_lastmod(open_rows, "updatedAt")),
        ("/finantari/in-pregatire/", latest_lastmod(prepare_rows, "updatedAt")),
        ("/consultari/", latest_lastmod(consultation_rows, "updatedAt")),
        ("/dosare/", latest_lastmod(publishable, "updatedAt")),
        ("/schimbari/", latest_lastmod(visible_home_news, "date")),
    ]
    for dossier in publishable:
        urls.append(
            (
                dossier_href(dossier, slug_by_id),
                meaningful_lastmod(dossier.get("updatedAt")),
            )
        )

    sitemap_nodes = []
    for path, lastmod in urls:
        node = f"  <url><loc>{xml_escape(canonical(path))}</loc>"
        if lastmod:
            node += f"<lastmod>{xml_escape(lastmod)}</lastmod>"
        node += "</url>"
        sitemap_nodes.append(node)

    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(sitemap_nodes)
        + "\n</urlset>\n"
    )
    write_page(web_root, "sitemap.xml", sitemap)

    try:
        generated_from = str(products_path.relative_to(ROOT))
    except ValueError:
        generated_from = str(products_path)

    manifest = {
        "schemaVersion": 1,
        "generatedFrom": generated_from,
        "generatedAt": payload.get("generatedAt"),
        "publishableDossiers": len(publishable),
        "currentOpen": len(open_rows),
        "prepare": len(prepare_rows),
        "consultations": len(consultation_rows),
        "failClosedOpenRefresh": fail_closed_open_refresh_count,
        "sitemapUrls": len(urls),
        "homeSnapshotBytes": home_snapshot_bytes,
        "homeSnapshotDossiers": len(snapshot_rows),
        "homeSnapshotNews": len(home_payload["news"]),
        "policy": {
            "materialFactsInvented": False,
            "provisionalFailClosedIndexed": False,
            "queryPagesInSitemap": False,
            "openRequiresConfirmedCurrentDeadline": True,
            "expiredOrUnverifiedOpenRenderedAsReview": True,
        },
    }
    write_page(
        web_root,
        "static-public-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_WEB)
    args = parser.parse_args()
    manifest = build(args.products, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
