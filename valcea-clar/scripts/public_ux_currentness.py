#!/usr/bin/env python3
"""Fail-closed current/archive + Local Life projection for VÂLCEA CLAR.

The durable live feed intentionally retains published archive stories. Reader
presentation must therefore distinguish the current set from the archive using
explicit runtime evidence. The canonical story manifest is the fallback source
of currentness when the feed compatibility projection does not carry
``active_now``/``archive_status`` fields.

Local Life event inventory is a separate structured product. The public UX must
render that canonical inventory instead of overwriting /unde-iesim/ with a
venue-only catalogue after every newsroom rebuild.

No fact, story body or publication decision is changed here.
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import public_ux_reset as base

_BASE_UNION = base.union_stories
_BASE_RENDER_HOME = base.render_home
TZ = ZoneInfo("Europe/Bucharest")
EVENTS = base.ROOT / "editorial" / "local_life_events.json"
STORY_MANIFEST = base.RUNTIME / "stiri" / "manifest.json"


def is_current(story: dict[str, Any]) -> bool:
    """Return currentness only from explicit evidence carried by a story."""
    if "active_now" in story:
        return story.get("active_now") is True
    return str(story.get("archive_status") or "").strip().lower() == "active"


def manifest_current_ids() -> set[str]:
    """Read canonical runtime currentness when the compatibility feed omits it."""
    try:
        manifest = base.load(STORY_MANIFEST, {"stories": []})
    except Exception:
        return set()
    return {
        str(row.get("id"))
        for row in manifest.get("stories") or []
        if isinstance(row, dict) and row.get("id") and is_current(row)
    }


def current_union(
    feed: dict[str, Any], archive: dict[str, Any]
) -> tuple[list[dict[str, Any]], set[str]]:
    stories, _legacy_live_ids = _BASE_UNION(feed, archive)
    manifest_ids = manifest_current_ids()
    current_ids: set[str] = set()
    for story in feed.get("stories") or []:
        if not isinstance(story, dict) or not story.get("id"):
            continue
        sid = str(story.get("id"))
        if is_current(story) or (
            "active_now" not in story
            and not str(story.get("archive_status") or "").strip()
            and sid in manifest_ids
        ):
            current_ids.add(sid)

    # The lead must come from the current set. Archive rows remain available for
    # context, but can never outrank a verified current story merely because the
    # compatibility feed sorts them first.
    stories.sort(
        key=lambda row: (
            0 if str(row.get("id")) in current_ids else 1,
            -base.stamp(row),
            -int(row.get("priority") or 0),
            str(row.get("id") or ""),
        )
    )
    return stories, current_ids


def no_current_home(
    nav: dict[str, Any], feed: dict[str, Any], stories: list[dict[str, Any]]
) -> str:
    """Render an explicit no-current state; never disguise archive as a live lead."""
    archive = stories[:6]
    archive_cards = "".join(base.card(row, set()) for row in archive)
    archive_block = (
        '<section class="section" id="arhiva-verificata">'
        '<div class="section-head"><h2>Arhivă verificată</h2>'
        '<a href="/stiri/">Vezi toate materialele</a></div>'
        f'<div class="cards">{archive_cards}</div></section>'
        if archive_cards else ""
    )
    body = (
        '<main><div class="live-strip"><div><strong>Actualizat</strong> '
        f'<span>{base.esc(feed.get("generated_at"))}</span></div>'
        '<span>0 materiale în fluxul curent</span></div>'
        '<section class="section"><div class="kicker">FLUX CURENT</div>'
        '<h1 class="index-title">Nu avem acum o știre nouă verificată.</h1>'
        '<p class="index-dek">Nu promovăm un material vechi drept noutate doar pentru a umple homepage-ul. '
        'Materialele publicate anterior rămân disponibile mai jos, marcate explicit ca arhivă.</p></section>'
        f'{archive_block}</main>'
    )
    return base.shell(
        nav,
        title="VÂLCEA CLAR — Știri din Vâlcea",
        description="Știri locale verificate din Vâlcea, cu separare clară între fluxul curent și arhivă.",
        canonical=base.BASE + "/",
        body=body,
    )


def current_home(
    nav: dict[str, Any], feed: dict[str, Any], stories: list[dict[str, Any]], current_ids: set[str]
) -> str:
    if not current_ids:
        return no_current_home(nav, feed, stories)
    return _BASE_RENDER_HOME(nav, feed, stories, current_ids)


def parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def eligible_events(doc: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Return future event rows that satisfy the canonical freshness contract."""
    effective_now = (now or datetime.now(TZ)).astimezone(TZ)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in doc.get("events") or []:
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        fingerprint = str(raw.get("fingerprint") or "").strip()
        source_url = str(raw.get("source_url") or "").strip()
        source_tier = str(raw.get("source_tier") or "").strip()
        event_start = parse_dt(raw.get("event_start"))
        checked = parse_dt(raw.get("checked_at"))
        status = str(raw.get("status") or "unknown").strip().lower()
        if not event_id or not fingerprint or not source_url or not source_tier or not event_start or not checked:
            continue
        if event_id in seen:
            continue
        if event_start.date() < effective_now.date() or status == "past":
            continue
        days = (event_start.date() - effective_now.date()).days
        age_hours = max(0.0, (effective_now - checked).total_seconds() / 3600.0)
        if days <= 1 and age_hours > 12:
            continue
        if days <= 7 and age_hours > 48:
            continue
        row = dict(raw)
        rows.append(row)
        seen.add(event_id)
    rows.sort(key=lambda row: (str(row.get("event_start") or ""), str(row.get("start_time") or ""), str(row.get("title") or "")))
    return rows


def event_status_label(value: object) -> str:
    return {
        "scheduled": "programat",
        "changed": "modificat",
        "cancelled": "anulat",
        "sold_out": "bilete epuizate",
        "unknown": "status de verificat",
    }.get(str(value or "").strip().lower(), "status de verificat")


def event_card(row: dict[str, Any]) -> str:
    when = str(row.get("event_start") or "")
    if row.get("start_time"):
        when += " · " + str(row.get("start_time"))
    price = row.get("price")
    price_text = "Preț/acces neconfirmat" if price in (None, "", "unknown") else str(price)
    source = str(row.get("source_url") or "")
    ticket = str(row.get("ticket_url") or row.get("reservation_url") or "").strip()
    action = f' · <a href="{base.esc(ticket)}" rel="nofollow noopener">bilete/rezervare</a>' if ticket else ""
    return (
        '<article class="list-row"><div>'
        f'<div class="kicker">{base.esc(str(row.get("category") or "EVENIMENT").upper())}</div>'
        f'<div class="story-date">{base.esc(event_status_label(row.get("status")))}</div></div><div>'
        f'<h2>{base.esc(row.get("title"))}</h2>'
        f'<p><strong>{base.esc(when)}</strong> · {base.esc(row.get("venue"))} · {base.esc(row.get("locality"))}</p>'
        f'<p>{base.esc(price_text)}</p>'
        f'<div class="sources"><a href="{base.esc(source)}" rel="nofollow noopener">Sursă</a>'
        f'{action} · verificat {base.esc(row.get("checked_at"))}</div></div></article>'
    )


def event_aware_venues(nav: dict[str, Any], feed: dict[str, Any]) -> str:
    event_doc = base.load(EVENTS, {"events": []})
    events = eligible_events(event_doc)
    event_html = "".join(event_card(row) for row in events)
    event_section = (
        '<section class="all-list" id="evenimente">'
        '<div class="section-head"><h2>Evenimente verificate</h2></div>'
        f'{event_html}</section>'
        if event_html else '<p class="empty">Nu există acum evenimente viitoare care trec pragul de prospețime.</p>'
    )
    venues = "".join(
        f'<a class="venue" href="/unde-iesim/local/{base.esc(place.get("slug") or place.get("id"))}/">'
        f'<strong>{base.esc(place.get("name"))}</strong>'
        f'<span>{base.esc(place.get("summary") or "Fișă verificată editorial.")}</span></a>'
        for place in feed.get("unde_iesim") or []
    )
    venue_section = (
        '<section class="section" id="locuri"><div class="section-head"><h2>Locuri</h2></div>'
        f'<div class="venue-grid">{venues}</div></section>'
        if venues else ""
    )
    body = (
        '<main><div class="kicker">LOCAL LIFE</div><h1 class="index-title">Unde ieșim</h1>'
        '<p class="index-dek">Evenimentele sunt ordonate cronologic și apar numai cât timp sursa și verificarea sunt suficient de proaspete. '
        'Prețul, accesul și sold-out-ul rămân necunoscute dacă nu există dovadă.</p>'
        f'{event_section}{venue_section}</main>'
    )
    return base.shell(
        nav,
        title="Unde ieșim — VÂLCEA CLAR",
        description="Agenda verificată și ghidul local VÂLCEA CLAR pentru județul Vâlcea.",
        canonical=base.BASE + "/unde-iesim/",
        body=body,
    )


def complete_about(nav: dict[str, Any]) -> str:
    principles = [
        ("01", "Fapte, nu completări", "Publicăm numai ceea ce poate fi atribuit unei surse identificabile. Necunoscutele rămân marcate ca necunoscute."),
        ("02", "Sursa la final", "Cititorul primește întâi produsul jurnalistic complet. Documentele originale sunt păstrate la finalul fiecărei știri."),
        ("03", "Drept la replică", "Subiectele critice cer poziția persoanei sau instituției vizate și separarea acuzației de faptul demonstrat."),
        ("04", "Corecții vizibile", "Dacă schimbăm o informație publicată, corecția rămâne vizibilă și explică ce s-a modificat și de ce."),
        ("05", "Imagini reale", "Folosim imagini numai când proveniența și dreptul de utilizare sunt clare. În lipsa lor, preferăm textul unei imagini care ar putea induce în eroare."),
        ("06", "Distribuție responsabilă", "Pe rețele distribuim numai materiale care au trecut aceleași reguli de verificare ca site-ul; titlul social nu poate exagera concluzia articolului."),
    ]
    grid = "".join(
        f'<section class="principle"><div class="num">{num}</div><h2>{base.esc(title)}</h2><p>{base.esc(text)}</p></section>'
        for num, title, text in principles
    )
    body = (
        '<main><div class="kicker">DESPRE PUBLICAȚIE</div>'
        '<h1 class="index-title">Clar înainte de rapid.</h1>'
        '<p class="index-dek">VÂLCEA CLAR este o publicație locală construită în jurul documentului, contextului și utilității pentru cititor.</p>'
        f'<div class="about-grid">{grid}</div></main>'
    )
    return base.shell(
        nav,
        title="Despre VÂLCEA CLAR",
        description="Principiile editoriale VÂLCEA CLAR.",
        canonical=base.BASE + "/despre/",
        body=body,
    )


def install() -> None:
    base.union_stories = current_union
    base.render_home = current_home
    base.render_venues = event_aware_venues
    base.render_about = complete_about


def self_test() -> None:
    feed = {
        "generated_at": "2026-09-23T15:00:00Z",
        "stories": [
            {"id": "active", "section": "MOBILITATE", "headline": "Active", "dek": "D", "paragraphs": ["P"], "sources": [{"url": "https://example.test/active"}], "active_now": True, "archive_status": "active"},
            {"id": "archive-in-feed", "section": "CULTURĂ", "headline": "Archive", "dek": "D", "paragraphs": ["P"], "sources": [{"url": "https://example.test/archive"}], "active_now": False, "archive_status": "published_archive"},
        ],
    }
    archive = {"stories": []}
    rows, current_ids = current_union(feed, archive)
    assert {str(row.get("id")) for row in rows} == {"active", "archive-in-feed"}
    assert current_ids == {"active"}
    assert str(rows[0].get("id")) == "active"
    assert is_current({"active_now": False, "archive_status": "active"}) is False
    assert is_current({"archive_status": "published_archive"}) is False
    assert is_current({}) is False

    sample_events = {"events": [
        {"event_id": "e1", "fingerprint": "fp1", "title": "Test Drăgășani", "event_start": "2026-09-24", "start_time": "19:00", "venue": "Casa de Cultură", "locality": "Drăgășani", "category": "teatru", "price": "unknown", "source_url": "https://example.test/e1", "source_tier": "T1", "checked_at": "2026-09-23T17:00:00+03:00", "status": "scheduled"},
        {"event_id": "e2", "fingerprint": "fp2", "title": "Stale", "event_start": "2026-09-24", "venue": "V", "locality": "L", "source_url": "https://example.test/e2", "source_tier": "T1", "checked_at": "2026-09-22T01:00:00+03:00", "status": "scheduled"},
    ]}
    eligible = eligible_events(sample_events, datetime(2026, 9, 23, 18, 0, tzinfo=TZ))
    assert [row["event_id"] for row in eligible] == ["e1"]
    assert "Drăgășani" in event_card(eligible[0])

    nav = {
        "contract_id": "valcea-clar-primary-v2",
        "brand": "VÂLCEA CLAR",
        "tagline": "Știrile Vâlcii, fără zgomot.",
        "items": [{"label": "Acasă", "href": "/"}],
        "footer": {"line": "VÂLCEA CLAR", "links": []},
    }
    no_live = no_current_home(nav, feed, rows)
    assert "Nu avem acum o știre nouă verificată" in no_live
    assert "ARHIVĂ" in no_live
    about = complete_about(nav)
    assert "Corecții vizibile" in about and "ce s-a modificat și de ce" in about
    assert "Imagini reale" in about and "proveniența" in about
    assert "Distribuție responsabilă" in about and "titlul social" in about
    print("VÂLCEA CLAR public UX current/archive + Local Life projection self-test: PASS")


def main() -> int:
    install()
    if "--self-test" in sys.argv[1:]:
        self_test()
        base.self_test()
        return 0
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
